"""
Tests for prompt_builder — assembles system prompt from 6 components
plus additive project instruction context.
"""
import json
import random
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.prompt_builder import (
    EVICTION_ORDER,
    MAX_COMPONENT_CHARS,
    MAX_MEMORY_INDEX_CHARS,
    MAX_RETRIEVED_MEMORY_BLOCK_CHARS,
    SECTIONS_IN_STABLE_PREFIX,
    _apply_eviction,
    build_anthropic_system_blocks,
    build_retrieved_memory_block,
    build_system_prompt,
    build_system_prompt_blocks,
)
from graph.skill_router import select_skill_entries_for_query


@pytest.fixture
def workspace(tmp_path):
    """Create a minimal workspace mirroring the real structure."""
    (tmp_path / "workspace").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "workspace" / "SOUL.md").write_text("Soul content", encoding="utf-8")
    (tmp_path / "workspace" / "IDENTITY.md").write_text("Identity content", encoding="utf-8")
    (tmp_path / "workspace" / "USER.md").write_text("User content", encoding="utf-8")
    (tmp_path / "workspace" / "AGENTS.md").write_text("Agents content", encoding="utf-8")
    (tmp_path / "memory" / "MEMORY.md").write_text("Memory content", encoding="utf-8")
    (tmp_path / "SKILLS_SNAPSHOT.md").write_text("<available_skills></available_skills>", encoding="utf-8")
    return tmp_path


def _write_skill(
    base_dir: Path,
    name: str,
    description: str = "Prompt builder skill",
    *,
    category: str = "bio/literature",
    tags: str | None = None,
    aliases: str | None = None,
    paths: str | None = None,
    effort: str | None = None,
    modality: str = "literature",
    stage: str = "analysis",
    stability: str = "experimental",
) -> None:
    skill_dir = base_dir / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    tags_line = f"tags: [{tags}]\n" if tags is not None else ""
    aliases_line = f"aliases: [{aliases}]\n" if aliases is not None else ""
    paths_line = f"paths: [{paths}]\n" if paths is not None else ""
    effort_line = f"effort: {effort}\n" if effort is not None else ""
    (skill_dir / "SKILL.md").write_text(
        (
            f"---\nname: {name}\ndescription: {description}\ncategory: {category}\n"
            f"{tags_line}{aliases_line}{paths_line}{effort_line}"
            "requires_tools: [read_file]\nrequires_network: false\nuser_invocable: true\n"
            f"species: any\nmodality: {modality}\nstage: {stage}\n"
            f"stability: {stability}\nsafety_level: low\n"
            "---\n# Body\n"
        ),
        encoding="utf-8",
    )


