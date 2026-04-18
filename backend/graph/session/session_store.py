"""Session disk I/O: atomic reads/writes, CRUD, and per-session compress locks."""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from graph.session.session_normalizer import (
    _build_blocks_from_legacy_message,
    _normalize_blocks,
    _normalize_messages,
    _normalize_record_list,
)
from graph.session.session_schema import SESSION_SCHEMA_VERSION, _validate_session_id

# Per-session locks prevent two concurrent requests from compressing the same
# session simultaneously (which would double-archive messages).
_compress_locks: dict[str, asyncio.Lock] = {}


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
        sessions = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    title, updated_at, msgs = path.stem, 0.0, raw
                else:
                    title = raw.get("title", path.stem)
                    updated_at = raw.get("updated_at", 0.0)
                    msgs = raw.get("messages", [])
                sessions.append(
                    {
                        "id": path.stem,
                        "title": title,
                        "updated_at": updated_at,
                        "message_count": len(msgs),
                    }
                )
            except Exception:
                continue
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        return sessions

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
        # Clean up the per-session lock to prevent unbounded memory growth
        _compress_locks.pop(session_id, None)

    def get_or_create_compress_lock(self, session_id: str) -> asyncio.Lock:
        """Return (creating if needed) the asyncio.Lock for *session_id*."""
        if session_id not in _compress_locks:
            _compress_locks[session_id] = asyncio.Lock()
        return _compress_locks[session_id]

    def get_session_meta(self, session_id: str) -> dict:
        data = self._read(session_id)
        return {
            "id": session_id,
            "title": data.get("title", ""),
            "created_at": data.get("created_at", 0.0),
            "updated_at": data.get("updated_at", 0.0),
            "message_count": len(data.get("messages", [])),
        }
