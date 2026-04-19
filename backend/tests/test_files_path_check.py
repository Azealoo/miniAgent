"""Regression tests for _check_path whitelist ordering.

_check_path must resolve the path first, then apply the whitelist against the
*derived* relative path. A raw startswith() on user input is fragile: a
sibling directory named ``workspace_evil/`` can satisfy the naive check for a
``workspace/`` prefix on some shapes of input (e.g. after removeprefix()/
lstrip() normalization) and symlink tricks can let a valid-looking prefix
resolve elsewhere on disk.

Vectors covered:

* Prefix-name attack: ``workspace_evil/foo.txt``. The directory exists on
  disk, but it is not under ``workspace/`` once the resolved relative path
  is consulted, so the whitelist must refuse it.
* Traversal: ``workspace/../etc/passwd``. The ``..`` guard runs first and
  rejects before any disk access.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def isolated_base_dir(tmp_path):
    from graph.agent import agent_manager

    original_base_dir = agent_manager.base_dir
    original_memory_indexer = agent_manager.memory_indexer
    agent_manager.base_dir = tmp_path
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("workspace", "memory", "skills", "knowledge", "artifacts"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.memory_indexer = original_memory_indexer


class TestCheckPathOrdering:
    def test_prefix_name_attack_is_rejected(self, isolated_base_dir):
        """``workspace_evil/foo.txt`` must not satisfy the ``workspace/`` prefix."""
        from api.files import _check_path
        from fastapi import HTTPException

        evil = isolated_base_dir / "workspace_evil"
        evil.mkdir(parents=True, exist_ok=True)
        (evil / "foo.txt").write_text("should-not-be-readable\n", encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            _check_path("workspace_evil/foo.txt", write=False)

        assert exc_info.value.status_code == 403
        assert "access denied" in str(exc_info.value.detail).lower()

    def test_traversal_vector_is_rejected(self, isolated_base_dir):
        """``workspace/../etc/passwd`` must trip the traversal guard."""
        from api.files import _check_path
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _check_path("workspace/../etc/passwd", write=False)

        assert exc_info.value.status_code == 403
        assert "traversal" in str(exc_info.value.detail).lower()

    def test_valid_workspace_path_still_accepted(self, isolated_base_dir):
        """Sanity check: a legitimate ``workspace/`` path resolves cleanly."""
        from api.files import _check_path

        target, clean = _check_path("workspace/doc.txt", write=False)
        assert clean == "workspace/doc.txt"
        assert target == (isolated_base_dir / "workspace" / "doc.txt").resolve()

    def test_allowed_root_file_still_accepted(self, isolated_base_dir):
        """``SKILLS_SNAPSHOT.md`` is whitelisted as a root file and must pass."""
        from api.files import _check_path

        target, clean = _check_path("SKILLS_SNAPSHOT.md", write=False)
        assert clean == "SKILLS_SNAPSHOT.md"
        assert target == (isolated_base_dir / "SKILLS_SNAPSHOT.md").resolve()

    def test_stream_write_rejects_prefix_name_attack(self, isolated_base_dir):
        """``_check_stream_write_path`` shares the resolve-first ordering."""
        from api.files import _check_stream_write_path
        from fastapi import HTTPException

        (isolated_base_dir / "artifacts_evil").mkdir(parents=True, exist_ok=True)

        with pytest.raises(HTTPException) as exc_info:
            _check_stream_write_path("artifacts_evil/foo.bin")

        assert exc_info.value.status_code == 403
        assert "artifacts" in str(exc_info.value.detail).lower()

    def test_stream_write_rejects_traversal(self, isolated_base_dir):
        from api.files import _check_stream_write_path
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _check_stream_write_path("artifacts/../etc/passwd")

        assert exc_info.value.status_code == 403
        assert "traversal" in str(exc_info.value.detail).lower()
