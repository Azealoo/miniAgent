"""
Tests for MemoryIndexer.
Index build/retrieve tests that need OpenAI embeddings are skipped unless
the OPENAI_API_KEY env var is set. All other logic (path discovery, hashing,
and empty-state handling) runs without any API calls.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_indexer import MemoryIndexer
from graph.memory_types import (
    TYPED_MEMORY_TYPE_VALUES,
    parse_memory_document,
    validate_memory_write,
)

NEEDS_OPENAI = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set - skipping embedding tests",
)


@pytest.fixture
def indexer(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "storage").mkdir()
    return MemoryIndexer(base_dir=tmp_path)


def _write_memory_file(base_dir: Path, relative_path: str, content: str) -> Path:
    target = base_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestInitialState:
    def test_index_starts_as_none(self, indexer):
        assert indexer._index is None

    def test_nodes_start_empty(self, indexer):
        assert indexer._nodes == []

    def test_last_md5_starts_empty(self, indexer):
        assert indexer._last_md5 == ""

    def test_storage_path_under_storage_dir(self, tmp_path):
        idx = MemoryIndexer(base_dir=tmp_path)
        assert idx._storage_path == tmp_path / "storage" / "memory_index"


class TestMemoryFileDiscovery:
    def test_memory_files_include_nested_markdown_and_text(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(tmp_path, "memory/project/notes.md", "# Project\n")
        _write_memory_file(tmp_path, "memory/user/profile.txt", "Prefers concise notes.\n")

        files = [path.relative_to(tmp_path).as_posix() for path in indexer._memory_files()]

        assert files == [
            "memory/MEMORY.md",
            "memory/project/notes.md",
            "memory/user/profile.txt",
        ]

    def test_memory_files_skip_hidden_and_non_text_files(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(tmp_path, "memory/test-note.md", "Temporary root note.\n")
        _write_memory_file(tmp_path, "memory/project/.gitkeep", "")
        binary_file = tmp_path / "memory" / "user" / "plot.png"
        binary_file.parent.mkdir(parents=True, exist_ok=True)
        binary_file.write_bytes(b"png")

        files = [path.relative_to(tmp_path).as_posix() for path in indexer._memory_files()]

        assert files == ["memory/MEMORY.md"]

    def test_memory_documents_use_relative_source_paths(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/runbook.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: Artifact runbook\n"
                "description: Keeps the artifact storage rule in one scoped note.\n"
                "---\n"
                "Keep outputs under artifacts/.\n"
            ),
        )
        _write_memory_file(tmp_path, "memory/user/empty.md", "")

        assert indexer._memory_documents() == [
            ("memory/MEMORY.md", "# Index"),
            ("memory/project/runbook.md", "Keep outputs under artifacts/."),
        ]

    def test_memory_sections_use_heading_anchors_for_markdown(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/project/runbook.md",
            "# Overview\nUse the miniAgent env.\n\n## QC Checklist\nRun Scanpy QC first.\n",
        )

        assert [(section.source, section.text) for section in indexer._memory_sections()] == [
            ("memory/project/runbook.md#overview", "# Overview\nUse the miniAgent env."),
            (
                "memory/project/runbook.md#qc-checklist",
                "## QC Checklist\nRun Scanpy QC first.",
            ),
        ]

    def test_parsed_memory_documents_capture_typed_frontmatter(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/user/preferences.md",
            (
                "---\n"
                "type: user preference\n"
                "name: Working style\n"
                "description: Stable collaboration preferences for the user.\n"
                "---\n"
                "# Style\nPrefer concise plans.\n"
            ),
        )

        documents = indexer._parsed_memory_documents()

        assert len(documents) == 1
        assert documents[0].metadata is not None
        assert documents[0].metadata.memory_type == "user_preference"
        assert documents[0].metadata.name == "Working style"
        assert documents[0].body == "# Style\nPrefer concise plans."


class TestTypedMemoryContract:
    def test_parse_memory_document_keeps_body_readable_when_type_is_invalid(self):
        parsed = parse_memory_document(
            "memory/project/note.md",
            (
                "---\n"
                "type: unsupported type\n"
                "name: Broken note\n"
                "description: Invalid type should be rejected.\n"
                "---\n"
                "# Body\nStill readable.\n"
            ),
        )

        assert parsed.metadata is None
        assert parsed.errors == (
            "Typed memory frontmatter type must be one of: "
            + ", ".join(TYPED_MEMORY_TYPE_VALUES)
            + ".",
        )
        assert parsed.body == "# Body\nStill readable."

    def test_validate_memory_write_ignores_legacy_memory_files(self):
        assert validate_memory_write("memory/project/legacy.md", "# Legacy note\n") == ()

    def test_validate_memory_write_requires_required_fields_when_frontmatter_is_present(self):
        errors = validate_memory_write(
            "memory/project/incomplete.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: \n"
                "---\n"
                "# Body\nIncomplete note.\n"
            ),
        )

        assert errors == (
            "Typed memory frontmatter requires non-empty fields: name, description.",
        )


class TestMemoryStateMd5:
    def test_md5_missing_files_returns_empty(self, indexer):
        assert indexer._memory_state_md5() == ""

    def test_md5_changes_after_memory_file_edit(self, indexer, tmp_path):
        mem = _write_memory_file(tmp_path, "memory/MEMORY.md", "version 1")
        md5_v1 = indexer._memory_state_md5()
        mem.write_text("version 2", encoding="utf-8")
        md5_v2 = indexer._memory_state_md5()
        assert md5_v1 != md5_v2

    def test_md5_changes_after_nested_file_is_added(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        md5_v1 = indexer._memory_state_md5()
        _write_memory_file(tmp_path, "memory/project/protocol.md", "Use the miniAgent env.\n")
        md5_v2 = indexer._memory_state_md5()
        assert md5_v1 != md5_v2


class TestRebuildIndexEdgeCases:
    def test_rebuild_missing_files_leaves_index_none(self, indexer):
        indexer.rebuild_index()
        assert indexer._index is None
        assert indexer._nodes == []

    def test_rebuild_empty_files_leaves_index_none(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "")
        _write_memory_file(tmp_path, "memory/project/notes.md", "   \n")

        indexer.rebuild_index()

        assert indexer._index is None
        assert indexer._nodes == []

    def test_rebuild_updates_last_md5_for_nested_memory_files(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(tmp_path, "memory/project/notes.md", "Project details.\n")
        expected_md5 = indexer._memory_state_md5()

        try:
            indexer.rebuild_index()
        except Exception:
            pass

        assert indexer._last_md5 == expected_md5


class TestMaybeRebuild:
    def test_no_rebuild_when_md5_unchanged(self, indexer, tmp_path, monkeypatch):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "stable content")
        indexer._last_md5 = indexer._memory_state_md5()

        rebuild_called = []
        monkeypatch.setattr(indexer, "rebuild_index", lambda: rebuild_called.append(1))
        indexer._maybe_rebuild()

        assert rebuild_called == []

    def test_rebuild_when_md5_differs(self, indexer, tmp_path, monkeypatch):
        _write_memory_file(tmp_path, "memory/project/notes.md", "changed content")
        indexer._last_md5 = "stale_md5"

        rebuild_called = []
        monkeypatch.setattr(indexer, "rebuild_index", lambda: rebuild_called.append(1))
        indexer._maybe_rebuild()

        assert rebuild_called == [1]

    def test_initial_empty_md5_triggers_rebuild(self, indexer, tmp_path, monkeypatch):
        _write_memory_file(tmp_path, "memory/user/profile.md", "User likes practical solutions.")

        rebuild_called = []
        monkeypatch.setattr(indexer, "rebuild_index", lambda: rebuild_called.append(1))
        indexer._maybe_rebuild()

        assert rebuild_called == [1]


class TestRetrieve:
    def test_retrieve_no_files_returns_empty(self, indexer):
        results = indexer.retrieve("anything")
        assert results == []

    def test_retrieve_empty_files_returns_empty(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "")
        _write_memory_file(tmp_path, "memory/project/notes.md", " ")

        results = indexer.retrieve("anything")

        assert results == []

    def test_retrieve_uses_lexical_fallback_with_section_sources(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/brca1.md",
            "# Follow Up\nBRCA1 differential expression follow-up lives in artifacts/evidence/.\n",
        )
        _write_memory_file(
            tmp_path,
            "memory/user/preferences.md",
            "# Style\nPrefer practical round-number plans over abstract summaries.\n",
        )

        results = indexer.retrieve("Where is the BRCA1 differential expression follow-up?", top_k=2)

        assert results
        assert results[0]["source"] == "memory/project/brca1.md#follow-up"
        assert "BRCA1 differential expression follow-up" in results[0]["text"]

    def test_retrieve_can_match_typed_memory_metadata(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/buffer-heuristic.md",
            (
                "---\n"
                "type: workflow_heuristic\n"
                "name: Glycine-limited running buffer\n"
                "description: Practical rule for western blot buffer scaling when glycine is limited.\n"
                "---\n"
                "# Heuristic\nPrefer round-number batches that preserve the original ratios.\n"
            ),
        )

        results = indexer.retrieve("What is the glycine running buffer heuristic?", top_k=2)

        assert results
        assert results[0]["source"] == "memory/project/buffer-heuristic.md#heuristic"
        assert results[0]["memory_type"] == "workflow_heuristic"
        assert results[0]["memory_type_label"] == "workflow heuristic"
        assert results[0]["memory_name"] == "Glycine-limited running buffer"
        assert (
            results[0]["memory_description"]
            == "Practical rule for western blot buffer scaling when glycine is limited."
        )

    def test_retrieve_respects_top_k_when_lexical_fallback_matches_many_sections(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        for index in range(5):
            _write_memory_file(
                tmp_path,
                f"memory/project/note-{index}.md",
                f"# Topic {index}\nScanpy topic {index} guidance.\n",
            )

        results = indexer.retrieve("Scanpy guidance", top_k=2)

        assert len(results) == 2

    @NEEDS_OPENAI
    def test_retrieve_with_content_returns_dicts(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/MEMORY.md",
            "User likes Python. User is a software engineer.",
        )

        results = indexer.retrieve("Python")

        assert isinstance(results, list)
        for result in results:
            assert "text" in result
            assert "score" in result
            assert "source" in result

    @NEEDS_OPENAI
    def test_retrieve_can_return_nested_memory_sources(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/analysis.md",
            "The Scanpy QC pipeline lives under backend/tools/.\n",
        )

        results = indexer.retrieve("Scanpy", top_k=2)

        assert any(result["source"] == "memory/project/analysis.md" for result in results)

    @NEEDS_OPENAI
    def test_retrieve_top_k_respected(self, indexer, tmp_path):
        content = "\n".join(
            f"Fact number {index}: something about topic {index}."
            for index in range(20)
        )
        _write_memory_file(tmp_path, "memory/MEMORY.md", content)

        results = indexer.retrieve("topic", top_k=2)

        assert len(results) <= 2
