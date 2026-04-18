from __future__ import annotations

# ─── Prompt budget + eviction policy ─────────────────────────────────────
# Per-section character budgets are loaded from the runtime config block
# ``prompt_budget`` (see ``config.get_prompt_budget``). Each section is
# truncated in place to its own cap with a visible truncation marker. When the
# optional ``prompt_budget.total_max_chars`` global cap is set (> 0), sections
# are dropped wholesale in the order below — least-load-bearing first — until
# the assembled prompt fits under the cap. The static Tool Result Error
# Contract guidance is never evicted.
#
#   1. git_context           (transient working-tree snapshot)
#   2. retrieved_memory      (RAG pulls; can be re-fetched next turn)
#   3. scoped_memory         (typed-note index; recoverable from disk)
#   4. memory_index          (curated MEMORY.md pointer file)
#   5. project_instructions  (AGENTS.md / CLAW.md and references)
#   6. skills_snapshot       (registry snapshot of available skills)
#   7. user_profile          (workspace/USER.md)
#   8. agents_guide          (workspace/AGENTS.md)
#   9. identity              (workspace/IDENTITY.md)
#  10. soul                  (workspace/SOUL.md — the durable agent contract)
#
# SOUL/IDENTITY/AGENTS are dropped only as a last resort. See
# ``context/ai-interaction.md`` for the rationale and configuration surface.
# ─────────────────────────────────────────────────────────────────────────
#
# ─── Prompt-cache friendly ordering ──────────────────────────────────────
# The assembled prompt is split into a *stable prefix* (identical across turns
# as long as workspace + skill registry + ancestor AGENTS.md + CLAW.md are
# unchanged) followed by a *volatile suffix* (per-turn state: memory index,
# scoped-memory listing, git working-tree snapshot). Keeping the stable prefix
# byte-identical across turns is what lets providers reuse the server-side
# attention KV cache:
#
#   • DeepSeek and OpenAI perform automatic prefix caching on prompts whose
#     leading tokens match the previous request byte-for-byte.
#   • Anthropic requires an explicit ``cache_control`` breakpoint at the end
#     of the stable prefix (see ``build_anthropic_system_blocks`` below).
#
# SECTIONS_IN_STABLE_PREFIX documents which section ids live in the stable
# portion. ``build_system_prompt_blocks`` returns the split explicitly so
# downstream call sites (``graph.agent._build_agent``) can pass structured
# message blocks to providers that need the breakpoint marker.
# ─────────────────────────────────────────────────────────────────────────

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

import config

# Module-level defaults mirror ``config._DEFAULT_PROMPT_BUDGET`` so callers and
# tests that import these constants continue to work. The runtime values used
# by ``build_system_prompt`` come from ``config.get_prompt_budget()``.
MAX_COMPONENT_CHARS = 20_000
MAX_PROJECT_INSTRUCTION_FILE_CHARS = 2_000
MAX_PROJECT_INSTRUCTION_TOTAL_CHARS = 8_000
MAX_GIT_CONTEXT_CHARS = 2_000
MAX_RETRIEVED_MEMORY_BLOCK_CHARS = 1_600
MAX_RETRIEVED_MEMORY_ITEM_CHARS = 280
MAX_SCOPED_MEMORY_BLOCK_CHARS = 4_000
MAX_MEMORY_INDEX_CHARS = 2_048

# Section identifiers used for eviction. Order is least- to most-load-bearing.
EVICTION_ORDER: tuple[str, ...] = (
    "git_context",
    "retrieved_memory",
    "scoped_memory",
    "memory_index",
    "project_instructions",
    "skills_snapshot",
    "user_profile",
    "agents_guide",
    "identity",
    "soul",
)

# Sections that belong to the prompt's stable prefix for prefix-cache reuse.
# Anything not in this set is treated as volatile (per-turn state) and placed
# after the cache breakpoint. Static guidance blocks (``_rag_memory_guidance``,
# ``_tool_result_error_contract``) are pinned stable and never evicted.
SECTIONS_IN_STABLE_PREFIX: frozenset[str] = frozenset({
    "skills_snapshot",
    "soul",
    "identity",
    "user_profile",
    "agents_guide",
    "project_instructions",
    "_tool_result_error_contract",
    "_rag_memory_guidance",
})

