"""
Tests for prompt_builder — assembles system prompt from 6 components
plus additive project instruction context.
"""
import json
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.prompt_builder import (
    MAX_COMPONENT_CHARS,
    MAX_MEMORY_INDEX_CHARS,
    MAX_RETRIEVED_MEMORY_BLOCK_CHARS,
    build_retrieved_memory_block,
    build_system_prompt,
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
