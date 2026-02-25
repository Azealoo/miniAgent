"""
Tests for MemoryIndexer.
Index build/retrieve tests that need OpenAI embeddings are skipped unless
the OPENAI_API_KEY env var is set. All other logic (MD5, paths, edge cases)
runs without any API calls.
"""
import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_indexer import MemoryIndexer

NEEDS_OPENAI = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping embedding tests",
)


@pytest.fixture
def indexer(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "storage").mkdir()
    return MemoryIndexer(base_dir=tmp_path)


# ──────────────────────────────────────────────────────────────────────────────
# Initialisation state
# ──────────────────────────────────────────────────────────────────────────────

class TestInitialState:
    def test_index_starts_as_none(self, indexer):
        assert indexer._index is None

    def test_nodes_starts_empty(self, indexer):
        assert indexer._nodes == []

    def test_last_md5_starts_empty(self, indexer):
        assert indexer._last_md5 == ""

    def test_storage_path_under_storage_dir(self, tmp_path):
        idx = MemoryIndexer(base_dir=tmp_path)
        assert idx._storage_path == tmp_path / "storage" / "memory_index"


# ──────────────────────────────────────────────────────────────────────────────
# MD5 helper
# ──────────────────────────────────────────────────────────────────────────────

class TestFileMd5:
    def test_md5_missing_file_returns_empty(self, indexer):
        assert indexer._file_md5() == ""

    def test_md5_matches_expected(self, indexer, tmp_path):
        content = b"Hello Memory"
        (tmp_path / "memory" / "MEMORY.md").write_bytes(content)
        expected = hashlib.md5(content).hexdigest()
        assert indexer._file_md5() == expected

    def test_md5_changes_after_file_edit(self, indexer, tmp_path):
        mem = tmp_path / "memory" / "MEMORY.md"
        mem.write_text("version 1", encoding="utf-8")
        md5_v1 = indexer._file_md5()
        mem.write_text("version 2 — different content", encoding="utf-8")
        md5_v2 = indexer._file_md5()
        assert md5_v1 != md5_v2


# ──────────────────────────────────────────────────────────────────────────────
# rebuild_index — no API key needed (file-not-found / empty paths)
# ──────────────────────────────────────────────────────────────────────────────

class TestRebuildIndexEdgeCases:
    def test_rebuild_missing_file_leaves_index_none(self, indexer):
        indexer.rebuild_index()
        assert indexer._index is None
        assert indexer._nodes == []

    def test_rebuild_empty_file_leaves_index_none(self, indexer, tmp_path):
        (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
        indexer.rebuild_index()
        assert indexer._index is None
        assert indexer._nodes == []

    def test_rebuild_updates_last_md5(self, indexer, tmp_path):
        mem = tmp_path / "memory" / "MEMORY.md"
        mem.write_text("some content", encoding="utf-8")
        expected_md5 = hashlib.md5(b"some content").hexdigest()
        # No API key — will fail at embedding step but MD5 should be set first
        try:
            indexer.rebuild_index()
        except Exception:
            pass
        # Even if embedding fails, last_md5 should have been updated
        assert indexer._last_md5 == expected_md5


# ──────────────────────────────────────────────────────────────────────────────
# _maybe_rebuild — triggers rebuild when MD5 changes
# ──────────────────────────────────────────────────────────────────────────────

class TestMaybeRebuild:
    def test_no_rebuild_when_md5_unchanged(self, indexer, tmp_path, monkeypatch):
        mem = tmp_path / "memory" / "MEMORY.md"
        mem.write_text("stable content", encoding="utf-8")
        indexer._last_md5 = indexer._file_md5()  # pre-set to current

        rebuild_called = []
        monkeypatch.setattr(indexer, "rebuild_index", lambda: rebuild_called.append(1))
        indexer._maybe_rebuild()
        assert rebuild_called == []

    def test_rebuild_when_md5_differs(self, indexer, tmp_path, monkeypatch):
        mem = tmp_path / "memory" / "MEMORY.md"
        mem.write_text("changed content", encoding="utf-8")
        indexer._last_md5 = "stale_md5"

        rebuild_called = []
        monkeypatch.setattr(indexer, "rebuild_index", lambda: rebuild_called.append(1))
        indexer._maybe_rebuild()
        assert rebuild_called == [1]

    def test_initial_empty_md5_triggers_rebuild(self, indexer, tmp_path, monkeypatch):
        mem = tmp_path / "memory" / "MEMORY.md"
        mem.write_text("some content", encoding="utf-8")
        # _last_md5 starts as ""

        rebuild_called = []
        monkeypatch.setattr(indexer, "rebuild_index", lambda: rebuild_called.append(1))
        indexer._maybe_rebuild()
        assert rebuild_called == [1]


# ──────────────────────────────────────────────────────────────────────────────
# retrieve — returns empty list when no index
# ──────────────────────────────────────────────────────────────────────────────

class TestRetrieve:
    def test_retrieve_no_file_returns_empty(self, indexer):
        results = indexer.retrieve("anything")
        assert results == []

    def test_retrieve_empty_file_returns_empty(self, indexer, tmp_path):
        (tmp_path / "memory" / "MEMORY.md").write_text("", encoding="utf-8")
        results = indexer.retrieve("anything")
        assert results == []

    @NEEDS_OPENAI
    def test_retrieve_with_content_returns_dicts(self, indexer, tmp_path):
        (tmp_path / "memory" / "MEMORY.md").write_text(
            "User likes Python. User is a software engineer.", encoding="utf-8"
        )
        results = indexer.retrieve("Python")
        assert isinstance(results, list)
        for r in results:
            assert "text" in r
            assert "score" in r
            assert "source" in r

    @NEEDS_OPENAI
    def test_retrieve_top_k_respected(self, indexer, tmp_path):
        content = "\n".join([f"Fact number {i}: something about topic {i}." for i in range(20)])
        (tmp_path / "memory" / "MEMORY.md").write_text(content, encoding="utf-8")
        results = indexer.retrieve("topic", top_k=2)
        assert len(results) <= 2