_MEMORY_SCOPE_DIRS = ("project", "user", "agent")

_RAG_MEMORY_GUIDANCE = (
    "<!-- Long-term Memory -->\n"
    "Your long-term memory is managed via RAG (Retrieval-Augmented Generation). "
    "Relevant memories will be dynamically retrieved and injected as context before each response. "
    "Use retrieved memory as background guidance only: it may include templates, heuristics, or "
    "prior-session notes. Do not present retrieved memory as something you verified in the current "
    "turn unless you explicitly inspected the referenced file or tool output."
)
_TOOL_RESULT_ERROR_GUIDANCE = (
    "<!-- Tool Result Error Contract -->\n"
    "Every tool call returns a structured envelope (contract_version = `tool_result.v1`) with a "
    "top-level `status` field (`success` or `error`), an `outcome` tag, and — when something went "
    "wrong — a populated `error` object of shape "
    "`{ code: 'blocked' | 'invalid_input' | 'retriable_failure' | 'execution_failure', "
    "message: string, retriable: boolean }`. If a wrapped tool raises an uncaught exception "
    "the wrapper will NOT silently drop it: it logs the traceback and returns an envelope with "
    "`status = 'error'` and `outcome = 'execution_failure'` (or `'retriable_failure'` for "
    "timeouts / connection / rate-limit style errors). Treat any envelope where `status == 'error'` "
    "as a failed call: do not assume the underlying action succeeded, do not fabricate output, and "
    "do not proceed with downstream steps that depend on the failed result. React based on "
    "`error.code`: retry only when `error.retriable` is true (after addressing the cause), ask the "
    "user or adjust inputs when `code == 'invalid_input'`, respect policy when `code == 'blocked'`, "
    "and surface the failure to the user with `error.message` when `code == 'execution_failure'`."
)
_PROJECT_REFERENCE_RE = re.compile(r"(?m)^\s*(?:[-*]\s+)?@(?P<path>[^\s#]+)")
_PROJECT_INSTRUCTION_FILENAMES = (
    "AGENTS.md",
    "CLAW.md",
    "CLAW.local.md",
)
_PROJECT_INSTRUCTION_RELATIVE_PATHS = (
    Path(".claw") / "CLAW.md",
    Path(".claw") / "instructions.md",
)


def _truncate_text(text: str, max_chars: int, *, marker: str = "\n...[truncated]") -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + marker, True


def _format_retrieved_memory_label(result: dict[str, Any]) -> str:
    source = result.get("source")
    if not isinstance(source, str) or not source:
        return ""

    label_parts: list[str] = []
    memory_type_label = result.get("memory_type_label")
    if not isinstance(memory_type_label, str) or not memory_type_label.strip():
        memory_type = result.get("memory_type")
        if isinstance(memory_type, str) and memory_type.strip():
            memory_type_label = memory_type.replace("_", " ")
    if isinstance(memory_type_label, str) and memory_type_label.strip():
        label_parts.append(f"[{memory_type_label.strip()}]")

    memory_name = result.get("memory_name")
    if isinstance(memory_name, str) and memory_name.strip():
        label_parts.append(memory_name.strip())

    label_parts.append(f"@ {source}")
    return " ".join(label_parts)


def build_retrieved_memory_block(
    results: list[dict],
    *,
    budget: dict[str, int] | None = None,
) -> str:
    block_cap = (budget or {}).get(
        "retrieved_memory_block_max_chars", MAX_RETRIEVED_MEMORY_BLOCK_CHARS
    )
    item_cap = (budget or {}).get(
        "retrieved_memory_item_max_chars", MAX_RETRIEVED_MEMORY_ITEM_CHARS
    )

    lines = ["[Retrieved Memory - background context only; not verified current project state]"]

    for result in results:
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        label = _format_retrieved_memory_label(result)
        if not label:
            continue

        compact_text = " ".join(text.split())
        compact_text, _ = _truncate_text(
            compact_text,
            item_cap,
            marker="...",
        )
        lines.append(f"- {label}: {compact_text}")

    if len(lines) == 1:
        return ""

    rendered = "\n".join(lines)
    rendered, _ = _truncate_text(
        rendered,
        block_cap,
        marker="\n...[retrieved memory truncated]",
    )
    return rendered


