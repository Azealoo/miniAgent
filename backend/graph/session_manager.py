import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict

from graph.session_summary import (
    append_compressed_summary,
    generate_structured_summary,
    parse_compressed_context,
)

# Per-session locks prevent two concurrent requests from compressing the same
# session simultaneously (which would double-archive messages).
_compress_locks: dict[str, asyncio.Lock] = {}

# Only allow standard UUID v4 strings produced by uuid.uuid4().
# This blocks path traversal payloads like "../config" or "../../etc/passwd".
_SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ARCHIVE_ID_RE = re.compile(r"^\d+$")

SESSION_SCHEMA_VERSION = "session.v3"


class SessionTextBlock(TypedDict):
    type: Literal["text"]
    text: str


class SessionToolUseBlock(TypedDict, total=False):
    type: Literal["tool_use"]
    tool: str
    input: str
    run_id: str


class SessionToolResultBlock(TypedDict, total=False):
    type: Literal["tool_result"]
    tool: str
    output: str
    run_id: str
    result: dict[str, Any]


class SessionRetrievalBlock(TypedDict, total=False):
    type: Literal["retrieval"]
    query: str
    results: list[dict[str, Any]]


class SessionUsageBlock(TypedDict):
    type: Literal["usage"]
    metadata: dict[str, Any]


class SessionPlanBlock(TypedDict, total=False):
    type: Literal["plan"]
    event: Literal["created", "updated"]
    summary: str
    run_id: str
    plan: dict[str, Any]
    tool_trace: list[dict[str, Any]]


class SessionVerificationBlock(TypedDict, total=False):
    type: Literal["verification"]
    summary: str
    verdict: Literal["pass", "repair_required", "fail"]
    run_id: str
    verification: dict[str, Any]
    tool_trace: list[dict[str, Any]]


class SessionArchiveIndexEntry(TypedDict):
    archive_id: str | None
    message_count: int


SessionContentBlock = (
    SessionTextBlock
    | SessionToolUseBlock
    | SessionToolResultBlock
    | SessionRetrievalBlock
    | SessionUsageBlock
    | SessionPlanBlock
    | SessionVerificationBlock
)


def _validate_session_id(session_id: str) -> None:
    """Raise ValueError if *session_id* does not look like a UUID v4."""
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")


def _normalize_record_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _tool_block_key(tool_name: str, run_id: str | None) -> str:
    return run_id or tool_name


def _build_blocks_from_legacy_message(
    role: str,
    content: str,
    tool_calls: list[dict[str, Any]],
    retrievals: list[dict[str, Any]],
) -> list[SessionContentBlock]:
    blocks: list[SessionContentBlock] = []

    if role == "assistant":
        if retrievals:
            blocks.append(
                SessionRetrievalBlock(
                    type="retrieval",
                    results=[dict(item) for item in retrievals],
                )
            )

        for call in tool_calls:
            tool_name = call.get("tool")
            if not isinstance(tool_name, str):
                continue

            use_block: SessionToolUseBlock = {
                "type": "tool_use",
                "tool": tool_name,
                "input": call.get("input") if isinstance(call.get("input"), str) else "",
            }
            run_id = call.get("run_id")
            if isinstance(run_id, str) and run_id:
                use_block["run_id"] = run_id
            blocks.append(use_block)

            result_block: SessionToolResultBlock = {
                "type": "tool_result",
                "tool": tool_name,
                "output": call.get("output") if isinstance(call.get("output"), str) else "",
            }
            if isinstance(run_id, str) and run_id:
                result_block["run_id"] = run_id
            if isinstance(call.get("result"), dict):
                result_block["result"] = dict(call["result"])
            blocks.append(result_block)

    if content:
        blocks.append(SessionTextBlock(type="text", text=content))

    return blocks


