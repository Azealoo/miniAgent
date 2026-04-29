"""Single filesystem-write boundary for files under ``memory/``.

Every in-process writer that lands content under ``memory/`` (the
``write_file`` tool, the ``/api/files/save`` editor endpoint, and the
runtime memory-distillation hooks) must go through :func:`write_memory_file`
so the typed-frontmatter validator can never be skipped. A bypass would let a
file with broken frontmatter reach disk and corrupt the memory indexer's
rebuild.

The helper does not log audit events — those vary per call site
(``api.files`` vs ``write_file_tool`` vs ``memory_distillation``) — and it
deliberately raises on validation failure so callers must decide a policy
(reject the request, log-and-skip, etc.) rather than silently fall through.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory_types import validate_memory_write


class MemoryFrontmatterError(ValueError):
    """Raised when ``validate_memory_write`` rejects the proposed content."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        super().__init__(" ".join(errors) if errors else "memory frontmatter validation failed")
        self.errors = errors


def write_memory_file(
    target: Path,
    relative_path: str,
    content: str,
    *,
    memory_indexer: Any | None = None,
) -> Path:
    """Validate frontmatter, write *content* to *target*, refresh the indexer.

    ``relative_path`` is the path-as-seen-by-the-validator (e.g.
    ``memory/agent/session-abc.md``); ``target`` is the already-resolved,
    security-checked absolute path the caller intends to write. Splitting the
    two avoids re-doing path resolution here and keeps the security boundary
    (path traversal, allowlist, secret-file check) with the caller.

    Raises :class:`MemoryFrontmatterError` when validation fails. On success,
    writes ``content`` (UTF-8), creates parent directories, and triggers an
    incremental rebuild on the supplied ``memory_indexer`` (or the global
    ``agent_manager.memory_indexer`` when not supplied) for any path under
    ``memory/``. Indexer failures are swallowed so a write never breaks on a
    background rebuild glitch.
    """
    errors = validate_memory_write(relative_path, content)
    if errors:
        raise MemoryFrontmatterError(errors)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    if relative_path.startswith("memory/"):
        indexer = memory_indexer
        if indexer is None:
            try:
                from graph.agent import agent_manager

                indexer = agent_manager.memory_indexer
            except Exception:
                indexer = None
        if indexer is not None:
            try:
                indexer._maybe_rebuild()
            except Exception:
                pass

    return target