def _read_component(path: Path, *, max_chars: int = MAX_COMPONENT_CHARS) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    content, _ = _truncate_text(content, max_chars)
    return content


def _iter_ancestor_dirs(start: Path) -> list[Path]:
    directories: list[Path] = []
    current = start.resolve()
    while True:
        directories.append(current)
        if current.parent == current:
            break
        current = current.parent
    directories.reverse()
    return directories


def _discover_project_instruction_files(base_dir: Path) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for directory in _iter_ancestor_dirs(base_dir):
        candidates = [directory / name for name in _PROJECT_INSTRUCTION_FILENAMES]
        candidates.extend(directory / relative for relative in _PROJECT_INSTRUCTION_RELATIVE_PATHS)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not candidate.exists() or not candidate.is_file():
                continue
            seen.add(resolved)
            discovered.append(candidate)
    return discovered


def _extract_project_reference_files(instruction_file: Path, content: str) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for match in _PROJECT_REFERENCE_RE.finditer(content):
        raw_ref = match.group("path").strip()
        if not raw_ref or "://" in raw_ref or raw_ref.startswith("app://"):
            continue
        candidate = (instruction_file.parent / raw_ref).resolve()
        if candidate in seen or not candidate.exists() or not candidate.is_file():
            continue
        seen.add(candidate)
        discovered.append(candidate)
    return discovered


def _display_project_reference(instruction_file: Path, referenced_file: Path) -> str:
    try:
        return str(referenced_file.relative_to(instruction_file.parent))
    except ValueError:
        return referenced_file.name


def _build_project_instruction_context(
    base_dir: Path,
    *,
    budget: dict[str, int] | None = None,
) -> str:
    file_cap = (budget or {}).get(
        "project_instruction_file_max_chars", MAX_PROJECT_INSTRUCTION_FILE_CHARS
    )
    total_cap = (budget or {}).get(
        "project_instruction_total_max_chars", MAX_PROJECT_INSTRUCTION_TOTAL_CHARS
    )
    sections: list[str] = []
    seen: set[Path] = set()
    remaining_chars = total_cap

    for instruction_file in _discover_project_instruction_files(base_dir):
        resolved_instruction = instruction_file.resolve()
        if resolved_instruction in seen or remaining_chars <= 0:
            continue

        instruction_content = _read_component(
            instruction_file,
            max_chars=min(file_cap, remaining_chars),
        )
        if not instruction_content:
            continue

        seen.add(resolved_instruction)
        sections.append(
            f"<!-- Project Instructions: {instruction_file.name} -->\n{instruction_content}"
        )
        remaining_chars = max(0, remaining_chars - len(instruction_content))
        if remaining_chars <= 0:
            break

        for referenced_file in _extract_project_reference_files(
            instruction_file,
            instruction_content,
        ):
            resolved_reference = referenced_file.resolve()
            if resolved_reference in seen or remaining_chars <= 0:
                continue

            reference_content = _read_component(
                referenced_file,
                max_chars=min(file_cap, remaining_chars),
            )
            if not reference_content:
                continue

            seen.add(resolved_reference)
            sections.append(
                (
                    "<!-- Project Context File: "
                    f"{_display_project_reference(instruction_file, referenced_file)} -->\n"
                    f"{reference_content}"
                )
            )
            remaining_chars = max(0, remaining_chars - len(reference_content))

    if remaining_chars == 0:
        sections.append("<!-- Project Context -->\n...[project context truncated]")

    return "\n\n".join(sections)


