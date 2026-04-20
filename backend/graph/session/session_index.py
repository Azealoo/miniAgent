"""On-disk sidecar index for the sessions directory.

``SessionManager.list_sessions()`` historically globbed every ``*.json`` file
under ``backend/sessions/`` and opened each to read title + updated_at +
message count. That cost is O(N) disk reads per listing. The ``_index.json``
sidecar stored alongside the session files collapses that to a single read
by caching the displayable metadata.

The file stays plain JSON (no database) so it remains inspectable and aligns
with the repository's file-first convention. It self-heals on miss or
corruption by scanning the directory once.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, TypedDict

from graph.session.session_schema import _SESSION_ID_RE

SESSION_INDEX_FILENAME = "_index.json"
SESSION_INDEX_SCHEMA_VERSION = "session_index.v1"


def _compute_sessions_checksum(sessions: dict[str, Any]) -> str:
    """Stable SHA-256 digest over the sessions payload.

    ``sort_keys=True`` makes the digest insensitive to dict ordering so the
    same logical payload always hashes to the same value — but any change to
    entry fields (title / updated_at / message_count) flips it, which is what
    lets ``_normalize_loaded_index`` detect semantically-corrupt but
    syntactically-valid sidecars.
    """
    canonical = json.dumps(sessions, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SessionIndexEntry(TypedDict):
    title: str
    updated_at: float
    message_count: int


def _index_path(sessions_dir: Path) -> Path:
    return sessions_dir / SESSION_INDEX_FILENAME


def _scan_sessions_dir(sessions_dir: Path) -> dict[str, SessionIndexEntry]:
    """Rebuild the index by reading every session file in *sessions_dir*."""
    index: dict[str, SessionIndexEntry] = {}
    if not sessions_dir.exists():
        return index
    for path in sessions_dir.glob("*.json"):
        if path.name == SESSION_INDEX_FILENAME:
            continue
        session_id = path.stem
        if not _SESSION_ID_RE.match(session_id):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(raw, list):
            # v1 session files were bare lists; treat the filename as title.
            title: str = session_id
            updated_at: float = 0.0
            message_count = len(raw)
        elif isinstance(raw, dict):
            title_val = raw.get("title", session_id)
            title = title_val if isinstance(title_val, str) else session_id
            updated_at_val = raw.get("updated_at", 0.0)
            updated_at = (
                float(updated_at_val)
                if isinstance(updated_at_val, (int, float))
                else 0.0
            )
            messages = raw.get("messages", [])
            message_count = len(messages) if isinstance(messages, list) else 0
        else:
            continue
        index[session_id] = {
            "title": title,
            "updated_at": updated_at,
            "message_count": message_count,
        }
    return index


def _normalize_entry(raw: Any, session_id: str) -> SessionIndexEntry | None:
    if not isinstance(raw, dict):
        return None
    title = raw.get("title", session_id)
    if not isinstance(title, str):
        title = session_id
    updated_at = raw.get("updated_at", 0.0)
    if not isinstance(updated_at, (int, float)):
        updated_at = 0.0
    message_count = raw.get("message_count", 0)
    if not isinstance(message_count, int) or message_count < 0:
        message_count = 0
    return {
        "title": title,
        "updated_at": float(updated_at),
        "message_count": message_count,
    }


def _normalize_loaded_index(raw: Any) -> dict[str, SessionIndexEntry] | None:
    """Return normalized index or None if *raw* is not a valid index payload."""
    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != SESSION_INDEX_SCHEMA_VERSION:
        return None
    sessions = raw.get("sessions")
    if not isinstance(sessions, dict):
        return None
    checksum = raw.get("checksum")
    if not isinstance(checksum, str):
        return None
    if checksum != _compute_sessions_checksum(sessions):
        return None
    normalized: dict[str, SessionIndexEntry] = {}
    for session_id, entry in sessions.items():
        if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
            continue
        clean = _normalize_entry(entry, session_id)
        if clean is None:
            continue
        normalized[session_id] = clean
    return normalized


def _write_index(sessions_dir: Path, index: dict[str, SessionIndexEntry]) -> None:
    """Atomically persist the sidecar via tmp-file + rename.

    The tmp filename is salted with pid + a uuid4 suffix so concurrent
    writers (e.g. simultaneous ``create_session`` / ``save_message`` calls in
    multi-request deployments) do not race on a shared tmp path and raise
    ``FileNotFoundError`` from ``tmp.replace(path)``.
    """
    path = _index_path(sessions_dir)
    payload: dict[str, Any] = {
        "schema_version": SESSION_INDEX_SCHEMA_VERSION,
        "checksum": _compute_sessions_checksum(index),
        "sessions": index,
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _existing_session_ids(sessions_dir: Path) -> set[str]:
    """Return the set of session ids that currently have a file on disk."""
    ids: set[str] = set()
    if not sessions_dir.exists():
        return ids
    for path in sessions_dir.glob("*.json"):
        if path.name == SESSION_INDEX_FILENAME:
            continue
        if _SESSION_ID_RE.match(path.stem):
            ids.add(path.stem)
    return ids


def _prune_missing_sessions(
    sessions_dir: Path, index: dict[str, SessionIndexEntry]
) -> bool:
    """Drop entries whose session file is no longer on disk.

    Returns True if any entry was removed (so the caller can persist the
    pruned index). A single directory scan is cheaper than stat-per-entry
    and still much faster than the old glob+read fallback.
    """
    if not index:
        return False
    existing = _existing_session_ids(sessions_dir)
    stale = [sid for sid in index if sid not in existing]
    for sid in stale:
        index.pop(sid, None)
    return bool(stale)


def _load_index(sessions_dir: Path) -> dict[str, SessionIndexEntry]:
    """Load the sidecar, rebuilding on miss or corruption.

    The rebuilt index is persisted so subsequent reads avoid the scan cost,
    except when no index file exists *and* the sessions directory has no
    session files — writing an empty sidecar in that case would pollute the
    directory on every read.

    Sidecar entries are revalidated against the on-disk session files so
    out-of-band deletions (e.g. by the retention runner, which unlinks
    files directly) do not surface phantom sessions in ``list_sessions``.
    """
    path = _index_path(sessions_dir)
    existing_bad = False

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing_bad = True
        else:
            normalized = _normalize_loaded_index(raw)
            if normalized is not None:
                if _prune_missing_sessions(sessions_dir, normalized):
                    _write_index(sessions_dir, normalized)
                return normalized
            existing_bad = True

    rebuilt = _scan_sessions_dir(sessions_dir)
    if existing_bad or rebuilt:
        _write_index(sessions_dir, rebuilt)
    return rebuilt


def list_index_entries(sessions_dir: Path) -> list[dict[str, Any]]:
    """Return session entries (sorted by updated_at desc) from the sidecar."""
    index = _load_index(sessions_dir)
    rows = [
        {
            "id": session_id,
            "title": entry["title"],
            "updated_at": entry["updated_at"],
            "message_count": entry["message_count"],
        }
        for session_id, entry in index.items()
    ]
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows


def upsert_session_entry(
    sessions_dir: Path,
    session_id: str,
    *,
    title: str,
    updated_at: float,
    message_count: int,
) -> None:
    """Record or update *session_id* in the sidecar.

    Idempotent: calling with the same session_id overwrites the previous
    entry rather than creating a duplicate.
    """
    index = _load_index(sessions_dir)
    index[session_id] = {
        "title": title,
        "updated_at": float(updated_at),
        "message_count": int(message_count),
    }
    _write_index(sessions_dir, index)


def remove_session_from_index(sessions_dir: Path, session_id: str) -> None:
    """Drop *session_id* from the sidecar. No-op if the sidecar is absent."""
    path = _index_path(sessions_dir)
    if not path.exists():
        return
    index = _load_index(sessions_dir)
    if session_id in index:
        index.pop(session_id)
        _write_index(sessions_dir, index)


def rebuild_index(sessions_dir: Path) -> dict[str, SessionIndexEntry]:
    """Force a full rescan and overwrite the sidecar. Exposed for tooling."""
    rebuilt = _scan_sessions_dir(sessions_dir)
    _write_index(sessions_dir, rebuilt)
    return rebuilt
