"""Session disk I/O: atomic reads/writes, CRUD, and per-session compress locks.

Inter-process safety
--------------------
``SessionStore`` guards its write path with a POSIX ``fcntl.flock`` advisory
lock on a per-session lock file (``{sessions_dir}/{session_id}.lock``).
Combined with write-temp-then-``os.replace`` the session JSON is safe against
two uvicorn workers (or any other cooperating processes) racing on the same
session id: the lock serialises read-modify-write, and the atomic rename
means a concurrent reader ever sees only the pre- or post-write blob, never
a torn file. Pure readers don't take the lock — they rely on the atomic
rename alone.

**NFS caveat.** Advisory ``flock`` is only reliable on a local filesystem.
On NFSv3, ``flock`` is typically a no-op (silently ignored by the server)
and on NFSv4 it only works when the server's ``lockd``/``nfsd`` stack is
configured for byte-range locking. If ``sessions/`` lives on a networked
volume, keep it on NFSv4 with locking enabled or, better, move it to local
disk. Running with multiple uvicorn workers against an NFSv3-mounted
``sessions/`` will reintroduce the lost-write bug this lock is meant to
prevent.
"""

import asyncio
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from graph.session.session_archive_index import (
    _atomic_write_text,
    remove_session_from_index as _remove_session_from_archive_index,
)
from graph.session.session_index import (
    list_index_entries as _list_session_index_entries,
    remove_session_from_index as _remove_session_from_session_index,
    upsert_session_entry as _upsert_session_index_entry,
)
from graph.session.session_normalizer import (
    _build_blocks_from_legacy_message,
    _normalize_blocks,
    _normalize_messages,
    _normalize_record_list,
)
from graph.session.session_schema import (
    SESSION_SCHEMA_VERSION,
    SessionCorruptError,
    _validate_session_id,
)

logger = logging.getLogger(__name__)

# Per-session locks prevent two concurrent requests from compressing the same
# session simultaneously (which would double-archive messages). Entries are
# held with a strong reference and evicted explicitly from
# ``SessionStore.delete_session``; a prior ``WeakValueDictionary`` design had
# a GC race where a freshly installed Lock could be collected before a
# concurrent caller observed it, yielding two distinct locks for one
# session id and interleaved writes (see issue #222).
_compress_locks: dict[str, asyncio.Lock] = {}

# Per-session turn locks serialize /api/chat execution for a single session id
# so that two overlapping turns (e.g. a double-click or client retry) cannot
# interleave writes to the session JSON, memory, or turn ledger.
_turn_locks: dict[str, asyncio.Lock] = {}

# Guards creation of entries in the two registries above so concurrent callers
# cannot race and end up with two distinct asyncio.Lock instances for the
# same session id.
_lock_creation_mutex = threading.Lock()


@dataclass(frozen=True)
class FrozenSessionPrefix:
    """Session-scoped snapshot of the cache-stable prompt prefix + tool list.

    Sub-agents reuse ``stable_prefix`` as the leading system-prompt string so
    the provider's server-side prefix cache matches across the parent turn and
    helper runs. ``tool_names`` and ``prefix_fingerprint`` let the runtime
    detect drift (a skill added mid-session, a workspace file edited) that
    would silently invalidate the cache.
    """

    stable_prefix: str
    tool_names: tuple[str, ...]
    prefix_fingerprint: str


# Per-session frozen prefix cache. Sub-agent contracts read this to reuse the
# byte-identical leading prompt and maximise prompt-cache hits.
_frozen_prefixes: dict[str, FrozenSessionPrefix] = {}
_frozen_prefix_drift_logged: set[str] = set()
_frozen_prefix_lock = threading.Lock()