def _run_git_command(base_dir: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=base_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""

    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _build_git_context(
    base_dir: Path,
    *,
    budget: dict[str, int] | None = None,
) -> str:
    include_git_context_env = os.getenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "").strip().lower()
    if include_git_context_env:
        include_git_context = include_git_context_env in {"1", "true", "yes", "on"}
    else:
        include_git_context = bool(
            config.get_prompt_context_settings().get("include_git_context", False)
        )
    if not include_git_context:
        return ""

    status = _run_git_command(base_dir, "status", "--short", "--branch")
    diff_stat = _run_git_command(base_dir, "diff", "--stat")

    if not status and not diff_stat:
        return ""

    sections: list[str] = []
    if status:
        sections.append(f"Git status snapshot:\n{status}")
    if diff_stat:
        sections.append(f"Git diff stat:\n{diff_stat}")

    cap = (budget or {}).get("git_context_max_chars", MAX_GIT_CONTEXT_CHARS)
    rendered, _ = _truncate_text("\n\n".join(sections), cap)
    return f"<!-- Project Git Context -->\n{rendered}"


def _parse_memory_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        parsed = yaml.safe_load(parts[1])
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _resolve_memory_updated_at(path: Path, frontmatter: dict[str, Any]) -> datetime | None:
    explicit = _parse_iso_datetime(frontmatter.get("updated_at"))
    if explicit is not None:
        return explicit
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc)


def _is_memory_entry_included(
    path: Path,
    frontmatter: dict[str, Any],
    *,
    now: datetime,
    stale_threshold: timedelta,
) -> bool:
    if bool(frontmatter.get("pinned")):
        return True
    updated_at = _resolve_memory_updated_at(path, frontmatter)
    if updated_at is None:
        return False
    return (now - updated_at) <= stale_threshold


def _format_scoped_memory_entry(relative_path: Path, frontmatter: dict[str, Any]) -> str:
    line = f"- {relative_path.as_posix()}"
    name = frontmatter.get("name")
    if isinstance(name, str) and name.strip():
        line += f" — {name.strip()}"
    description = frontmatter.get("description")
    if isinstance(description, str) and description.strip():
        line += f": {description.strip()}"
    return line


