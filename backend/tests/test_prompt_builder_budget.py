"""Hypothesis property tests for prompt_builder budgeting & eviction order.

The production builder in ``backend/graph/prompt_builder.py`` composes the
system prompt from many on-disk sources (workspace files, MEMORY index,
scoped typed notes, ancestor project instruction trees with ``@``-refs,
optional git context, retrieved memory blocks). This suite pins down the
declared per-source caps and the documented eviction order against
randomised inputs.

All tests are offline: subprocess is stubbed for git, and ancestor dir
discovery is constrained to the per-example tmp workspace so host-machine
``AGENTS.md`` / ``CLAW.md`` files cannot leak into the prompt under test.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph import prompt_builder
from graph.prompt_builder import (
    MAX_COMPONENT_CHARS,
    MAX_GIT_CONTEXT_CHARS,
    MAX_MEMORY_INDEX_CHARS,
    MAX_PROJECT_INSTRUCTION_FILE_CHARS,
    MAX_PROJECT_INSTRUCTION_TOTAL_CHARS,
    MAX_RETRIEVED_MEMORY_BLOCK_CHARS,
    MAX_RETRIEVED_MEMORY_ITEM_CHARS,
    MAX_SCOPED_MEMORY_BLOCK_CHARS,
    _PROJECT_INSTRUCTION_FILENAMES,
    _PROJECT_INSTRUCTION_RELATIVE_PATHS,
    _build_project_instruction_context,
    _build_scoped_memory_listing,
    build_retrieved_memory_block,
    build_system_prompt,
)


# Markers the builder appends on truncation. Kept here to make cap-bound
# assertions explicit: max length = declared cap + len(marker).
FILE_TRUNCATE_MARKER = "\n...[truncated]"
RETRIEVED_BLOCK_MARKER = "\n...[retrieved memory truncated]"
RETRIEVED_ITEM_MARKER = "..."


_COMMON_SETTINGS = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------


def _printable(max_size: int) -> st.SearchStrategy[str]:
    """Printable ASCII, bounded, no frontmatter/YAML escape hazards."""
    return st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        min_size=0,
        max_size=max_size,
    )


_filename_stem = st.from_regex(r"[a-z][a-z0-9_-]{0,11}", fullmatch=True)
_scope_name = st.sampled_from(("project", "user", "agent"))

_retrieved_result = st.fixed_dictionaries(
    mapping={
        "source": st.from_regex(
            r"memory/(project|user|agent)/[a-z0-9_-]{1,16}\.md(#[a-z0-9-]{1,16})?",
            fullmatch=True,
        ),
        "text": _printable(MAX_RETRIEVED_MEMORY_ITEM_CHARS * 4),
    },
    optional={
        "memory_type": st.sampled_from(
            ("workflow_heuristic", "project_fact", "user_preference", "")
        ),
        "memory_type_label": st.sampled_from(
            ("workflow heuristic", "project fact", "user preference", "")
        ),
        "memory_name": st.one_of(
            st.just(""),
            st.text(
                min_size=1,
                max_size=30,
                alphabet="abcdefghijklmnopqrstuvwxyz ",
            ),
        ),
    },
)


# NOTE: age_days intentionally skips the threshold boundary (we configure
# BIOAPEX_PROMPT_MEMORY_STALE_DAYS=10 in a fixture). The builder calls
# datetime.now() after the test does, so an entry written at exactly the
# threshold can flip stale by the time the builder looks; keep the gap wide.
_age_days = st.one_of(
    st.integers(min_value=0, max_value=5),
    st.integers(min_value=20, max_value=365),
)

# Keep name/description out of YAML trouble — no ':' / '#' / quotes.
_yaml_safe_text = st.one_of(
    st.just(""),
    st.text(
        min_size=1,
        max_size=30,
        alphabet="abcdefghijklmnopqrstuvwxyz ",
    ),
)

_scoped_memory_entry = st.fixed_dictionaries(
    {
        "stem": _filename_stem,
        "scope": _scope_name,
        "pinned": st.booleans(),
        "age_days": _age_days,
        "name": _yaml_safe_text,
        "description": _yaml_safe_text,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_workspace(tmp_path_factory) -> Callable[[], Path]:
    """Return a factory that hands out a fresh tmp dir per hypothesis example.

    Hypothesis re-runs a decorated test many times within a single
    ``tmp_path``; instead we ask ``tmp_path_factory`` for a new directory per
    example so earlier examples cannot taint later ones.
    """

    def _make() -> Path:
        return tmp_path_factory.mktemp("pb_budget")

    return _make


@pytest.fixture(autouse=True)
def _restrict_ancestor_discovery(monkeypatch) -> None:
    """Stop project-instruction discovery from walking above the workspace.

    The real ``_iter_ancestor_dirs`` walks all the way to ``/``. A stray
    ``AGENTS.md`` or ``CLAW.md`` in ``/tmp`` or the test host's home
    directory would silently leak into the prompt under test. Clamp the
    walk to the workspace root.
    """
    monkeypatch.setattr(
        prompt_builder,
        "_iter_ancestor_dirs",
        lambda start: [Path(start).resolve()],
    )


@pytest.fixture(autouse=True)
def _deterministic_memory_stale_days(monkeypatch) -> None:
    """Use a fixed stale threshold so ``age_days`` strategy is interpretable."""
    monkeypatch.setenv("BIOAPEX_PROMPT_MEMORY_STALE_DAYS", "10")


def _write_scoped_memory_file(
    memory_root: Path,
    entry: dict,
    now: datetime,
) -> Path:
    scope_dir = memory_root / entry["scope"]
    scope_dir.mkdir(parents=True, exist_ok=True)
    updated_at = now - timedelta(days=entry["age_days"])
    frontmatter = (
        "---\n"
        f"type: project_fact\n"
        f"name: {entry['name']}\n"
        f"description: {entry['description']}\n"
        f"pinned: {'true' if entry['pinned'] else 'false'}\n"
        f"updated_at: {updated_at.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        "---\n"
        "body\n"
    )
    path = scope_dir / f"{entry['stem']}.md"
    path.write_text(frontmatter, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# build_retrieved_memory_block — bounded output, per-item truncation
# ---------------------------------------------------------------------------


class TestRetrievedMemoryBudget:
    @_COMMON_SETTINGS
    @given(results=st.lists(_retrieved_result, min_size=0, max_size=25))
    def test_block_fits_within_declared_cap(self, results):
        block = build_retrieved_memory_block(results)
        assert len(block) <= MAX_RETRIEVED_MEMORY_BLOCK_CHARS + len(
            RETRIEVED_BLOCK_MARKER
        )

    @_COMMON_SETTINGS
    @given(
        source=st.from_regex(
            r"memory/(project|user|agent)/[a-z0-9_-]{1,16}\.md",
            fullmatch=True,
        ),
        text_size=st.integers(
            min_value=1, max_value=MAX_RETRIEVED_MEMORY_ITEM_CHARS * 3
        ),
    )
    def test_item_text_truncated_to_declared_cap(self, source, text_size):
        # Use a non-whitespace filler so `" ".join(text.split())` is a no-op —
        # this isolates the item-level truncation from whitespace compaction.
        text = "x" * text_size
        block = build_retrieved_memory_block(
            [{"source": source, "text": text}]
        )

        lines = block.splitlines()
        assert len(lines) == 2, block  # header + single item line
        prefix = f"- @ {source}: "
        assert lines[1].startswith(prefix)
        body = lines[1][len(prefix):]
        assert len(body) <= MAX_RETRIEVED_MEMORY_ITEM_CHARS + len(
            RETRIEVED_ITEM_MARKER
        )
        if text_size > MAX_RETRIEVED_MEMORY_ITEM_CHARS:
            assert body.endswith(RETRIEVED_ITEM_MARKER)


# ---------------------------------------------------------------------------
# Workspace components (SOUL / IDENTITY / USER / AGENTS) + MEMORY.md index
# ---------------------------------------------------------------------------


_WORKSPACE_MARKERS = {
    "SOUL.md": "<!-- Soul -->\n",
    "IDENTITY.md": "<!-- Identity -->\n",
    "USER.md": "<!-- User Profile -->\n",
    "AGENTS.md": "<!-- Agents Guide -->\n",
}


class TestWorkspaceComponentBudgets:
    @_COMMON_SETTINGS
    @given(
        filename=st.sampled_from(sorted(_WORKSPACE_MARKERS.keys())),
        size=st.integers(
            min_value=0, max_value=MAX_COMPONENT_CHARS + 2_000
        ),
    )
    def test_workspace_component_capped_at_declared_limit(
        self, fresh_workspace, filename, size
    ):
        root = fresh_workspace()
        (root / "workspace").mkdir()
        (root / "workspace" / filename).write_text("A" * size, encoding="utf-8")

        prompt = build_system_prompt(root, rag_mode=True)

        marker = _WORKSPACE_MARKERS[filename]
        if size == 0:
            # Empty file is skipped entirely — no header emitted.
            assert marker not in prompt
            return
        assert marker in prompt
        _, _, after = prompt.partition(marker)
        block = after.split("\n\n", 1)[0]
        assert len(block) <= MAX_COMPONENT_CHARS + len(FILE_TRUNCATE_MARKER)

    @_COMMON_SETTINGS
    @given(
        size=st.integers(
            min_value=0, max_value=MAX_MEMORY_INDEX_CHARS + 2_000
        ),
    )
    def test_memory_index_capped_at_index_budget(self, fresh_workspace, size):
        root = fresh_workspace()
        (root / "memory").mkdir()
        (root / "memory" / "MEMORY.md").write_text("M" * size, encoding="utf-8")

        prompt = build_system_prompt(root, rag_mode=False)

        marker = "<!-- Long-term Memory -->\n"
        if size == 0:
            assert marker not in prompt
            return
        assert marker in prompt
        _, _, after = prompt.partition(marker)
        block = after.split("\n\n", 1)[0]
        # Index uses the tighter per-index cap, not MAX_COMPONENT_CHARS.
        assert len(block) <= MAX_MEMORY_INDEX_CHARS + len(FILE_TRUNCATE_MARKER)


# ---------------------------------------------------------------------------
# Project instruction context — total cap + deterministic eviction
# ---------------------------------------------------------------------------


class TestProjectInstructionContext:
    @_COMMON_SETTINGS
    @given(
        sizes=st.dictionaries(
            keys=st.sampled_from(list(_PROJECT_INSTRUCTION_FILENAMES)),
            values=st.integers(
                min_value=0,
                max_value=MAX_PROJECT_INSTRUCTION_FILE_CHARS * 3,
            ),
            min_size=0,
            max_size=len(_PROJECT_INSTRUCTION_FILENAMES),
        )
    )
    def test_total_output_fits_within_total_budget(self, fresh_workspace, sizes):
        root = fresh_workspace()
        for filename, size in sizes.items():
            if size == 0:
                continue
            (root / filename).write_text("P" * size, encoding="utf-8")

        output = _build_project_instruction_context(root)

        # Content bytes are capped at MAX_PROJECT_INSTRUCTION_TOTAL_CHARS; the
        # remaining overhead comes from section-header comments and at most one
        # truncation marker per included file. The number of includable files
        # is bounded by len(_PROJECT_INSTRUCTION_FILENAMES) +
        # len(_PROJECT_INSTRUCTION_RELATIVE_PATHS), so overhead stays small.
        max_sections = (
            len(_PROJECT_INSTRUCTION_FILENAMES)
            + len(_PROJECT_INSTRUCTION_RELATIVE_PATHS)
        )
        # Per-section header is "<!-- Project Instructions: <name> -->\n" —
        # generously bound at 200 chars, plus the one "<!-- Project Context -->"
        # eviction marker (~60 chars) at the end.
        overhead_budget = max_sections * (200 + len(FILE_TRUNCATE_MARKER)) + 200
        assert (
            len(output)
            <= MAX_PROJECT_INSTRUCTION_TOTAL_CHARS + overhead_budget
        )

    def test_eviction_is_top_down_and_filename_order(self, fresh_workspace):
        """When earlier files exhaust the total budget, later files are dropped.

        Documented policy (see prompt_builder module docstring / code):
          1. Ancestors are walked top-down (root → base_dir).
          2. Within a directory, files are probed in
             ``_PROJECT_INSTRUCTION_FILENAMES`` order, then
             ``_PROJECT_INSTRUCTION_RELATIVE_PATHS``.
          3. ``@``-references within a file are loaded right after that file.
          4. Reads are capped at min(file cap, remaining total budget); when
             remaining hits 0, later files are skipped entirely.
        """
        root = fresh_workspace()

        # AGENTS.md references four oversized files. Each reference will be
        # truncated to MAX_PROJECT_INSTRUCTION_FILE_CHARS; combined they drain
        # the 8k total budget before CLAW.md gets a chance.
        reference_body = "R" * (MAX_PROJECT_INSTRUCTION_FILE_CHARS * 3)
        ref_lines = []
        for idx in range(4):
            ref_path = root / f"ref{idx}.md"
            ref_path.write_text(reference_body, encoding="utf-8")
            ref_lines.append(f"- @ref{idx}.md")
        agents_body = "Root instructions.\n" + "\n".join(ref_lines) + "\n"
        (root / "AGENTS.md").write_text(agents_body, encoding="utf-8")

        # CLAW.md has a distinct marker so we can verify eviction.
        (root / "CLAW.md").write_text(
            "claw-marker-should-not-appear", encoding="utf-8"
        )
        (root / "CLAW.local.md").write_text(
            "claw-local-marker-should-not-appear", encoding="utf-8"
        )

        output = _build_project_instruction_context(root)

        # AGENTS.md and its first reference always win the race.
        assert "<!-- Project Instructions: AGENTS.md -->" in output
        assert "<!-- Project Context File: ref0.md -->" in output

        # CLAW.md and CLAW.local.md appear later in the filename order; the
        # total budget is exhausted before they are read.
        assert "<!-- Project Instructions: CLAW.md -->" not in output
        assert "claw-marker-should-not-appear" not in output
        assert "<!-- Project Instructions: CLAW.local.md -->" not in output
        assert "claw-local-marker-should-not-appear" not in output

        # Once the total budget is exhausted, the builder appends a visible
        # "context truncated" eviction marker so reviewers can see what was cut.
        assert "...[project context truncated]" in output

    def test_reference_loaded_immediately_after_parent(self, fresh_workspace):
        """References are attached to the parent instruction file, not deferred."""
        root = fresh_workspace()
        (root / "AGENTS.md").write_text(
            "agents header\n- @ref_after_parent.md\n", encoding="utf-8"
        )
        (root / "ref_after_parent.md").write_text(
            "reference payload", encoding="utf-8"
        )
        # CLAW.md comes AFTER AGENTS.md in _PROJECT_INSTRUCTION_FILENAMES; but
        # its reference would be attached to CLAW.md, not to AGENTS.md. Keep it
        # small so the reference can also fit.
        (root / "CLAW.md").write_text("claw marker", encoding="utf-8")

        output = _build_project_instruction_context(root)

        agents_pos = output.find("<!-- Project Instructions: AGENTS.md -->")
        ref_pos = output.find("<!-- Project Context File: ref_after_parent.md -->")
        claw_pos = output.find("<!-- Project Instructions: CLAW.md -->")

        assert agents_pos != -1 and ref_pos != -1 and claw_pos != -1
        # Reference is inserted between its parent and the next instruction file.
        assert agents_pos < ref_pos < claw_pos


# ---------------------------------------------------------------------------
# Scoped memory listing — filter stale + deterministic order
# ---------------------------------------------------------------------------


class TestScopedMemoryListing:
    @_COMMON_SETTINGS
    @given(
        entries=st.lists(
            _scoped_memory_entry,
            min_size=0,
            max_size=12,
            unique_by=lambda e: (e["scope"], e["stem"]),
        ),
    )
    def test_listing_bounded_and_filters_stale_unpinned(
        self, fresh_workspace, entries
    ):
        root = fresh_workspace()
        now = datetime.now(timezone.utc)
        paths_written: list[tuple[dict, Path]] = []
        for entry in entries:
            path = _write_scoped_memory_file(root / "memory", entry, now)
            paths_written.append((entry, path))

        output = _build_scoped_memory_listing(root)
        assert len(output) <= MAX_SCOPED_MEMORY_BLOCK_CHARS + len(
            FILE_TRUNCATE_MARKER
        )

        # Parse listed paths precisely — the formatter appends ": desc" or
        # " — name" after the path with no leading space, so a naive
        # split(" ") leaves a trailing ":" on the path token.
        listed = set(
            re.findall(r"memory/(?:project|user|agent)/[a-z0-9_-]+\.md", output)
        )
        # A note is included iff it is pinned OR younger than the stale
        # threshold (we configured 10 days via the autouse fixture, and the
        # age_days strategy avoids the 6-19 boundary window).
        for entry, _ in paths_written:
            rel = f"memory/{entry['scope']}/{entry['stem']}.md"
            should_include = entry["pinned"] or entry["age_days"] <= 5
            if should_include:
                assert rel in listed, (rel, entry)
            else:
                assert rel not in listed, (rel, entry)

    def test_listing_order_is_project_then_user_then_agent_glob_sorted(
        self, fresh_workspace
    ):
        """Policy: iterate scopes in ``_MEMORY_SCOPE_DIRS`` order; within each
        scope emit ``*.md`` entries in glob-sorted (alphabetical) order.
        """
        root = fresh_workspace()
        now = datetime.now(timezone.utc)
        # Deliberately write out-of-order to prove the builder does the sort.
        fresh_names = [
            ("project", "zzz"),
            ("project", "aaa"),
            ("project", "mmm"),
            ("user", "yankee"),
            ("user", "alpha"),
            ("agent", "whiskey"),
            ("agent", "bravo"),
        ]
        for scope, stem in fresh_names:
            _write_scoped_memory_file(
                root / "memory",
                {
                    "scope": scope,
                    "stem": stem,
                    "pinned": False,
                    "age_days": 0,
                    "name": "",
                    "description": "",
                },
                now,
            )

        output = _build_scoped_memory_listing(root)
        lines = re.findall(
            r"memory/(?:project|user|agent)/[a-z0-9_-]+\.md",
            output,
        )

        expected = [
            "memory/project/aaa.md",
            "memory/project/mmm.md",
            "memory/project/zzz.md",
            "memory/user/alpha.md",
            "memory/user/yankee.md",
            "memory/agent/bravo.md",
            "memory/agent/whiskey.md",
        ]
        assert lines == expected


# ---------------------------------------------------------------------------
# Git context — offline, capped output
# ---------------------------------------------------------------------------


class TestGitContextBudget:
    @_COMMON_SETTINGS
    @given(
        status_size=st.integers(min_value=0, max_value=MAX_GIT_CONTEXT_CHARS * 2),
        diff_size=st.integers(min_value=0, max_value=MAX_GIT_CONTEXT_CHARS * 2),
    )
    def test_git_context_stays_under_cap(
        self, fresh_workspace, monkeypatch, status_size, diff_size
    ):
        root = fresh_workspace()
        monkeypatch.setenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "1")

        status_payload = "S" * status_size
        diff_payload = "D" * diff_size

        def fake_run(cmd, cwd=None, capture_output=True, text=True, check=False):
            class _Completed:
                returncode = 0

            completed = _Completed()
            # cmd is ["git", <subcommand>, ...]
            subcommand = cmd[1] if len(cmd) > 1 else ""
            completed.stdout = (
                status_payload if subcommand == "status" else diff_payload
            )
            completed.stderr = ""
            return completed

        monkeypatch.setattr(prompt_builder.subprocess, "run", fake_run)

        prompt = build_system_prompt(root, rag_mode=True)

        marker = "<!-- Project Git Context -->\n"
        if status_size == 0 and diff_size == 0:
            assert marker not in prompt
            return
        assert marker in prompt
        _, _, after = prompt.partition(marker)
        block = after.split("\n\n", 1)[0]
        assert len(block) <= MAX_GIT_CONTEXT_CHARS + len(FILE_TRUNCATE_MARKER)
