import json
import time
import uuid
from pathlib import Path
from typing import Optional


class SessionManager:
    def __init__(self, base_dir: Path) -> None:
        self.sessions_dir = base_dir / "sessions"
        self.archive_dir = self.sessions_dir / "archive"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _read(self, session_id: str) -> dict:
        path = self._path(session_id)
        if not path.exists():
            return self._empty(session_id)

        raw = json.loads(path.read_text(encoding="utf-8"))

        # v1 migration: plain list → v2 dict
        if isinstance(raw, list):
            raw = {
                "title": session_id,
                "created_at": 0.0,
                "updated_at": 0.0,
                "compressed_context": "",
                "messages": raw,
            }
            self._write(session_id, raw)

        return raw

    def _write(self, session_id: str, data: dict) -> None:
        data["updated_at"] = time.time()
        self._path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _empty(session_id: str) -> dict:
        now = time.time()
        return {
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "compressed_context": "",
            "messages": [],
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        data = self._empty(session_id)
        self._path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
        return self._read(session_id)["messages"]

    def load_session_for_agent(self, session_id: str) -> list[dict]:
        """
        Return history optimised for the LLM:
        - Consecutive assistant messages are merged into one.
        - If compressed_context exists, a synthetic assistant message is
          prepended containing the summary.
        """
        data = self._read(session_id)
        messages = data["messages"]
        compressed = data.get("compressed_context", "")

        # Merge consecutive assistant messages
        merged: list[dict] = []
        for msg in messages:
            if merged and merged[-1]["role"] == "assistant" and msg["role"] == "assistant":
                merged[-1]["content"] += "\n\n" + msg["content"]
            else:
                merged.append(dict(msg))

        # Prepend compressed context
        if compressed:
            synthetic = {
                "role": "assistant",
                "content": f"[Summary of previous conversation]\n{compressed}",
            }
            merged = [synthetic] + merged

        return merged

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list] = None,
    ) -> None:
        data = self._read(session_id)
        msg: dict = {"role": role, "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        data["messages"].append(msg)
        self._write(session_id, data)

    def rename_session(self, session_id: str, title: str) -> None:
        data = self._read(session_id)
        data["title"] = title
        self._write(session_id, data)

    def delete_session(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def get_session_meta(self, session_id: str) -> dict:
        data = self._read(session_id)
        return {
            "id": session_id,
            "title": data.get("title", ""),
            "created_at": data.get("created_at", 0.0),
            "updated_at": data.get("updated_at", 0.0),
            "message_count": len(data.get("messages", [])),
        }

    def compress_history(self, session_id: str, summary: str, n: int) -> tuple[int, int]:
        """
        Archive the first *n* messages and store *summary* in compressed_context.
        Returns (archived_count, remaining_count).
        """
        data = self._read(session_id)
        messages = data["messages"]

        archived = messages[:n]
        remaining = messages[n:]

        # Write archive file
        archive_path = self.archive_dir / f"{session_id}_{int(time.time())}.json"
        archive_path.write_text(
            json.dumps(archived, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Append to compressed_context (multiple compressions separated by ---)
        existing = data.get("compressed_context", "").strip()
        data["compressed_context"] = (existing + "\n---\n" + summary) if existing else summary
        data["messages"] = remaining
        self._write(session_id, data)

        return len(archived), len(remaining)

    def get_compressed_context(self, session_id: str) -> str:
        return self._read(session_id).get("compressed_context", "")

    async def auto_compress_if_needed(
        self, session_id: str, llm, threshold: int = 40
    ) -> bool:
        """
        If the session has >= *threshold* messages, compress the oldest 50%.
        Uses *llm* to generate a concise summary (same logic as the manual
        /compress endpoint). Returns True if compression was performed.
        Non-fatal: any LLM failure silently skips compression.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        data = self._read(session_id)
        messages = data["messages"]

        if len(messages) < threshold:
            return False

        n = max(4, len(messages) // 2)
        to_compress = messages[:n]

        conversation = "\n".join(
            f"{m['role'].upper()}: {m.get('content', '')}" for m in to_compress
        )

        try:
            summary_llm = llm.bind(temperature=0.3)
            resp = await summary_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a helpful assistant that summarises conversations concisely. "
                            "Reply in English. Keep the summary under 500 characters."
                        )
                    ),
                    HumanMessage(
                        content=f"Please summarise the following conversation:\n\n{conversation}"
                    ),
                ]
            )
            summary = resp.content.strip()[:500]
        except Exception:
            return False  # non-fatal — skip compression this turn

        self.compress_history(session_id, summary, n)
        return True
