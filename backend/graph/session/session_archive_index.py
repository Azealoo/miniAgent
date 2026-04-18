"""On-disk sidecar index for session archive batches.

The archive directory (``backend/sessions/archive/``) is a flat folder that
grows O(N) with the number of compressed batches across all sessions. The
``_index.json`` sidecar stored alongside the archive files maps each
``session_id`` to its archive-batch metadata so that listing is O(k) in the
batches-per-session instead of O(N) globbing+reading.

The file stays plain JSON (no database) so it remains inspectable and aligns
with the repository's file-first convention. It self-heals on miss or
corruption by scanning the directory once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from graph.session.session_schema import _ARCHIVE_ID_RE, _SESSION_ID_RE

ARCHIVE_INDEX_FILENAME = "_index.json"
ARCHIVE_INDEX_SCHEMA_VERSION = "archive_index.v1"


class ArchiveIndexEntry(TypedDict):
    archive_id: str
    message_count: int


def _index_path(archive_dir: Path) -> Path:
    return archive_dir / ARCHIVE_INDEX_FILENAME


def _split_archive_filename(stem: str) -> tuple[str, str] | None:
    """Return (session_id, archive_id) if *stem* matches the archive pattern.

    Archive files are named ``{session_id}_{archive_id}.json``. Session ids
    contain hyphens but never underscores, so we rsplit on the last ``_``.
    """
    if "_" not in stem:
        return None
    session_id, archive_id = stem.rsplit("_", 1)
    if not _SESSION_ID_RE.match(session_id):
        return None
    if not _ARCHIVE_ID_RE.match(archive_id):
        return None
    return session_id, archive_id


def _scan_archive_dir(archive_dir: Path) -> dict[str, list[ArchiveIndexEntry]]:
    """Rebuild the index by walking every archive file in *archive_dir*."""
    by_session: dict[str, list[ArchiveIndexEntry]] = {}
    for path in archive_dir.glob("*.json"):
        if path.name == ARCHIVE_INDEX_FILENAME:
            continue
        split = _split_archive_filename(path.stem)
        if split is None:
            continue
        session_id, archive_id = split
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        message_count = len(raw) if isinstance(raw, list) else 0
        by_session.setdefault(session_id, []).append(
            {"archive_id": archive_id, "message_count": message_count}
        )
    for entries in by_session.values():
        entries.sort(key=lambda e: e["archive_id"])
    return by_session


def _normalize_loaded_index(raw: Any) -> dict[str, list[ArchiveIndexEntry]] | None:
    """Return normalized index or None if *raw* is not a valid index payload."""
    if not isinstance(raw, dict):
        return None
    sessions = raw.get("sessions")
    if not isinstance(sessions, dict):
        return None
    normalized: dict[str, list[ArchiveIndexEntry]] = {}
    for session_id, entries in sessions.items():
        if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
            continue
        if not isinstance(entries, list):
            continue
        clean: list[ArchiveIndexEntry] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            archive_id = entry.get("archive_id")
            message_count = entry.get("message_count")
            if not isinstance(archive_id, str) or not _ARCHIVE_ID_RE.match(archive_id):
                continue
            if not isinstance(message_count, int) or message_count < 0:
                message_count = 0
            clean.append({"archive_id": archive_id, "message_count": message_count})
        if clean:
            clean.sort(key=lambda e: e["archive_id"])
            normalized[session_id] = clean
    return normalized


def _write_index(
    archive_dir: Path, index: dict[str, list[ArchiveIndexEntry]]
) -> None:
    """Atomically persist the sidecar via tmp-file + rename."""
    path = _index_path(archive_dir)
    payload: dict[str, Any] = {
        "schema_version": ARCHIVE_INDEX_SCHEMA_VERSION,
        "sessions": index,
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_index(archive_dir: Path) -> dict[str, list[ArchiveIndexEntry]]:
    """Load the sidecar, rebuilding on miss or corruption.

    The rebuilt index is persisted so subsequent reads avoid the scan cost,
    except when no index file exists *and* the archive directory has no
    archive files — writing an empty sidecar in that case would pollute the
    directory on every read.
    """
    path = _index_path(archive_dir)
    existing_bad = False

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing_bad = True
        else:
            normalized = _normalize_loaded_index(raw)
            if normalized is not None:
                return normalized
            existing_bad = True

    rebuilt = _scan_archive_dir(archive_dir)
    if existing_bad or rebuilt:
        _write_index(archive_dir, rebuilt)
    return rebuilt


def list_archive_entries(
    archive_dir: Path, session_id: str
) -> list[ArchiveIndexEntry]:
    """Return archive-batch entries for *session_id* using the sidecar."""
    index = _load_index(archive_dir)
    return list(index.get(session_id, []))


def append_archive_entry(
    archive_dir: Path,
    session_id: str,
    archive_id: str,
    message_count: int,
) -> None:
    """Record a new archive batch in the sidecar.

    Idempotent on ``archive_id``: re-inserting the same id overwrites the
    previous ``message_count`` rather than creating a duplicate entry.
    """
    index = _load_index(archive_dir)
    entries = [e for e in index.get(session_id, []) if e["archive_id"] != archive_id]
    entries.append({"archive_id": archive_id, "message_count": message_count})
    entries.sort(key=lambda e: e["archive_id"])
    index[session_id] = entries
    _write_index(archive_dir, index)


def remove_session_from_index(archive_dir: Path, session_id: str) -> None:
    """Drop all archive entries for *session_id* from the sidecar."""
    path = _index_path(archive_dir)
    if not path.exists():
        return
    index = _load_index(archive_dir)
    if session_id in index:
        index.pop(session_id)
        _write_index(archive_dir, index)


def rebuild_index(archive_dir: Path) -> dict[str, list[ArchiveIndexEntry]]:
    """Force a full rescan and overwrite the sidecar. Exposed for tooling."""
    rebuilt = _scan_archive_dir(archive_dir)
    _write_index(archive_dir, rebuilt)
    return rebuilt