def _normalize_blocks(value: Any) -> list[SessionContentBlock]:
    if not isinstance(value, list):
        return []

    blocks: list[SessionContentBlock] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        block_type = item.get("type")
        if block_type == "text":
            text = item.get("text")
            if isinstance(text, str):
                blocks.append(SessionTextBlock(type="text", text=text))
        elif block_type == "tool_use":
            tool_name = item.get("tool")
            if not isinstance(tool_name, str):
                continue
            block: SessionToolUseBlock = {
                "type": "tool_use",
                "tool": tool_name,
                "input": item.get("input") if isinstance(item.get("input"), str) else "",
            }
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            blocks.append(block)
        elif block_type == "tool_result":
            tool_name = item.get("tool")
            if not isinstance(tool_name, str):
                continue
            block = SessionToolResultBlock(
                type="tool_result",
                tool=tool_name,
                output=item.get("output") if isinstance(item.get("output"), str) else "",
            )
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            result = item.get("result")
            if isinstance(result, dict):
                block["result"] = dict(result)
            blocks.append(block)
        elif block_type == "retrieval":
            results = item.get("results")
            if not isinstance(results, list):
                continue
            block = SessionRetrievalBlock(
                type="retrieval",
                results=[dict(entry) for entry in results if isinstance(entry, dict)],
            )
            query = item.get("query")
            if isinstance(query, str) and query:
                block["query"] = query
            blocks.append(block)
        elif block_type == "usage":
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                blocks.append(SessionUsageBlock(type="usage", metadata=dict(metadata)))
        elif block_type == "plan":
            event = item.get("event")
            summary = item.get("summary")
            plan = item.get("plan")
            if event not in {"created", "updated"}:
                continue
            if not isinstance(summary, str) or not isinstance(plan, dict):
                continue
            block: SessionPlanBlock = {
                "type": "plan",
                "event": event,
                "summary": summary,
                "plan": dict(plan),
            }
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            tool_trace = item.get("tool_trace")
            if isinstance(tool_trace, list):
                block["tool_trace"] = [
                    dict(entry) for entry in tool_trace if isinstance(entry, dict)
                ]
            blocks.append(block)
        elif block_type == "verification":
            summary = item.get("summary")
            verdict = item.get("verdict")
            verification = item.get("verification")
            if verdict not in {"pass", "repair_required", "fail"}:
                continue
            if not isinstance(summary, str) or not isinstance(verification, dict):
                continue
            block: SessionVerificationBlock = {
                "type": "verification",
                "summary": summary,
                "verdict": verdict,
                "verification": dict(verification),
            }
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            tool_trace = item.get("tool_trace")
            if isinstance(tool_trace, list):
                block["tool_trace"] = [
                    dict(entry) for entry in tool_trace if isinstance(entry, dict)
                ]
            blocks.append(block)

    return blocks