class TestBuildSystemPrompt:
    def test_normal_mode_contains_all_6_components(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=False)
        assert "Soul content" in prompt
        assert "Identity content" in prompt
        assert "User content" in prompt
        assert "Agents content" in prompt
        assert "Memory content" in prompt
        assert "available_skills" in prompt

    def test_normal_mode_has_all_html_comment_tags(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=False)
        for tag in ["<!-- Skills Snapshot -->", "<!-- Soul -->", "<!-- Identity -->",
                    "<!-- User Profile -->", "<!-- Agents Guide -->", "<!-- Long-term Memory -->"]:
            assert tag in prompt, f"Missing tag: {tag}"

    def test_rag_mode_substitutes_memory_with_guidance(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=True)
        assert "Memory content" not in prompt
        assert "RAG" in prompt or "Retrieval" in prompt
        assert "Do not present retrieved memory as something you verified" in prompt

    def test_rag_mode_still_has_other_5_components(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=True)
        assert "Soul content" in prompt
        assert "Identity content" in prompt
        assert "User content" in prompt
        assert "Agents content" in prompt
        assert "available_skills" in prompt

    def test_components_separated_by_double_newline(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=False)
        assert "\n\n" in prompt

    def test_missing_soul_skipped_gracefully(self, workspace):
        (workspace / "workspace" / "SOUL.md").unlink()
        prompt = build_system_prompt(workspace, rag_mode=False)
        assert "<!-- Soul -->" not in prompt
        assert "Identity content" in prompt  # others still present

    def test_missing_memory_skipped_gracefully(self, workspace):
        (workspace / "memory" / "MEMORY.md").unlink()
        prompt = build_system_prompt(workspace, rag_mode=False)
        assert "Memory content" not in prompt
        assert "Soul content" in prompt

    def test_non_rag_prompt_stays_index_first_and_does_not_inline_scoped_memory(self, workspace):
        (workspace / "memory" / "MEMORY.md").write_text(
            "# Memory Index\n- See memory/project/buffer-heuristic.md\n",
            encoding="utf-8",
        )
        (workspace / "memory" / "project").mkdir()
        (workspace / "memory" / "project" / "buffer-heuristic.md").write_text(
            (
                "---\n"
                "type: workflow_heuristic\n"
                "name: Buffer heuristic\n"
                "description: Scoped typed note.\n"
                "---\n"
                "# Heuristic\nNever inline this whole note into the non-RAG system prompt.\n"
            ),
            encoding="utf-8",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "# Memory Index" in prompt
        assert "memory/project/buffer-heuristic.md" in prompt
        assert "Never inline this whole note" not in prompt

    def test_memory_index_is_truncated_to_tight_budget(self, workspace):
        oversized_index = "# Memory Index\n" + ("- stale narrative line\n" * 500)
        assert len(oversized_index) > MAX_MEMORY_INDEX_CHARS
        (workspace / "memory" / "MEMORY.md").write_text(oversized_index, encoding="utf-8")

        prompt = build_system_prompt(workspace, rag_mode=False)

        _, _, memory_block = prompt.partition("<!-- Long-term Memory -->\n")
        memory_block = memory_block.split("\n\n", 1)[0]
        assert "[truncated]" in memory_block
        assert len(memory_block) <= MAX_MEMORY_INDEX_CHARS + len("\n...[truncated]")

    def test_non_rag_memory_filters_stale_unpinned_scoped_entries(self, workspace):
        project_dir = workspace / "memory" / "project"
        user_dir = workspace / "memory" / "user"
        project_dir.mkdir(parents=True, exist_ok=True)
        user_dir.mkdir(parents=True, exist_ok=True)

        (project_dir / "fresh-entry.md").write_text(
            (
                "---\n"
                "type: project_fact\n"
                "name: Fresh entry\n"
                "description: Fresh scoped note\n"
                "pinned: false\n"
                "updated_at: 2099-01-01T00:00:00Z\n"
                "---\n"
                "# Fresh body\nFresh scoped body text.\n"
            ),
            encoding="utf-8",
        )
        (project_dir / "stale-unpinned.md").write_text(
            (
                "---\n"
                "type: project_fact\n"
                "name: Stale unpinned entry\n"
                "description: Stale unpinned scoped note\n"
                "pinned: false\n"
                "updated_at: 2000-01-01T00:00:00Z\n"
                "---\n"
                "# Stale body\nStale scoped body text.\n"
            ),
            encoding="utf-8",
        )
        (user_dir / "stale-pinned.md").write_text(
            (
                "---\n"
                "type: user_preference\n"
                "name: Stale pinned entry\n"
                "description: Stale but pinned scoped note\n"
                "pinned: true\n"
                "updated_at: 2000-01-01T00:00:00Z\n"
                "---\n"
                "# Stale pinned body\n"
            ),
            encoding="utf-8",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "<!-- Scoped Memory (fresh or pinned) -->" in prompt
        assert "memory/project/fresh-entry.md" in prompt
        assert "memory/user/stale-pinned.md" in prompt
        assert "memory/project/stale-unpinned.md" not in prompt
        # Body content is never inlined, even for fresh/pinned entries.
        assert "Fresh scoped body text" not in prompt
        assert "Stale scoped body text" not in prompt

    def test_all_files_missing_returns_only_static_guidance(self, tmp_path):
        prompt = build_system_prompt(tmp_path, rag_mode=False)
        # Workspace components and memory are absent; the only remaining block is
        # the static Tool Result Error contract guidance that the wrapper relies on.
        assert "<!-- Soul -->" not in prompt
        assert "<!-- Identity -->" not in prompt
        assert "<!-- Long-term Memory -->" not in prompt
        assert "<!-- Tool Result Error Contract -->" in prompt
        assert "execution_failure" in prompt

    def test_component_truncated_at_20k_chars(self, workspace):
        oversized = "A" * (MAX_COMPONENT_CHARS + 5000)
        (workspace / "workspace" / "SOUL.md").write_text(oversized, encoding="utf-8")
        prompt = build_system_prompt(workspace, rag_mode=False)
        # Truncated soul should appear but not the full text
        assert "[truncated]" in prompt
        # The full oversized text is not in the prompt
        assert "A" * (MAX_COMPONENT_CHARS + 1) not in prompt

    def test_skills_snapshot_comes_first(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=False)
        snap_pos = prompt.find("available_skills")
        soul_pos = prompt.find("Soul content")
        assert snap_pos < soul_pos

    def test_memory_comes_last_in_normal_mode(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=False)
        agents_pos = prompt.rfind("Agents content")
        memory_pos = prompt.find("Memory content")
        assert memory_pos > agents_pos

    def test_project_agents_file_is_included_as_additive_context(self, workspace):
        (workspace / "AGENTS.md").write_text(
            "Repo-level instructions\n- prefer provenance\n",
            encoding="utf-8",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "<!-- Project Instructions: AGENTS.md -->" in prompt
        assert "Repo-level instructions" in prompt

    def test_project_instruction_references_are_loaded_with_budgeting(self, workspace):
        (workspace / "AGENTS.md").write_text(
            "Repo instructions\n- @context/project-overview.md\n",
            encoding="utf-8",
        )
        (workspace / "context").mkdir()
        (workspace / "context" / "project-overview.md").write_text(
            "Project overview from referenced context file.",
            encoding="utf-8",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "<!-- Project Context File: context/project-overview.md -->" in prompt
        assert "Project overview from referenced context file." in prompt

    def test_git_context_is_optional_and_env_gated(self, workspace, monkeypatch):
        subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"],
            cwd=workspace,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Prompt Builder Tests"],
            cwd=workspace,
            check=True,
        )
        (workspace / "tracked.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--quiet"],
            cwd=workspace,
            check=True,
        )
        (workspace / "tracked.txt").write_text("hello\nworld\n", encoding="utf-8")
        monkeypatch.setenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "1")

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "<!-- Project Git Context -->" in prompt
        assert "Git status snapshot:" in prompt

    def test_git_context_can_be_enabled_via_runtime_config(self, workspace, monkeypatch):
        subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "config", "user.email", "tests@example.com"],
            cwd=workspace,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Prompt Builder Tests"],
            cwd=workspace,
            check=True,
        )
        (workspace / "tracked.txt").write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "--quiet"],
            cwd=workspace,
            check=True,
        )
        (workspace / "tracked.txt").write_text("hello\nworld\n", encoding="utf-8")
        monkeypatch.delenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", raising=False)
        cfg_file = workspace / "backend-config.json"
        cfg_file.write_text(
            json.dumps({"prompt_context": {"include_git_context": True}}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            prompt = build_system_prompt(workspace, rag_mode=False)

        assert "<!-- Project Git Context -->" in prompt
        assert "Git diff stat:" in prompt

    def test_runtime_registry_replaces_stale_skills_snapshot(self, workspace):
        _write_skill(workspace, "fresh_skill", "Fresh runtime skill")
        (workspace / "SKILLS_SNAPSHOT.md").write_text(
            "<available_skills><skill><name>stale_skill</name></skill></available_skills>",
            encoding="utf-8",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "fresh_skill" in prompt
        assert "stale_skill" not in prompt

    def test_runtime_registry_populates_prompt_without_snapshot_file(self, workspace):
        _write_skill(workspace, "registry_skill", "Registry-backed skill")
        (workspace / "SKILLS_SNAPSHOT.md").unlink()

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "registry_skill" in prompt
        assert "available_skills" in prompt

    def test_snapshot_compatibility_artifact_is_used_when_no_runtime_skills_exist(self, workspace):
        (workspace / "SKILLS_SNAPSHOT.md").write_text(
            "<available_skills><skill><name>compat_skill</name></skill></available_skills>",
            encoding="utf-8",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "compat_skill" in prompt
        assert "available_skills" in prompt

    def test_runtime_registry_snapshot_includes_paths_and_effort_hints(self, workspace):
        _write_skill(
            workspace,
            "path_scoped_skill",
            "Registry-backed path-aware skill",
            category="bio/compute",
            paths="backend/runtime/**, memory/project/**",
            effort="medium",
            modality="compute",
            stage="utilities",
        )

        prompt = build_system_prompt(workspace, rag_mode=False)

        assert "<paths>backend/runtime/**, memory/project/**</paths>" in prompt
        assert "<effort>medium</effort>" in prompt

    def test_build_system_prompt_can_use_routed_skill_subset(self, workspace):
        selected_entries = [
            {
                "name": "paper_triage",
                "description": "Classify relevance of a paper.",
                "location": "./skills/paper_triage/SKILL.md",
                "category": "bio/literature",
                "stage": "interpretation",
                "paths": ["backend/runtime/**", "memory/project/**"],
                "effort": "high",
                "species": "any",
                "modality": "literature",
                "aliases": ["literature_triage"],
                "tags": ["paper", "abstract"],
                "requires_tools": ["read_file"],
                "requires_network": False,
                "stability": "experimental",
                "safety_level": "low",
                "user_invocable": True,
            }
        ]

        prompt = build_system_prompt(
            workspace,
            rag_mode=False,
            skill_entries=selected_entries,
        )

        assert "paper_triage" in prompt
        assert "literature_triage" in prompt
        assert "<paths>backend/runtime/**, memory/project/**</paths>" in prompt
        assert "<effort>high</effort>" in prompt
        assert "available_skills" in prompt
        assert "stale_skill" not in prompt


class TestSkillRouting:
    def test_skill_router_prefers_domain_specific_matches(self, workspace):
        _write_skill(
            workspace,
            "perturbseq_coverage_estimator",
            "Estimate the cell budget for a Perturb-seq design.",
            category="bio/perturb_seq",
            tags="perturb-seq, coverage, design",
            aliases="perturbation_coverage_planner",
            modality="perturb_seq",
            stage="design",
            stability="stable",
        )
        _write_skill(
            workspace,
            "dilution_calculator",
            "Calculate wet-lab dilutions.",
            category="bio/molecular_lab",
            tags="dilution, wet-lab",
            aliases="serial_dilution_planner",
            modality="wet_lab",
            stage="utilities",
            stability="stable",
        )
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            tags="paper, abstract, literature",
            aliases="literature_triage",
            modality="literature",
            stage="interpretation",
        )

        selected = select_skill_entries_for_query(
            workspace,
            "Estimate coverage for a perturb-seq pilot screen",
        )

        assert selected is not None
        assert selected[0]["name"] == "perturbseq_coverage_estimator"
        assert "dilution_calculator" not in {entry["name"] for entry in selected}

    def test_skill_router_preserves_explicit_skill_name_invocation(self, workspace):
        _write_skill(
            workspace,
            "scRNA_qc_checklist",
            "Produce a QC report for single-cell data.",
            category="bio/single_cell_rna",
            aliases="single_cell_qc_helper",
            modality="single_cell_rna",
            stage="qc",
        )
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            modality="literature",
            stage="interpretation",
        )
        _write_skill(
            workspace,
            "runtime_debugger",
            "Inspect backend runtime paths.",
            category="bio/compute",
            paths="backend/runtime/**",
            modality="compute",
            stage="utilities",
        )

        selected = select_skill_entries_for_query(
            workspace,
            "Use scRNA_qc_checklist on backend/runtime/query_engine.py and suggest thresholds",
        )

        assert selected is not None
        assert [entry["name"] for entry in selected] == ["scRNA_qc_checklist"]

    def test_skill_router_activates_path_scoped_skill_from_current_message_path(self, workspace):
        _write_skill(
            workspace,
            "runtime_debugger",
            "Inspect backend runtime paths.",
            category="bio/compute",
            paths="backend/runtime/**",
            modality="compute",
            stage="utilities",
        )
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            modality="literature",
            stage="interpretation",
        )

        selected = select_skill_entries_for_query(
            workspace,
            "Please inspect backend/runtime/query_engine.py for this failure",
        )

        assert selected is not None
        assert selected[0]["name"] == "runtime_debugger"

    def test_skill_router_activates_path_scoped_skill_from_recent_history_paths(self, workspace):
        _write_skill(
            workspace,
            "memory_curator",
            "Update project memory notes.",
            category="bio/compute",
            paths="memory/project/**",
            modality="compute",
            stage="utilities",
        )
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            modality="literature",
            stage="interpretation",
        )

        history = [
            {
                "role": "assistant",
                "content": "Loaded the note.",
                "blocks": [
                    {
                        "type": "tool_result",
                        "tool": "read_file",
                        "output": "# BRCA1 notes",
                        "result": {
                            "structured_payload": {
                                "path": "memory/project/brca1.md",
                            },
                            "metadata": {
                                "requested_path": "memory/project/brca1.md",
                            },
                            "artifact_refs": [
                                {
                                    "path": "/tmp/ignored-artifact.json",
                                    "label": "artifact",
                                }
                            ],
                        },
                    }
                ],
            }
        ]

        selected = select_skill_entries_for_query(
            workspace,
            "Please update the note you just opened.",
            history=history,
        )

        assert selected is not None
        assert selected[0]["name"] == "memory_curator"

    def test_skill_router_gates_out_path_scoped_skill_when_no_path_matches(self, workspace):
        _write_skill(
            workspace,
            "runtime_debugger",
            "Inspect backend runtime paths.",
            category="bio/compute",
            tags="runtime, debugger",
            paths="backend/runtime/**",
            modality="compute",
            stage="utilities",
        )
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            tags="paper, abstract, literature",
            modality="literature",
            stage="interpretation",
        )

        selected = select_skill_entries_for_query(
            workspace,
            "triage this paper abstract about runtime scheduling",
        )

        assert selected is not None
        names = {entry["name"] for entry in selected}
        assert "runtime_debugger" not in names
        assert "paper_triage" in names

    def test_skill_router_keeps_skill_without_paths_as_always_on(self, workspace):
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            tags="paper, abstract, literature",
            modality="literature",
            stage="interpretation",
        )

        selected = select_skill_entries_for_query(
            workspace,
            "triage this paper abstract",
        )

        assert selected is not None
        assert [entry["name"] for entry in selected] == ["paper_triage"]

    def test_skill_router_allows_explicit_invocation_to_bypass_path_gate(self, workspace):
        _write_skill(
            workspace,
            "runtime_debugger",
            "Inspect backend runtime paths.",
            category="bio/compute",
            paths="backend/runtime/**",
            modality="compute",
            stage="utilities",
        )

        selected = select_skill_entries_for_query(
            workspace,
            "use runtime_debugger to brainstorm checks",
        )

        assert selected is not None
        assert [entry["name"] for entry in selected] == ["runtime_debugger"]

    def test_skill_router_drops_skill_with_missing_required_env(
        self, workspace, monkeypatch
    ):
        skill_dir = workspace / "skills" / "needs_token_skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            (
                "---\nname: needs_token_skill\n"
                "description: Requires an env token to operate\n"
                "category: bio/compute\n"
                "tags: [paper, abstract]\n"
                "requires_tools: [read_file]\nrequires_network: false\n"
                "user_invocable: true\n"
                "species: any\nmodality: compute\nstage: utilities\n"
                "stability: experimental\nsafety_level: low\n"
                "required_env: [BIOAPEX_NEEDS_THIS]\n"
                "---\n# Body\n"
            ),
            encoding="utf-8",
        )
        _write_skill(
            workspace,
            "paper_triage",
            "Classify relevance of a paper abstract.",
            category="bio/literature",
            tags="paper, abstract, literature",
            modality="literature",
            stage="interpretation",
        )

        monkeypatch.delenv("BIOAPEX_NEEDS_THIS", raising=False)

        selected = select_skill_entries_for_query(
            workspace,
            "triage this paper abstract",
        )
        assert selected is not None
        names = {entry["name"] for entry in selected}
        assert "needs_token_skill" not in names
        assert "paper_triage" in names

        monkeypatch.setenv("BIOAPEX_NEEDS_THIS", "1")
        selected_with_env = select_skill_entries_for_query(
            workspace,
            "triage this paper abstract",
        )
        assert selected_with_env is not None
        names_with_env = {entry["name"] for entry in selected_with_env}
        # With the env set, the skill is eligible; whether it scores is
        # query-dependent — we only assert it's no longer filtered out a
        # priori. Explicit invocation by name proves the gate is off.
        explicit = select_skill_entries_for_query(
            workspace,
            "use needs_token_skill to help",
        )
        assert explicit is not None
        assert "needs_token_skill" in {entry["name"] for entry in explicit}
        del names_with_env  # silence unused warning on CI linters


