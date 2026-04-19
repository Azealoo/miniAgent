"""Session disk I/O: atomic reads/writes, CRUD, and per-session compress locks."""

import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from graph.session.session_archive_index import (
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
from graph.session.session_schema import SESSION_SCHEMA_VERSION, _validate_session_id

logger = logging.getLogger(__name__)

# Per-session locks prevent two concurrent requests from compressing the same
# session simultaneously (which would double-archive messages).
_compress_locks: dict[str, asyncio.Lock] = {}

# Per-session turn locks serialize /api/chat execution for a single session id so
# that two overlapping turns (e.g. a double-click or client retry) cannot
# interleave writes to the session JSON, memory, or turn ledger.
_turn_locks: dict[str, asyncio.Lock] = {}


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
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _path(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.json"

    def _read(self, session_id: str) -> dict:
        path = self._path(session_id)
        if not path.exists():
            return self._empty(session_id)

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Corrupted or unreadable file — return a fresh session structure
            # rather than propagating a 500 error to the user.
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
        self._path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
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
        self._write(session_id, data)
        return session_id

    def list_sessions(self) -> list[dict]:
        # Reads the ``_index.json`` sidecar so we avoid an O(N) glob+open of
        # every session file. ``_load_index`` self-heals if the sidecar is
        # missing, malformed, or has an unknown schema version.
        return _list_session_index_entries(self.sessions_dir)

    def load_session(self, session_id: str) -> list[dict]:
        """Return the raw message array (for display / history endpoint)."""
        return _normalize_messages(self._read(session_id).get("messages", []))

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

    def load_session_for_agent(self, session_id: str) -> list[dict]:
        """
        Return history optimised for the LLM:
        - Consecutive assistant messages are merged into one.
        - If compressed_context exists, a synthetic system message is
          prepended containing the summary.
        """
        data = self._read(session_id)
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
        data = self._read(session_id)
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

        data["messages"].append(msg)
        self._write(session_id, data)

    def rename_session(self, session_id: str, title: str) -> None:
        data = self._read(session_id)
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

        if path.exists():
            path.unlink()
        for archive_path in self.archive_dir.glob(f"{session_id}_*.json"):
            try:
                archive_path.unlink()
            except FileNotFoundError:
                continue
        _remove_session_from_archive_index(self.archive_dir, session_id)
        _remove_session_from_session_index(self.sessions_dir, session_id)
        # Clean up the per-session locks to prevent unbounded memory growth
        _compress_locks.pop(session_id, None)
        _turn_locks.pop(session_id, None)
        self.clear_frozen_session_prefix(session_id)

    def get_or_create_compress_lock(self, session_id: str) -> asyncio.Lock:
        """Return (creating if needed) the asyncio.Lock for *session_id*."""
        if session_id not in _compress_locks:
            _compress_locks[session_id] = asyncio.Lock()
        return _compress_locks[session_id]

    def get_or_create_turn_lock(self, session_id: str) -> asyncio.Lock:
        """Return (creating if needed) the turn-serialization Lock for *session_id*."""
        if session_id not in _turn_locks:
            _turn_locks[session_id] = asyncio.Lock()
        return _turn_locks[session_id]

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
        data = self._read(session_id)
        runtime_config = data.get("runtime_config")
        if not isinstance(runtime_config, dict):
            runtime_config = {}
        runtime_config["_loaded_at"] = float(loaded_at)
        data["runtime_config"] = runtime_config
        self._write(session_id, data)