def _build_scoped_memory_listing(
    base_dir: Path,
    *,
    budget: dict[str, int] | None = None,
) -> str:
    memory_root = base_dir / "memory"
    if not memory_root.is_dir():
        return ""

    stale_days = config.get_memory_stale_days()
    stale_threshold = timedelta(days=max(0, stale_days))
    now = datetime.now(timezone.utc)

    lines: list[str] = []
    for scope in _MEMORY_SCOPE_DIRS:
        scope_dir = memory_root / scope
        if not scope_dir.is_dir():
            continue
        for md_file in sorted(scope_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            frontmatter = _parse_memory_frontmatter(content)
            if not _is_memory_entry_included(
                md_file,
                frontmatter,
                now=now,
                stale_threshold=stale_threshold,
            ):
                continue
            try:
                relative = md_file.relative_to(base_dir)
            except ValueError:
                relative = Path("memory") / scope / md_file.name
            lines.append(_format_scoped_memory_entry(relative, frontmatter))

    if not lines:
        return ""

    rendered = "<!-- Scoped Memory (fresh or pinned) -->\n" + "\n".join(lines)
    cap = (budget or {}).get("scoped_memory_block_max_chars", MAX_SCOPED_MEMORY_BLOCK_CHARS)
    rendered, _ = _truncate_text(rendered, cap)
    return rendered


def _build_skills_snapshot_context(
    base_dir: Path,
    *,
    skill_entries: list[dict[str, Any]] | None = None,
    budget: dict[str, int] | None = None,
) -> str:
    from tools.skills_scanner import collect_skill_entries, iter_skill_files, render_skills_snapshot

    component_cap = (budget or {}).get("component_max_chars", MAX_COMPONENT_CHARS)

    if skill_entries is not None:
        return render_skills_snapshot(skill_entries)

    runtime_skill_entries = collect_skill_entries(base_dir, respect_enabled=True)
    if runtime_skill_entries or iter_skill_files(base_dir):
        return render_skills_snapshot(runtime_skill_entries)
    return _read_component(base_dir / "SKILLS_SNAPSHOT.md", max_chars=component_cap)


def _apply_eviction(
    sections: list[tuple[str, str]],
    *,
    total_max_chars: int,
    separator: str = "\n\n",
) -> list[tuple[str, str]]:
    """Drop sections in EVICTION_ORDER until the joined length fits the cap.

    ``sections`` is a list of (section_id, content) tuples in render order. The
    static guidance block (``_tool_result_error_contract``) is never evicted
    because it is not present in EVICTION_ORDER. Returns the surviving
    sections in their original order.
    """
    if total_max_chars <= 0:
        return sections

    def _joined_len(items: list[tuple[str, str]]) -> int:
        if not items:
            return 0
        return sum(len(content) for _, content in items) + len(separator) * (len(items) - 1)

    remaining = list(sections)
    for section_id in EVICTION_ORDER:
        if _joined_len(remaining) <= total_max_chars:
            break
        remaining = [(sid, body) for sid, body in remaining if sid != section_id]

    return remaining


def _assemble_sections(
    base_dir: Path,
    rag_mode: bool,
    *,
    skill_entries: list[dict[str, Any]] | None,
) -> list[tuple[str, str]]:
    """Collect all section ``(id, content)`` pairs in prompt-cache friendly
    order: stable-prefix sections first, volatile per-turn sections last."""
    budget = config.get_prompt_budget()
    component_cap = budget["component_max_chars"]
    memory_index_cap = budget["memory_index_max_chars"]

    sections: list[tuple[str, str]] = []

    # ── Stable prefix ──────────────────────────────────────────────────
    snap = _build_skills_snapshot_context(
        base_dir,
        skill_entries=skill_entries,
        budget=budget,
    )
    if snap:
        sections.append(("skills_snapshot", f"<!-- Skills Snapshot -->\n{snap}"))

    soul = _read_component(base_dir / "workspace" / "SOUL.md", max_chars=component_cap)
    if soul:
        sections.append(("soul", f"<!-- Soul -->\n{soul}"))

    identity = _read_component(base_dir / "workspace" / "IDENTITY.md", max_chars=component_cap)
    if identity:
        sections.append(("identity", f"<!-- Identity -->\n{identity}"))

    user = _read_component(base_dir / "workspace" / "USER.md", max_chars=component_cap)
    if user:
        sections.append(("user_profile", f"<!-- User Profile -->\n{user}"))

    agents = _read_component(base_dir / "workspace" / "AGENTS.md", max_chars=component_cap)
    if agents:
        sections.append(("agents_guide", f"<!-- Agents Guide -->\n{agents}"))

    project_instructions = _build_project_instruction_context(base_dir, budget=budget)
    if project_instructions:
        sections.append(("project_instructions", project_instructions))

    # Static guidance — pinned and stable, so it lives in the cache prefix.
    sections.append(("_tool_result_error_contract", _TOOL_RESULT_ERROR_GUIDANCE))

    if rag_mode:
        sections.append(("_rag_memory_guidance", _RAG_MEMORY_GUIDANCE))

    # ── Volatile suffix (per-turn state) ───────────────────────────────
    if not rag_mode:
        # MEMORY.md is intentionally loaded as a concise curated index rather
        # than durable content. The tight char budget prevents the prompt from
        # silently bloating if someone starts accumulating narrative here —
        # durable facts belong in typed notes under memory/{project,user,agent}/
        # and are surfaced via _build_scoped_memory_listing.
        memory = _read_component(
            base_dir / "memory" / "MEMORY.md",
            max_chars=memory_index_cap,
        )
        if memory:
            sections.append(("memory_index", f"<!-- Long-term Memory -->\n{memory}"))
        scoped_memory = _build_scoped_memory_listing(base_dir, budget=budget)
        if scoped_memory:
            sections.append(("scoped_memory", scoped_memory))

    git_context = _build_git_context(base_dir, budget=budget)
    if git_context:
        sections.append(("git_context", git_context))

    return _apply_eviction(
        sections,
        total_max_chars=budget.get("total_max_chars", 0),
    )


def build_system_prompt_blocks(
    base_dir: Path,
    rag_mode: bool = False,
    *,
    skill_entries: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Assemble the system prompt and return ``(stable_prefix, volatile_suffix)``.

    The stable prefix contains sections that are byte-identical across turns
    given a stable workspace and skill registry (SKILLS_SNAPSHOT,
    workspace/SOUL|IDENTITY|USER|AGENTS.md, ancestor AGENTS.md / CLAW.md, the
    pinned Tool Result Error Contract guidance, and — in RAG mode — the RAG
    memory guidance). The volatile suffix contains per-turn state: the
    long-term memory index, the scoped-memory listing, and the git working-tree
    snapshot. The split matches ``SECTIONS_IN_STABLE_PREFIX``.

    Callers targeting Anthropic can feed ``stable_prefix`` through
    ``build_anthropic_system_blocks`` to attach a ``cache_control`` breakpoint.
    Callers targeting DeepSeek / OpenAI can simply concatenate the two — server
    side prefix caching will match the stable leading bytes automatically.
    """
    sections = _assemble_sections(base_dir, rag_mode, skill_entries=skill_entries)
    stable_parts = [
        content for sid, content in sections if sid in SECTIONS_IN_STABLE_PREFIX
    ]
    volatile_parts = [
        content for sid, content in sections if sid not in SECTIONS_IN_STABLE_PREFIX
    ]
    return "\n\n".join(stable_parts), "\n\n".join(volatile_parts)


def build_system_prompt(
    base_dir: Path,
    rag_mode: bool = False,
    *,
    skill_entries: list[dict[str, Any]] | None = None,
) -> str:
    """
    Assemble the system prompt from the ordered workspace components and any
    additive project context discovered around the workspace root.

    Per-section character budgets come from ``config.get_prompt_budget()``;
    individual sections exceeding their cap are truncated in place with a
    visible marker. When the optional ``total_max_chars`` global cap is set,
    sections are dropped wholesale in the documented EVICTION_ORDER (least
    load-bearing first) so SOUL/IDENTITY/USER/AGENTS survive as long as
    possible. The static Tool Result Error Contract guidance is never evicted.

    Sections are emitted in prompt-cache friendly order: the stable prefix
    first (SKILLS_SNAPSHOT, workspace/*.md, ancestor AGENTS.md / CLAW.md,
    Tool Result Error Contract, RAG memory guidance), followed by the
    volatile suffix (memory index, scoped-memory listing, git context). This
    lets DeepSeek / OpenAI automatic prefix caching match the leading bytes
    across turns; ``build_system_prompt_blocks`` exposes the split explicitly
    for Anthropic ``cache_control`` breakpoints.
    """
    stable_prefix, volatile_suffix = build_system_prompt_blocks(
        base_dir,
        rag_mode,
        skill_entries=skill_entries,
    )
    if stable_prefix and volatile_suffix:
        return f"{stable_prefix}\n\n{volatile_suffix}"
    return stable_prefix or volatile_suffix


def build_anthropic_system_blocks(
    stable_prefix: str,
    volatile_suffix: str,
) -> list[dict[str, Any]]:
    """Render the split prompt as Anthropic system-message content blocks with
    a ``cache_control`` breakpoint at the end of the stable prefix.

    This is a pure helper: it does not import or depend on the Anthropic SDK,
    so the rest of the runtime can remain provider-agnostic. Call sites that
    build a ChatAnthropic model can pass the returned list directly as the
    ``system`` argument; other providers should keep using
    ``build_system_prompt`` and rely on automatic prefix caching.
    """
    blocks: list[dict[str, Any]] = []
    if stable_prefix:
        blocks.append({
            "type": "text",
            "text": stable_prefix,
            "cache_control": {"type": "ephemeral"},
        })
    if volatile_suffix:
        blocks.append({"type": "text", "text": volatile_suffix})
    return blocks
