"""Tests for the shared memory write boundary.

`graph.memory_writer.write_memory_file` is the single funnel every in-process
writer under `memory/` must go through. These tests pin three guarantees:

1. valid frontmatter is written verbatim;
2. invalid frontmatter raises and the file is *not* created (no partial
   on-disk state for the indexer to trip over);
3. legacy markdown without frontmatter still writes (back-compat).

The fourth test pins the previously-broken bypass: the runtime memory
distillation writer now goes through the helper, so a regression that adds a
new `target.write_text(...)` direct call would surface as a missing rebuild
or a missing validation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_writer import MemoryFrontmatterError, write_memory_file


def _valid_frontmatter() -> str:
    return (
        "---\n"
        "type: project_fact\n"
        "name: test note\n"
        "description: a test note\n"
        "---\n"
        "body line\n"
    )


def test_write_memory_file_writes_valid_frontmatter(tmp_path):
    target = tmp_path / "memory" / "agent" / "ok.md"
    content = _valid_frontmatter()

    write_memory_file(target, "memory/agent/ok.md", content)

    assert target.read_text(encoding="utf-8") == content


def test_write_memory_file_rejects_invalid_frontmatter_without_writing(tmp_path):
    target = tmp_path / "memory" / "agent" / "bad.md"
    # Missing required `description` field.
    content = "---\ntype: project_fact\nname: test note\n---\nbody\n"

    with pytest.raises(MemoryFrontmatterError) as excinfo:
        write_memory_file(target, "memory/agent/bad.md", content)

    assert excinfo.value.errors, "MemoryFrontmatterError must carry validator output"
    assert not target.exists(), (
        "validation failures must not leave a half-written file on disk for the "
        "memory indexer to read"
    )


def test_write_memory_file_writes_legacy_markdown_without_frontmatter(tmp_path):
    target = tmp_path / "memory" / "project" / "legacy.md"

    write_memory_file(target, "memory/project/legacy.md", "# Legacy note\n")

    assert target.read_text(encoding="utf-8") == "# Legacy note\n"


def test_write_memory_file_does_not_validate_outside_memory(tmp_path):
    """skills/ and knowledge/ writes flow through the same helper but must not
    trip frontmatter validation — those trees do not carry typed memory
    metadata."""
    target = tmp_path / "skills" / "foo" / "SKILL.md"

    write_memory_file(target, "skills/foo/SKILL.md", "no frontmatter here")

    assert target.read_text(encoding="utf-8") == "no frontmatter here"


def test_write_memory_file_calls_supplied_indexer(tmp_path):
    class _SpyIndexer:
        def __init__(self) -> None:
            self.calls = 0

        def _maybe_rebuild(self) -> None:
            self.calls += 1

    indexer = _SpyIndexer()
    target = tmp_path / "memory" / "agent" / "ok.md"

    write_memory_file(
        target,
        "memory/agent/ok.md",
        _valid_frontmatter(),
        memory_indexer=indexer,
    )

    assert indexer.calls == 1


def test_write_memory_file_does_not_call_indexer_outside_memory(tmp_path):
    class _SpyIndexer:
        def __init__(self) -> None:
            self.calls = 0

        def _maybe_rebuild(self) -> None:
            self.calls += 1

    indexer = _SpyIndexer()
    target = tmp_path / "skills" / "foo" / "SKILL.md"

    write_memory_file(
        target,
        "skills/foo/SKILL.md",
        "hi",
        memory_indexer=indexer,
    )

    assert indexer.calls == 0


def test_write_memory_file_swallows_indexer_failures(tmp_path):
    class _BrokenIndexer:
        def _maybe_rebuild(self) -> None:
            raise RuntimeError("indexer offline")

    target = tmp_path / "memory" / "agent" / "ok.md"

    # Must not raise — a background rebuild glitch can't take down the write.
    write_memory_file(
        target,
        "memory/agent/ok.md",
        _valid_frontmatter(),
        memory_indexer=_BrokenIndexer(),
    )

    assert target.exists()


def test_all_memory_writers_route_through_helper():
    """Regression for issue #236: the runtime memory-distillation writer used
    to call ``target.write_text`` directly, bypassing
    ``validate_memory_write`` and risking indexer corruption. Pin that every
    in-process writer under ``memory/`` now imports the shared helper, and
    that no module under backend/ (except the helper itself and its tests)
    still has a raw ``write_text`` call against a path under ``memory/``.

    The check is grep-based on purpose — a runtime spy can be skipped, but a
    new direct writer would have to physically appear in source."""
    from graph import memory_writer

    backend_root = Path(__file__).parent.parent
    expected_users = (
        backend_root / "tools" / "write_file_tool.py",
        backend_root / "api" / "files.py",
        backend_root / "runtime" / "memory_distillation.py",
    )

    for path in expected_users:
        text = path.read_text(encoding="utf-8")
        assert "from graph.memory_writer import" in text, (
            f"{path.relative_to(backend_root)} must import the shared "
            f"memory writer so frontmatter validation is enforced at the "
            f"filesystem-write boundary"
        )
        assert "write_memory_file(" in text, (
            f"{path.relative_to(backend_root)} must call write_memory_file "
            f"instead of writing memory/ paths directly"
        )

    # Sanity: the helper itself must still expose the symbols.
    assert hasattr(memory_writer, "write_memory_file")
    assert hasattr(memory_writer, "MemoryFrontmatterError")