def _derive_legacy_fields_from_blocks(
    blocks: list[SessionContentBlock],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []
    pending_tool_uses: dict[str, list[SessionToolUseBlock]] = {}

    for block in blocks:
        block_type = block["type"]

        if block_type == "text":
            text_parts.append(block["text"])
            continue

        if block_type == "tool_use":
            key = _tool_block_key(block["tool"], block.get("run_id"))
            pending_tool_uses.setdefault(key, []).append(block)
            continue

        if block_type == "tool_result":
            key = _tool_block_key(block["tool"], block.get("run_id"))
            pending = pending_tool_uses.get(key, [])
            started = pending.pop(0) if pending else None
            if not pending:
                pending_tool_uses.pop(key, None)

            call: dict[str, Any] = {
                "tool": block["tool"],
                "input": started.get("input", "") if started else "",
                "output": block.get("output", ""),
            }
            if isinstance(block.get("run_id"), str):
                call["run_id"] = block["run_id"]
            elif started and isinstance(started.get("run_id"), str):
                call["run_id"] = started["run_id"]
            if isinstance(block.get("result"), dict):
                call["result"] = dict(block["result"])
            tool_calls.append(call)
            continue

        if block_type == "retrieval":
            retrievals.extend(dict(item) for item in block["results"])
            continue

    return "".join(text_parts), tool_calls, retrievals


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(message)
    role = normalized.get("role")
    normalized["role"] = role if isinstance(role, str) else "assistant"

    content_value = normalized.get("content")
    legacy_content = content_value if isinstance(content_value, str) else ""
    tool_calls = _normalize_record_list(normalized.get("tool_calls"))
    retrievals = _normalize_record_list(normalized.get("retrievals"))
    blocks = _normalize_blocks(normalized.get("blocks"))

    if blocks:
        derived_content, derived_tool_calls, derived_retrievals = _derive_legacy_fields_from_blocks(
            blocks
        )
        normalized["content"] = legacy_content if isinstance(content_value, str) else derived_content
        if tool_calls:
            normalized["tool_calls"] = tool_calls
        elif derived_tool_calls:
            normalized["tool_calls"] = derived_tool_calls
        else:
            normalized.pop("tool_calls", None)

        if retrievals:
            normalized["retrievals"] = retrievals
        elif derived_retrievals:
            normalized["retrievals"] = derived_retrievals
        else:
            normalized.pop("retrievals", None)

        normalized["blocks"] = blocks
        return normalized

    normalized["content"] = legacy_content
    if tool_calls:
        normalized["tool_calls"] = tool_calls
    else:
        normalized.pop("tool_calls", None)

    if retrievals:
        normalized["retrievals"] = retrievals
    else:
        normalized.pop("retrievals", None)

    derived_blocks = _build_blocks_from_legacy_message(
        normalized["role"],
        normalized["content"],
        tool_calls,
        retrievals,
    )
    if derived_blocks:
        normalized["blocks"] = derived_blocks
    else:
        normalized.pop("blocks", None)

    return normalized


def _normalize_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [_normalize_message(item) for item in messages if isinstance(item, dict)]


def _empty_archive_index_entry() -> SessionArchiveIndexEntry:
    return {"archive_id": None, "message_count": 0}


def _normalize_archive_index(value: Any) -> list[SessionArchiveIndexEntry]:
    if not isinstance(value, list):
        return []

    entries: list[SessionArchiveIndexEntry] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        archive_id = item.get("archive_id")
        if not isinstance(archive_id, str) or not _ARCHIVE_ID_RE.match(archive_id):
            archive_id = None

        message_count = item.get("message_count")
        if not isinstance(message_count, int) or message_count < 0:
            message_count = 0

        entries.append({"archive_id": archive_id, "message_count": message_count})

    return entries


def _pad_archive_index(
    entries: list[SessionArchiveIndexEntry], summary_count: int
) -> list[SessionArchiveIndexEntry]:
    padded = list(entries[:summary_count])
    if len(padded) < summary_count:
        padded.extend(_empty_archive_index_entry() for _ in range(summary_count - len(padded)))
    return padded


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
        self._path(session_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
        normalized_tool_calls = _normalize_record_list(tool_calls)
        normalized_retrievals = _normalize_record_list(retrievals)
        normalized_blocks = _normalize_blocks(blocks)

        if normalized_tool_calls:
            msg["tool_calls"] = normalized_tool_calls
        if normalized_retrievals:
            msg["retrievals"] = normalized_retrievals
        if request_id:
            msg["request_id"] = request_id
        if normalized_blocks:
            msg["blocks"] = normalized_blocks
        else:
            derived_blocks = _build_blocks_from_legacy_message(
                role,
                content,
                normalized_tool_calls,
                normalized_retrievals,
            )
            if derived_blocks:
                msg["blocks"] = derived_blocks
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

    def compress_history(self, session_id: str, summary: str, n: int) -> tuple[int, int]:
        """
        Archive the first *n* messages and store *summary* in compressed_context.
        Returns (archived_count, remaining_count).
        """
        data = self._read(session_id)
        messages = self.load_session(session_id)

        archived = messages[:n]
        remaining = messages[n:]

        # Write archive file
        archive_id = str(time.time_ns())
        archive_path = self.archive_dir / f"{session_id}_{archive_id}.json"
        archive_path.write_text(
            json.dumps(archived, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Append to compressed_context (multiple compressions separated by ---)
        existing = data.get("compressed_context", "").strip()
        archive_index = _pad_archive_index(
            _normalize_archive_index(data.get("compressed_archive_index")),
            len(parse_compressed_context(existing)),
        )
        archive_index.append({"archive_id": archive_id, "message_count": len(archived)})
        data["compressed_context"] = append_compressed_summary(existing, summary)
        data["compressed_archive_index"] = archive_index
        data["messages"] = remaining
        self._write(session_id, data)

        return len(archived), len(remaining)

    def get_compressed_context(self, session_id: str) -> str:
        return self._read(session_id).get("compressed_context", "")

    def get_compressed_summaries(self, session_id: str) -> list[dict]:
        summaries = parse_compressed_context(self.get_compressed_context(session_id))
        return [
            {
                "source_format": summary.source_format,
                "legacy_summary": summary.legacy_summary,
                "decisions_and_rationale": summary.decisions_and_rationale,
                "results_register": summary.results_register,
                "evidence_register": summary.evidence_register,
                "compliance_register": summary.compliance_register,
                "open_questions_and_next_actions": summary.open_questions_and_next_actions,
            }
            for summary in summaries
        ]

    def list_archived_history_batches(self, session_id: str) -> list[dict[str, Any]]:
        _validate_session_id(session_id)
        if not self._path(session_id).exists():
            return []
        batches: list[dict[str, Any]] = []

        for path in sorted(self.archive_dir.glob(f"{session_id}_*.json")):
            archive_id = path.stem.removeprefix(f"{session_id}_")
            if not _ARCHIVE_ID_RE.match(archive_id):
                continue

            try:
                raw_messages = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            messages = _normalize_messages(raw_messages)
            batches.append(
                {
                    "archive_id": archive_id,
                    "message_count": len(messages),
                }
            )

        return batches

    def load_archived_history(self, session_id: str, archive_id: str) -> list[dict]:
        _validate_session_id(session_id)
        if not _ARCHIVE_ID_RE.match(archive_id):
            raise ValueError(f"Invalid archive_id: {archive_id!r}")
        if not self._path(session_id).exists():
            raise FileNotFoundError(self._path(session_id))

        path = self.archive_dir / f"{session_id}_{archive_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)

        raw_messages = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_messages(raw_messages)

    def _resolve_archive_index_for_summaries(
        self, session_id: str, summaries: list[dict[str, Any]], data: dict[str, Any]
    ) -> list[SessionArchiveIndexEntry]:
        summary_count = len(summaries)
        if summary_count == 0:
            return []

        stored_index = _normalize_archive_index(data.get("compressed_archive_index"))
        if stored_index:
            return _pad_archive_index(stored_index, summary_count)

        batches = self.list_archived_history_batches(session_id)
        archive_index = [
            {"archive_id": batch["archive_id"], "message_count": batch["message_count"]}
            for batch in batches
        ]
        if len(archive_index) == summary_count:
            return archive_index

        leading_legacy_count = 0
        for summary in summaries:
            if summary.get("source_format") == "legacy":
                leading_legacy_count += 1
                continue
            break

        if leading_legacy_count and len(archive_index) == summary_count - leading_legacy_count:
            return [
                *(_empty_archive_index_entry() for _ in range(leading_legacy_count)),
                *archive_index,
            ]

        return [_empty_archive_index_entry() for _ in range(summary_count)]

    def get_session_continuity(self, session_id: str) -> list[dict[str, Any]]:
        data = self._read(session_id)
        summaries = self.get_compressed_summaries(session_id)
        archive_index = self._resolve_archive_index_for_summaries(session_id, summaries, data)
        continuity: list[dict[str, Any]] = []

        for summary, archive in zip(summaries, archive_index):
            continuity.append(
                {
                    **summary,
                    "archive_id": archive["archive_id"],
                    "archived_message_count": archive["message_count"],
                }
            )

        return continuity

    async def auto_compress_if_needed(
        self, session_id: str, llm, threshold: int = 40
    ) -> bool:
        """
        If the session has >= *threshold* messages, compress the oldest 50%.
        Uses *llm* to generate a concise summary (same logic as the manual
        /compress endpoint). Returns True if compression was performed.
        Non-fatal: any LLM failure silently skips compression.

        A per-session asyncio.Lock prevents concurrent requests from compressing
        the same session simultaneously (which would double-archive messages).
        """
        async with self.get_or_create_compress_lock(session_id):
            return await self._do_compress_if_needed(session_id, llm, threshold)

    async def _do_compress_if_needed(
        self, session_id: str, llm, threshold: int
    ) -> bool:
        """Inner compress logic — must be called with the session lock held."""
        data = self._read(session_id)
        messages = self.load_session(session_id)

        if len(messages) < threshold:
            return False

        n = max(4, len(messages) // 2)
        to_compress = messages[:n]

        try:
            summary = await generate_structured_summary(to_compress, llm)
        except Exception:
            return False  # non-fatal — skip compression this turn

        self.compress_history(session_id, summary, n)
        return True