def _get_or_create_lock(
    registry: dict[str, asyncio.Lock],
    session_id: str,
) -> asyncio.Lock:
    """Return an asyncio.Lock for *session_id*, creating at most one.

    Double-checked locking under ``_lock_creation_mutex`` keeps two concurrent
    callers from installing distinct Lock instances for the same session id.
    The registry is a plain ``dict`` that holds a strong reference, so a
    freshly installed lock cannot be collected before a concurrent caller
    observes it (issue #222). Eviction is explicit via
    :meth:`SessionStore.delete_session`.
    """
    lock = registry.get(session_id)
    if lock is not None:
        return lock
    with _lock_creation_mutex:
        lock = registry.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            registry[session_id] = lock
        return lock


def _fingerprint_prefix(stable_prefix: str, tool_names: tuple[str, ...]) -> str:
    hasher = hashlib.sha256()
    hasher.update(stable_prefix.encode("utf-8"))
    hasher.update(b"\x1f")
    for name in tool_names:
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x1e")
    return hasher.hexdigest()


class SessionStore:
    def __init__(self, base_dir: Path) -> None:
        self.sessions_dir = base_dir / "sessions"
        self.archive_dir = self.sessions_dir / "archive"
        self.quarantine_dir = self.sessions_dir / "_quarantine"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _path(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.json"

    def _lock_path(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.lock"

    @contextlib.contextmanager
    def _locked(self, session_id: str) -> Iterator[None]:
        """Hold a POSIX exclusive advisory lock for *session_id*.

        Callers that perform a read-modify-write sequence must wrap the whole
        sequence — locking ``_read`` and ``_write`` independently is not
        enough, because another process could slip in between and cause a
        lost update. The lock is keyed on a dedicated ``{session_id}.lock``
        file rather than the session JSON itself so ``os.replace`` (which
        swaps inodes) does not invalidate an outstanding lock.
        """
        lock_path = self._lock_path(session_id)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _quarantine_corrupt_file(self, path: Path, session_id: str) -> Path:
        """Move *path* into ``sessions/_quarantine/`` and return the new path.

        Used when a session JSON file fails to decode. Preserves the bad
        bytes for forensic review while clearing the active slot so the
        next read returns an empty session.
        """
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantined = self.quarantine_dir / f"{int(time.time())}_{session_id}.json"
        try:
            path.replace(quarantined)
        except OSError as exc:
            logger.warning(
                "session_quarantine_failed session_id=%s path=%s error=%s",
                session_id,
                path,
                exc,
            )
            return quarantined
        logger.warning(
            "session_quarantined session_id=%s quarantine_path=%s",
            session_id,
            quarantined,
        )
        return quarantined

    def _read(self, session_id: str, *, raise_on_corrupt: bool = False) -> dict:
        path = self._path(session_id)
        if not path.exists():
            return self._empty(session_id)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            quarantined = self._quarantine_corrupt_file(path, session_id)
            if raise_on_corrupt:
                raise SessionCorruptError(
                    session_id, str(quarantined), original_error=exc
                ) from exc
            # Default: behave like the pre-quarantine code path and return an
            # empty session so internal call sites (turn runtime, files
            # workspace summary, token stats, compaction) do not start raising
            # generic 500s when a single session file is corrupt. The bytes
            # were preserved in ``_quarantine`` and the API endpoints that
            # want a typed 422 opt in via ``raise_on_corrupt=True``.
            return self._empty(session_id)
        except OSError as exc:
            # Transient read failure (permissions, EBUSY, etc.) — surface as
            # an empty session rather than destroying the file.
            logger.warning(
                "session_read_fallback session_id=%s path=%s error=%s",
                session_id,
                path,
                exc,
            )
            return self._empty(session_id)

        # v1 migration: plain list → v2 dict
        if isinstance(raw, list):
            raw = {
                "title": session_id,
                "created_at": 0.0,
                "updated_at": 0.0,
                "compressed_context": "",
                "compressed_archive_index": [],
                "messages": raw,
            }
            self._write(session_id, raw)

        return raw

    def _write(self, session_id: str, data: dict) -> None:
        data.setdefault("schema_version", SESSION_SCHEMA_VERSION)
        data["updated_at"] = time.time()
        self._stamp_deterministic_mode(data)
        _atomic_write_text(
            self._path(session_id),
            json.dumps(data, ensure_ascii=False, indent=2),
        )
        messages = data.get("messages", [])
        _upsert_session_index_entry(
            self.sessions_dir,
            session_id,
            title=data.get("title", session_id),
            updated_at=data.get("updated_at", 0.0),
            message_count=len(messages) if isinstance(messages, list) else 0,
        )

    @staticmethod
    def _stamp_deterministic_mode(data: dict) -> None:
        # Deferred import avoids a config ↔ session_manager circular import at module load.
        import config

        seed = config.get_deterministic_seed()
        if seed is None:
            data.pop("deterministic", None)
        else:
            data["deterministic"] = {"seed": seed}

    @staticmethod
    def _empty(session_id: str) -> dict:
        now = time.time()
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "compressed_context": "",
            "compressed_archive_index": [],
            "messages": [],
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        data = self._empty(session_id)
        with self._locked(session_id):
            self._write(session_id, data)
        return session_id

    def list_sessions(self) -> list[dict]:
        # Reads the ``_index.json`` sidecar so we avoid an O(N) glob+open of
        # every session file. ``_load_index`` self-heals if the sidecar is
        # missing, malformed, or has an unknown schema version. Corrupt
        # session files are quarantined on demand by ``_read`` when any caller
        # attempts to load them directly.
        return _list_session_index_entries(self.sessions_dir)

    def load_session(
        self, session_id: str, *, raise_on_corrupt: bool = False
    ) -> list[dict]:
        """Return the raw message array (for display / history endpoint).

        ``raise_on_corrupt=True`` surfaces ``SessionCorruptError`` when the
        underlying file fails to decode; the default mirrors prior behavior
        and returns an empty session so internal callers do not regress.
        """
        return _normalize_messages(
            self._read(session_id, raise_on_corrupt=raise_on_corrupt).get(
                "messages", []
            )
        )

    def load_request_messages(self, session_id: str, request_id: str) -> list[dict]:
        """Return normalized messages associated with a persisted request id."""
        normalized_request_id = request_id.strip()
        if not normalized_request_id:
            return []
        return [
            message
            for message in self.load_session(session_id)
            if message.get("request_id") == normalized_request_id
        ]

    def load_session_for_agent(
        self, session_id: str, *, raise_on_corrupt: bool = False
    ) -> list[dict]:
        """
        Return history optimised for the LLM:
        - Consecutive assistant messages are merged into one.
        - If compressed_context exists, a synthetic system message is
          prepended containing the summary.

        ``raise_on_corrupt=True`` surfaces ``SessionCorruptError`` when the
        underlying file fails to decode; the default mirrors prior behavior
        and returns an empty history so the turn runtime keeps working.
        """
        data = self._read(session_id, raise_on_corrupt=raise_on_corrupt)
        messages = self.load_session(session_id)
        compressed = data.get("compressed_context", "")

        # Merge consecutive assistant messages
        merged: list[dict] = []
        for msg in messages:
            if merged and merged[-1]["role"] == "assistant" and msg["role"] == "assistant":
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(dict(msg))

        # Prepend compressed context as a system message.
        # Using "assistant" here would cause API rejection: most LLMs require that
        # the first non-system message be a user message, not an assistant message.
        if compressed:
            synthetic = {
                "role": "system",
                "content": f"[Summary of earlier conversation — treat as background context]\n{compressed}",
            }
            merged = [synthetic] + merged

        return merged

    @staticmethod
    def _build_message_record(
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        retrievals: Optional[list] = None,
        request_id: str | None = None,
        blocks: Optional[list[dict[str, Any]]] = None,
    ) -> dict:
        msg: dict = {"role": role, "content": content}
        normalized_blocks = _normalize_blocks(blocks)

        if not normalized_blocks:
            normalized_blocks = _build_blocks_from_legacy_message(
                role,
                content,
                _normalize_record_list(tool_calls),
                _normalize_record_list(retrievals),
            )

        if request_id:
            msg["request_id"] = request_id
        if normalized_blocks:
            msg["blocks"] = normalized_blocks

        return msg

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
        retrievals: Optional[list] = None,
        request_id: str | None = None,
        blocks: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        msg = self._build_message_record(
            role,
            content,
            tool_calls=tool_calls,
            retrievals=retrievals,
            request_id=request_id,
            blocks=blocks,
        )

        # Hold the inter-process lock across read-append-write so a second
        # worker racing on the same session_id cannot read a stale message
        # list and clobber our append when it writes back.
        with self._locked(session_id):
            data = self._read(session_id)
            data["messages"].append(msg)
            self._write(session_id, data)

    def save_messages_batch(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Append multiple messages in one read-modify-write under one flock.

        Each dict in *messages* accepts the same keys as :meth:`save_message`
        (``role``, ``content``, plus optional ``tool_calls``/``retrievals``/
        ``request_id``/``blocks``). Turn-scoped persistence uses this so the
        user message and every assistant segment land in a single atomic
        write — cross-process readers observe either the pre-turn or the
        post-turn message list, never a partially-committed turn.
        """
        if not messages:
            return

        records: list[dict] = []
        for raw in messages:
            if not isinstance(raw, dict):
                raise TypeError("save_messages_batch entries must be dicts")
            records.append(
                self._build_message_record(
                    raw["role"],
                    raw.get("content", ""),
                    tool_calls=raw.get("tool_calls"),
                    retrievals=raw.get("retrievals"),
                    request_id=raw.get("request_id"),
                    blocks=raw.get("blocks"),
                )
            )

        with self._locked(session_id):
            data = self._read(session_id)
            data["messages"].extend(records)
            self._write(session_id, data)

    def rename_session(
        self, session_id: str, title: str, *, raise_on_corrupt: bool = False
    ) -> None:
        with self._locked(session_id):
            data = self._read(session_id, raise_on_corrupt=raise_on_corrupt)
            data["title"] = title
            self._write(session_id, data)

    def delete_session(self, session_id: str) -> None:
        path = self._path(session_id)

        # Fire post-session distillation before removing the session file.
        # Deferred import: runtime.memory_distillation imports SessionManager,
        # so a top-level import would create a cycle at module load time.
        try:
            from runtime.memory_distillation import fire_post_session_distillation

            fire_post_session_distillation(
                session_id,
                base_dir=self.sessions_dir.parent,
                session_manager=self,
            )
        except Exception:
            # Fire-and-forget: scheduling failures must never block deletion.
            pass

        with self._locked(session_id):
            if path.exists():
                path.unlink()
            for archive_path in self.archive_dir.glob(f"{session_id}_*.json"):
                try:
                    archive_path.unlink()
                except FileNotFoundError:
                    continue
        _remove_session_from_archive_index(self.archive_dir, session_id)
        _remove_session_from_session_index(self.sessions_dir, session_id)
        # Best-effort cleanup of the on-disk lock file — failure is fine
        # (a concurrent worker may still hold it open).
        with contextlib.suppress(FileNotFoundError):
            self._lock_path(session_id).unlink()
        # Clean up the per-session locks to prevent unbounded memory growth.
        # Holding ``_lock_creation_mutex`` keeps this consistent with
        # ``_get_or_create_lock`` so a concurrent creator observes either the
        # pre-delete lock (and proceeds on a dying session, which the outer
        # file-lock guards) or installs a fresh one; it cannot observe a
        # half-removed state.
        with _lock_creation_mutex:
            _compress_locks.pop(session_id, None)
            _turn_locks.pop(session_id, None)
        self.clear_frozen_session_prefix(session_id)

    def get_or_create_compress_lock(self, session_id: str) -> asyncio.Lock:
        """Return (creating if needed) the asyncio.Lock for *session_id*."""
        return _get_or_create_lock(_compress_locks, session_id)

    def get_or_create_turn_lock(self, session_id: str) -> asyncio.Lock:
        """Return (creating if needed) the turn-serialization Lock for *session_id*."""
        return _get_or_create_lock(_turn_locks, session_id)

    # ------------------------------------------------------------------ #
    # Frozen prompt-cache prefix                                          #
    # ------------------------------------------------------------------ #

    def freeze_session_prefix(
        self,
        session_id: str,
        *,
        stable_prefix: str,
        tool_names: tuple[str, ...],
    ) -> FrozenSessionPrefix:
        """Record (on first call) or return the session's frozen prompt prefix.

        The prefix + tool list are the leading bytes of the system prompt that
        must stay byte-identical across the parent turn and every sub-agent
        run for DeepSeek / OpenAI / Anthropic prompt-cache hits. We freeze on
        the first turn and never replace the snapshot — subsequent turns with
        a different prefix log a drift warning (workspace edits, skills added
        mid-session) so the loss of cache-eligibility is visible.
        """
        _validate_session_id(session_id)
        fingerprint = _fingerprint_prefix(stable_prefix, tool_names)
        with _frozen_prefix_lock:
            existing = _frozen_prefixes.get(session_id)
            if existing is not None:
                if existing.prefix_fingerprint != fingerprint and session_id not in _frozen_prefix_drift_logged:
                    _frozen_prefix_drift_logged.add(session_id)
                    logger.warning(
                        "session_prefix_drift session_id=%s — frozen prefix no "
                        "longer matches current prompt assembly; sub-agent "
                        "prompt-cache hits will degrade for this session.",
                        session_id,
                    )
                return existing
            frozen = FrozenSessionPrefix(
                stable_prefix=stable_prefix,
                tool_names=tool_names,
                prefix_fingerprint=fingerprint,
            )
            _frozen_prefixes[session_id] = frozen
            return frozen

    def get_frozen_session_prefix(self, session_id: str) -> FrozenSessionPrefix | None:
        """Return the frozen prefix for *session_id*, or ``None`` if unset."""
        if not isinstance(session_id, str) or not session_id:
            return None
        with _frozen_prefix_lock:
            return _frozen_prefixes.get(session_id)

    def clear_frozen_session_prefix(self, session_id: str) -> None:
        """Drop the frozen prefix (used when the session is deleted)."""
        with _frozen_prefix_lock:
            _frozen_prefixes.pop(session_id, None)
            _frozen_prefix_drift_logged.discard(session_id)

    def get_session_meta(self, session_id: str) -> dict:
        data = self._read(session_id)
        meta = {
            "id": session_id,
            "title": data.get("title", ""),
            "created_at": data.get("created_at", 0.0),
            "updated_at": data.get("updated_at", 0.0),
            "message_count": len(data.get("messages", [])),
        }
        runtime_config = data.get("runtime_config")
        if isinstance(runtime_config, dict):
            meta["runtime_config"] = {
                "_loaded_at": runtime_config.get("_loaded_at"),
            }
        return meta

    def stamp_runtime_config_snapshot(
        self,
        session_id: str,
        *,
        loaded_at: float,
    ) -> None:
        """Record when the runtime config was frozen for the current turn.

        The timestamp is written under the ``runtime_config._loaded_at``
        key on the session JSON. Later inspection tools can use it to prove
        that a turn's behavior was bound to the config that was live at
        turn entry — not a mid-turn mutation.
        """
        path = self._path(session_id)
        if not path.exists():
            # Nothing to stamp if the session file has not been materialized
            # yet; the first save_message call will create it.
            return
        with self._locked(session_id):
            data = self._read(session_id)
            runtime_config = data.get("runtime_config")
            if not isinstance(runtime_config, dict):
                runtime_config = {}
            runtime_config["_loaded_at"] = float(loaded_at)
            data["runtime_config"] = runtime_config
            self._write(session_id, data)