class TestRetrievedMemoryBlock:
    def test_retrieved_memory_block_includes_typed_metadata_compactly(self):
        block = build_retrieved_memory_block(
            [
                {
                    "source": "memory/project/buffer-heuristic.md#heuristic",
                    "text": "Prefer round-number batches that preserve the original ratios.",
                    "memory_type": "workflow_heuristic",
                    "memory_type_label": "workflow heuristic",
                    "memory_name": "Glycine-limited running buffer",
                }
            ]
        )

        assert "[workflow heuristic]" in block
        assert "Glycine-limited running buffer" in block
        assert "memory/project/buffer-heuristic.md#heuristic" in block

    def test_retrieved_memory_block_includes_source_paths_and_text(self):
        block = build_retrieved_memory_block(
            [
                {
                    "source": "memory/project/brca1.md#follow-up",
                    "text": "BRCA1 differential expression follow-up lives in artifacts/evidence/.",
                },
                {
                    "source": "memory/user/preferences.md#style",
                    "text": "Prefer practical round-number plans over abstract summaries.",
                },
            ]
        )

        assert block.startswith(
            "[Retrieved Memory - background context only; not verified current project state]"
        )
        assert "memory/project/brca1.md#follow-up" in block
        assert "Prefer practical round-number plans" in block

    def test_retrieved_memory_block_is_bounded(self):
        block = build_retrieved_memory_block(
            [
                {
                    "source": "memory/project/long.md#section",
                    "text": "A" * (MAX_RETRIEVED_MEMORY_BLOCK_CHARS * 2),
                }
            ]
        )

        assert len(block) <= MAX_RETRIEVED_MEMORY_BLOCK_CHARS + len(
            "\n...[retrieved memory truncated]"
        )
        assert "[retrieved memory truncated]" in block or len(block) <= MAX_RETRIEVED_MEMORY_BLOCK_CHARS


