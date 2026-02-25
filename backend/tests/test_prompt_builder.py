"""
Tests for prompt_builder — assembles system prompt from 6 components.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.prompt_builder import build_system_prompt, MAX_COMPONENT_CHARS


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

    def test_all_files_missing_returns_empty_string(self, tmp_path):
        prompt = build_system_prompt(tmp_path, rag_mode=False)
        assert prompt == ""

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