# ── G2 property tests: prompt budget + eviction policy ────────────────────
# Parameterized fuzz inputs (no `hypothesis` dependency — see backend/requirements.txt).
# Each case seeds the workspace with oversized content for one or more
# sections and asserts the budget invariants hold under the configured caps.


def _populated_workspace(tmp_path: Path, *, oversize_factor: int) -> Path:
    """Build a workspace where every section has content ``oversize_factor``
    times the relevant cap, so per-section truncation always bites."""
    (tmp_path / "workspace").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "project").mkdir()

    big_component = "S" * (MAX_COMPONENT_CHARS * max(1, oversize_factor))
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "AGENTS.md"):
        (tmp_path / "workspace" / name).write_text(big_component, encoding="utf-8")

    (tmp_path / "memory" / "MEMORY.md").write_text(
        "# Memory Index\n" + ("- a stale narrative line\n" * 500),
        encoding="utf-8",
    )
    (tmp_path / "memory" / "project" / "fresh-entry.md").write_text(
        (
            "---\n"
            "type: project_fact\n"
            "name: Fresh entry\n"
            "description: " + ("padding " * 200) + "\n"
            "pinned: true\n"
            "updated_at: 2099-01-01T00:00:00Z\n"
            "---\nbody\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "Repo instructions\n" + ("- bullet line\n" * 1000),
        encoding="utf-8",
    )
    (tmp_path / "SKILLS_SNAPSHOT.md").write_text(
        "<available_skills>" + ("<skill><name>x</name></skill>" * 200) + "</available_skills>",
        encoding="utf-8",
    )
    return tmp_path


def _project_config(tmp_path: Path, prompt_budget: dict) -> Path:
    cfg = tmp_path / "backend-config.json"
    cfg.write_text(json.dumps({"prompt_budget": prompt_budget}), encoding="utf-8")
    return cfg


@pytest.mark.parametrize("seed", list(range(8)))
def test_property_each_section_respects_its_configured_cap(tmp_path, seed):
    """Per-section caps are honored across randomized cap configurations."""
    rng = random.Random(seed)
    workspace = _populated_workspace(tmp_path, oversize_factor=2)
    budget = {
        "component_max_chars": rng.randint(200, 5_000),
        "project_instruction_file_max_chars": rng.randint(100, 1_500),
        "project_instruction_total_max_chars": rng.randint(500, 6_000),
        "git_context_max_chars": rng.randint(100, 1_500),
        "retrieved_memory_block_max_chars": rng.randint(200, 1_200),
        "retrieved_memory_item_max_chars": rng.randint(40, 200),
        "scoped_memory_block_max_chars": rng.randint(200, 3_000),
        "memory_index_max_chars": rng.randint(200, 1_500),
        "total_max_chars": 0,
    }

    cfg = _project_config(tmp_path, budget)
    with patch("config._CONFIG_FILE", cfg):
        prompt = build_system_prompt(workspace, rag_mode=False)

    truncate_marker = len("\n...[truncated]")

    def _section_body(tag: str) -> str:
        if tag not in prompt:
            return ""
        body = prompt.split(tag, 1)[1]
        return body.split("\n\n", 1)[0]

    for tag, cap_field in [
        ("<!-- Soul -->\n", "component_max_chars"),
        ("<!-- Identity -->\n", "component_max_chars"),
        ("<!-- User Profile -->\n", "component_max_chars"),
        ("<!-- Agents Guide -->\n", "component_max_chars"),
        ("<!-- Long-term Memory -->\n", "memory_index_max_chars"),
    ]:
        body = _section_body(tag)
        assert len(body) <= budget[cap_field] + truncate_marker, (
            f"section {tag!r} exceeded cap {budget[cap_field]} (len={len(body)})"
        )


@pytest.mark.parametrize("seed", list(range(6)))
def test_property_total_prompt_under_sum_of_section_budgets(tmp_path, seed):
    """The total assembled prompt fits under the sum of per-section budgets
    (excluding the static guidance block, which is pinned)."""
    rng = random.Random(seed)
    workspace = _populated_workspace(tmp_path, oversize_factor=3)
    budget = {
        "component_max_chars": rng.randint(500, 4_000),
        "project_instruction_file_max_chars": rng.randint(200, 1_500),
        "project_instruction_total_max_chars": rng.randint(800, 6_000),
        "git_context_max_chars": rng.randint(200, 1_200),
        "retrieved_memory_block_max_chars": rng.randint(200, 1_500),
        "retrieved_memory_item_max_chars": rng.randint(60, 200),
        "scoped_memory_block_max_chars": rng.randint(300, 2_500),
        "memory_index_max_chars": rng.randint(200, 1_500),
        "total_max_chars": 0,
    }

    cfg = _project_config(tmp_path, budget)
    with patch("config._CONFIG_FILE", cfg):
        prompt = build_system_prompt(workspace, rag_mode=False)

    # Sum of evictable per-section caps (4 workspace components +
    # project_instructions total + memory_index + scoped_memory).
    sum_caps = (
        4 * budget["component_max_chars"]
        + budget["project_instruction_total_max_chars"]
        + budget["memory_index_max_chars"]
        + budget["scoped_memory_block_max_chars"]
    )
    # The static Tool Result Error Contract guidance is always present and
    # never evicted; account for it explicitly so the bound is meaningful.
    static_guidance_len = len(
        "<!-- Tool Result Error Contract -->\n"
    ) + 4_000  # generous upper bound for the guidance text.
    truncation_slack = 200  # accommodates per-section truncate markers.

    assert len(prompt) <= sum_caps + static_guidance_len + truncation_slack


def test_property_total_max_chars_evicts_lowest_priority_first(workspace, monkeypatch):
    """When total_max_chars is binding, sections drop in EVICTION_ORDER —
    SOUL/IDENTITY/USER/AGENTS survive lower-priority sections."""
    # Add a memory index and scoped memory entries that would otherwise be
    # included in the prompt under the current defaults.
    (workspace / "memory" / "MEMORY.md").write_text(
        "# Memory Index\nlong narrative line " * 50, encoding="utf-8"
    )
    (workspace / "memory" / "project").mkdir(exist_ok=True)
    (workspace / "memory" / "project" / "fresh-entry.md").write_text(
        (
            "---\n"
            "type: project_fact\n"
            "name: Fresh entry\n"
            "description: scoped note\n"
            "pinned: true\n"
            "updated_at: 2099-01-01T00:00:00Z\n"
            "---\nbody\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "0")

    # Set a tight total cap that forces eviction. The SOUL/IDENTITY/USER/AGENTS
    # blocks combined are well under 1 KiB in this fixture, so a 2 KiB cap
    # leaves room for them but forces lower-priority sections out.
    budget = {
        "component_max_chars": 20_000,
        "project_instruction_file_max_chars": 2_000,
        "project_instruction_total_max_chars": 8_000,
        "git_context_max_chars": 2_000,
        "retrieved_memory_block_max_chars": 1_600,
        "retrieved_memory_item_max_chars": 280,
        "scoped_memory_block_max_chars": 4_000,
        "memory_index_max_chars": 2_048,
        "total_max_chars": 2_000,
    }
    cfg = workspace / "backend-config.json"
    cfg.write_text(json.dumps({"prompt_budget": budget}), encoding="utf-8")

    with patch("config._CONFIG_FILE", cfg):
        prompt = build_system_prompt(workspace, rag_mode=False)

    # High-priority workspace blocks survive.
    assert "<!-- Soul -->" in prompt
    assert "<!-- Identity -->" in prompt
    assert "<!-- User Profile -->" in prompt
    assert "<!-- Agents Guide -->" in prompt
    # Lowest-priority sections are dropped first.
    assert "<!-- Long-term Memory -->" not in prompt
    assert "<!-- Scoped Memory" not in prompt
    # The pinned static guidance block always remains.
    assert "<!-- Tool Result Error Contract -->" in prompt


def test_property_truncation_marker_present_when_per_section_cap_bites(workspace):
    """Each truncation path emits a visible marker so the prompt isn't
    silently snipped."""
    big = "Z" * (MAX_COMPONENT_CHARS + 1_000)
    (workspace / "workspace" / "IDENTITY.md").write_text(big, encoding="utf-8")
    oversized_index = "# Memory Index\n" + ("- stale narrative line\n" * 500)
    (workspace / "memory" / "MEMORY.md").write_text(oversized_index, encoding="utf-8")

    prompt = build_system_prompt(workspace, rag_mode=False)
    identity_body = prompt.split("<!-- Identity -->\n", 1)[1].split("\n\n", 1)[0]
    memory_body = prompt.split("<!-- Long-term Memory -->\n", 1)[1].split("\n\n", 1)[0]

    assert "[truncated]" in identity_body
    assert "[truncated]" in memory_body


def test_eviction_order_constant_keeps_protected_sections_last():
    """SOUL/IDENTITY/USER/AGENTS must sit at the tail of EVICTION_ORDER so they
    are dropped only after lower-priority context has already been evicted."""
    protected = ("user_profile", "agents_guide", "identity", "soul")
    for section in protected:
        assert section in EVICTION_ORDER
    tail = EVICTION_ORDER[-len(protected):]
    assert set(tail) == set(protected)


def test_apply_eviction_drops_in_documented_order():
    """``_apply_eviction`` removes sections strictly in EVICTION_ORDER until
    the cap is met, regardless of insertion order."""
    sections = [
        ("skills_snapshot", "S" * 100),
        ("soul", "X" * 100),
        ("identity", "X" * 100),
        ("user_profile", "X" * 100),
        ("agents_guide", "X" * 100),
        ("project_instructions", "P" * 100),
        ("git_context", "G" * 100),
        ("_tool_result_error_contract", "T" * 50),
        ("memory_index", "M" * 100),
        ("scoped_memory", "C" * 100),
    ]

    # Cap big enough to keep most workspace blocks but small enough to evict
    # git_context, retrieved_memory, scoped_memory, memory_index.
    survived = _apply_eviction(sections, total_max_chars=600)
    survived_ids = [sid for sid, _ in survived]

    assert "git_context" not in survived_ids
    assert "scoped_memory" not in survived_ids
    assert "memory_index" not in survived_ids
    # Pinned static guidance survives even though it has no priority slot.
    assert "_tool_result_error_contract" in survived_ids
    # SOUL/IDENTITY/USER/AGENTS still present.
    for sid in ("soul", "identity", "user_profile", "agents_guide"):
        assert sid in survived_ids


def test_apply_eviction_disabled_when_total_zero():
    sections = [
        ("git_context", "G" * 5000),
        ("soul", "S" * 5000),
    ]
    survived = _apply_eviction(sections, total_max_chars=0)
    assert survived == sections


# ── Prompt-cache prefix stability tests (issue #66) ─────────────────────
# The stable prefix (SKILLS_SNAPSHOT, workspace/*.md, ancestor AGENTS.md /
# CLAW.md, pinned tool-result contract, RAG memory guidance) must stay
# byte-identical across turns with varying per-turn state (git status,
# memory index, scoped-memory listing). Otherwise provider-side prompt
# caching (DeepSeek / OpenAI automatic prefix caching, Anthropic cache_control)
# cannot reuse the KV cache across consecutive turns.


def _init_git_repo(workspace: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Prompt Builder Tests"],
        cwd=workspace,
        check=True,
    )
    # Disable commit signing for the test repo — some sandboxed environments
    # configure a global signing hook that fails on throwaway repos.
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "tag.gpgsign", "false"],
        cwd=workspace,
        check=True,
    )
    (workspace / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=workspace, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", "init", "--quiet"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            "git commit unavailable in this environment (possibly signing-gated); "
            f"stderr={result.stderr.strip()!r}"
        )


class TestPromptCachePrefix:
    def test_stable_prefix_contains_all_cache_eligible_sections(self, workspace):
        stable, volatile = build_system_prompt_blocks(workspace, rag_mode=False)
        # The cache-eligible tags land in the stable prefix.
        for tag in [
            "<!-- Skills Snapshot -->",
            "<!-- Soul -->",
            "<!-- Identity -->",
            "<!-- User Profile -->",
            "<!-- Agents Guide -->",
            "<!-- Tool Result Error Contract -->",
        ]:
            assert tag in stable, f"{tag} missing from stable prefix"
            assert tag not in volatile, f"{tag} leaked into volatile suffix"
        # And the volatile per-turn sections land in the suffix (not the prefix).
        assert "<!-- Long-term Memory -->" in volatile
        assert "<!-- Long-term Memory -->" not in stable

    def test_rag_mode_keeps_memory_guidance_in_stable_prefix(self, workspace):
        stable, volatile = build_system_prompt_blocks(workspace, rag_mode=True)
        # The RAG memory guidance is a static string — it belongs in the prefix.
        assert "Long-term Memory" in stable
        assert "RAG" in stable or "Retrieval" in stable
        # No volatile memory index in RAG mode (it's substituted by guidance).
        assert volatile == ""

    def test_stable_prefix_comes_before_volatile_suffix_in_concat(self, workspace):
        prompt = build_system_prompt(workspace, rag_mode=False)
        # Every stable-prefix marker appears before the first volatile marker.
        memory_pos = prompt.find("<!-- Long-term Memory -->")
        assert memory_pos > 0
        for tag in [
            "<!-- Skills Snapshot -->",
            "<!-- Soul -->",
            "<!-- Identity -->",
            "<!-- User Profile -->",
            "<!-- Agents Guide -->",
            "<!-- Tool Result Error Contract -->",
        ]:
            assert 0 <= prompt.find(tag) < memory_pos, (
                f"stable section {tag!r} must precede volatile memory section"
            )

    def test_stable_prefix_is_byte_identical_across_10_turns_with_volatile_churn(
        self,
        workspace,
        monkeypatch,
    ):
        """Simulate 10 turns with per-turn volatile state (git status + memory
        index + scoped memory churn) and assert the stable prefix is
        byte-identical every turn."""
        _init_git_repo(workspace)
        monkeypatch.setenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "1")

        # Pre-create scoped memory dirs so stale entries can be swapped in.
        (workspace / "memory" / "project").mkdir(parents=True, exist_ok=True)

        stable_prefixes: list[str] = []
        for turn in range(10):
            # Mutate per-turn volatile state only: git working tree, memory
            # index content, and a scoped-memory entry.
            (workspace / "tracked.txt").write_text(
                f"turn-{turn} dirty state\n",
                encoding="utf-8",
            )
            (workspace / "memory" / "MEMORY.md").write_text(
                f"# Memory Index\n- turn {turn} pointer line\n",
                encoding="utf-8",
            )
            (workspace / "memory" / "project" / "note.md").write_text(
                (
                    "---\n"
                    "type: project_fact\n"
                    f"name: Turn {turn} note\n"
                    "description: Scoped note that changes per-turn.\n"
                    "pinned: true\n"
                    "updated_at: 2099-01-01T00:00:00Z\n"
                    "---\nbody\n"
                ),
                encoding="utf-8",
            )

            stable, volatile = build_system_prompt_blocks(workspace, rag_mode=False)
            stable_prefixes.append(stable)
            # Volatile churn must actually reach the volatile suffix on every
            # turn so we know we're testing the right thing.
            assert f"turn {turn} pointer line" in volatile
            assert f"Turn {turn} note" in volatile

        # All 10 stable prefixes are byte-identical → provider-side prefix
        # caching can reuse the attention KV for every turn after the first.
        unique_prefixes = set(stable_prefixes)
        assert len(unique_prefixes) == 1, (
            "stable prefix drifted across turns: "
            f"{len(unique_prefixes)} distinct variants observed"
        )

    def test_stable_prefix_captures_at_least_80_percent_of_prompt_mass(
        self,
        workspace,
        monkeypatch,
    ):
        """Across a 10-turn fixture, the stable prefix must carry ≥ 80 % of
        the average total prompt length. This is the hit-rate demonstration
        asked for in issue #66: once the first turn has warmed the cache,
        every subsequent turn's input gets ≥ 80 % cache-read tokens.
        """
        _init_git_repo(workspace)
        monkeypatch.setenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "1")
        (workspace / "memory" / "project").mkdir(parents=True, exist_ok=True)

        ratios: list[float] = []
        for turn in range(10):
            (workspace / "tracked.txt").write_text(
                f"turn-{turn} dirty\n", encoding="utf-8"
            )
            (workspace / "memory" / "MEMORY.md").write_text(
                f"# Memory Index\n- turn {turn} pointer\n",
                encoding="utf-8",
            )
            stable, volatile = build_system_prompt_blocks(workspace, rag_mode=False)
            total = len(stable) + len(volatile)
            assert total > 0
            ratios.append(len(stable) / total)

        avg_ratio = sum(ratios) / len(ratios)
        assert avg_ratio >= 0.80, (
            f"stable prefix covers {avg_ratio:.1%} of prompt mass; "
            "cache hit-rate target is ≥ 80%"
        )

    def test_sections_in_stable_prefix_matches_documented_membership(self):
        # The cache-prefix membership set is the contract the runtime relies
        # on to attach Anthropic ``cache_control`` breakpoints. Guard it so
        # reshuffling sections requires an intentional update here.
        assert SECTIONS_IN_STABLE_PREFIX == frozenset({
            "skills_snapshot",
            "soul",
            "identity",
            "user_profile",
            "agents_guide",
            "project_instructions",
            "_tool_result_error_contract",
            "_rag_memory_guidance",
        })


class TestAnthropicSystemBlocks:
    def test_emits_cache_control_breakpoint_on_stable_prefix_only(self):
        blocks = build_anthropic_system_blocks("STABLE", "VOLATILE")
        assert blocks == [
            {"type": "text", "text": "STABLE", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "VOLATILE"},
        ]

    def test_skips_volatile_block_when_empty(self):
        blocks = build_anthropic_system_blocks("STABLE", "")
        assert blocks == [
            {"type": "text", "text": "STABLE", "cache_control": {"type": "ephemeral"}},
        ]

    def test_skips_stable_block_when_empty(self):
        # A degenerate prompt with no stable prefix should not emit a
        # cache_control breakpoint — Anthropic would reject an empty block.
        blocks = build_anthropic_system_blocks("", "VOLATILE")
        assert blocks == [{"type": "text", "text": "VOLATILE"}]

    def test_returns_empty_list_when_both_parts_empty(self):
        assert build_anthropic_system_blocks("", "") == []
