from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TurnSegment:
    content: str
    blocks: list[dict[str, Any]]


@dataclass(frozen=True)
class TurnResult:
    segments: list[TurnSegment]
    turn_status: str
    final_content: str


class TurnLedger:
    """Accumulates streamed runtime events into persisted assistant turn segments.

    Blocks are the canonical on-disk shape — legacy ``tool_calls``/``retrievals``
    arrays are derived at read boundaries by the session manager.

    When constructed with ``session_manager``/``session_id``/``request_id``/
    ``user_message`` the ledger also owns finalize-time persistence: the user
    message is written once on demand and assistant segments are written from
    the ``TurnResult`` produced by ``finalize``.
    """

    def __init__(
        self,
        *,
        session_manager: Any = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        user_message: Optional[str] = None,
    ) -> None:
        self._segments: list[TurnSegment] = []
        self._current_content: list[str] = []
        self._current_blocks: list[dict[str, Any]] = []
        self._pending_tools: dict[str, dict[str, Any]] = {}
        self._session_manager = session_manager
        self._session_id = session_id
        self._request_id = request_id
        self._user_message = user_message
        self._user_message_saved = False

    def consume(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = event.get("type")

        if event_type == "retrieval":
            query = event.get("query")
            results = event.get("results")
            if isinstance(query, str) and isinstance(results, list):
                self._append_retrieval(
                    query,
                    [dict(item) for item in results if isinstance(item, dict)],
                )
            return [event]

        if event_type == "token":
            content = event.get("content")
            if not isinstance(content, str):
                return []
            self._append_text(content)
            return [event]

        if event_type == "tool_start":
            tool_name = event.get("tool")
            run_id = event.get("run_id", tool_name)
            if isinstance(tool_name, str) and isinstance(run_id, str) and run_id:
                self._pending_tools[run_id] = {
                    "tool": tool_name,
                    "input": event.get("input", ""),
                }
            return [event]

        if event_type == "tool_end":
            tool_name = event.get("tool")
            run_id = event.get("run_id", tool_name)
            if isinstance(tool_name, str) and isinstance(run_id, str):
                self._append_tool_call(
                    tool_name,
                    run_id,
                    event.get("output"),
                    event.get("result"),
                )
            return [event]

        if event_type == "tool_awaiting_approval":
            tool_name = event.get("tool")
            run_id = event.get("run_id", tool_name)
            if isinstance(tool_name, str) and isinstance(run_id, str) and run_id:
                self._append_approval_gate(event, tool_name=tool_name, run_id=run_id)
            return [event]

        if event_type in {"plan_created", "plan_updated"}:
            self._append_plan_event(event)
            return [event]

        if event_type == "verification_result":
            self._append_verification_event(event)
            return [event]

        if event_type == "warning":
            self._append_warning_event(event)
            return [event]

        if event_type == "new_response":
            self._flush_segment()
            return [event]

        return [event]

    def finalize(self, *, turn_status: str) -> TurnResult:
        self._flush_segment()
        final_content = " ".join(segment.content for segment in self._segments if segment.content)

        return TurnResult(
            segments=list(self._segments),
            turn_status=turn_status,
            final_content=final_content,
        )

    def persist_user_message(self) -> None:
        """Marker call — the user message is persisted by :meth:`persist_segments`.

        Kept for call-site symmetry with the done/error/cancel flows. Writing
        the user message here (as an earlier implementation did) would split
        a turn across two advisory-flock scopes and let cross-process readers
        see a partially-committed state (user message on disk but no
        assistant reply yet). All persistence goes through
        :meth:`persist_segments`, which writes the user message and every
        assistant segment in one batched read-modify-write.
        """
        return

    def persist_segments(self, turn_result: TurnResult) -> None:
        """Write the user message + assistant segments in one atomic batch.

        The batch goes through ``SessionStore.save_messages_batch`` which
        takes the per-session advisory flock exactly once, so cross-process
        readers never observe a mid-turn state (e.g. user message written
        but assistant reply missing, or only the first of multiple segments
        persisted).
        """
        self._flush_to_session_store(turn_result=turn_result)

    def _flush_to_session_store(self, *, turn_result: TurnResult | None) -> None:
        if self._session_manager is None or self._session_id is None:
            return

        pending: list[dict[str, Any]] = []

        if self._user_message is not None and not self._user_message_saved:
            user_record: dict[str, Any] = {
                "role": "user",
                "content": self._user_message,
            }
            if self._request_id:
                user_record["request_id"] = self._request_id
            pending.append(user_record)

        segments = turn_result.segments if turn_result is not None else []
        for segment in segments:
            assistant_record: dict[str, Any] = {
                "role": "assistant",
                "content": segment.content,
            }
            if self._request_id:
                assistant_record["request_id"] = self._request_id
            if segment.blocks:
                assistant_record["blocks"] = segment.blocks
            pending.append(assistant_record)

        if not pending:
            return

        self._session_manager.save_messages_batch(self._session_id, pending)
        self._user_message_saved = True

    def _flush_segment(self) -> None:
        content = "".join(self._current_content)
        if content or self._current_blocks:
            self._segments.append(
                TurnSegment(
                    content=content,
                    blocks=[dict(block) for block in self._current_blocks],
                )
            )

        self._current_content.clear()
        self._current_blocks.clear()

    def _append_text(self, text: str) -> None:
        if not text:
            return
        self._current_content.append(text)
        if self._current_blocks and self._current_blocks[-1].get("type") == "text":
            self._current_blocks[-1]["text"] += text
        else:
            self._current_blocks.append({"type": "text", "text": text})

    def _append_tool_call(
        self,
        tool_name: str,
        run_id: str,
        output: Any,
        result: Any,
    ) -> None:
        started = self._pending_tools.pop(run_id, {"tool": tool_name, "input": ""})
        use_block = {
            "type": "tool_use",
            "tool": started["tool"],
            "input": started.get("input", ""),
            "run_id": run_id,
        }
        self._current_blocks.append(use_block)

        result_block = {
            "type": "tool_result",
            "tool": started["tool"],
            "output": output if isinstance(output, str) else "",
            "run_id": run_id,
        }
        if result is not None:
            result_block["result"] = result
        self._current_blocks.append(result_block)

    def _append_retrieval(self, query: str, results: list[dict[str, Any]]) -> None:
        self._current_blocks.append(
            {
                "type": "retrieval",
                "query": query,
                "results": [dict(item) for item in results],
            }
        )

    def _append_plan_event(self, event: dict[str, Any]) -> None:
        block = {
            "type": "plan",
            "event": "updated" if event.get("type") == "plan_updated" else "created",
            "summary": event.get("summary", ""),
            "plan": dict(event.get("plan", {})) if isinstance(event.get("plan"), dict) else {},
        }
        run_id = event.get("run_id")
        if isinstance(run_id, str) and run_id:
            block["run_id"] = run_id
        tool_trace = event.get("tool_trace")
        if isinstance(tool_trace, list):
            block["tool_trace"] = [
                dict(item) for item in tool_trace if isinstance(item, dict)
            ]
        self._current_blocks.append(block)

    def _append_approval_gate(
        self,
        event: dict[str, Any],
        *,
        tool_name: str,
        run_id: str,
    ) -> None:
        started = self._pending_tools.pop(run_id, None)
        block: dict[str, Any] = {
            "type": "approval_gate",
            "tool": tool_name,
            "input": (
                started.get("input", "") if isinstance(started, dict) else event.get("input", "")
            ),
            "run_id": run_id,
            "reason": event.get("reason", "requires_approval"),
            "message": event.get("message", ""),
        }
        result = event.get("result")
        if result is not None:
            block["result"] = result
        policy = event.get("policy")
        if isinstance(policy, dict):
            block["policy"] = dict(policy)
        self._current_blocks.append(block)

    def _append_warning_event(self, event: dict[str, Any]) -> None:
        block: dict[str, Any] = {
            "type": "warning",
            "kind": event.get("kind", "warning"),
            "message": event.get("message", ""),
        }
        for field in ("missing", "cited", "included"):
            value = event.get(field)
            if isinstance(value, list):
                block[field] = [str(item) for item in value if isinstance(item, str)]
        review_path = event.get("review_path")
        if isinstance(review_path, str) and review_path:
            block["review_path"] = review_path
        self._current_blocks.append(block)

    def _append_verification_event(self, event: dict[str, Any]) -> None:
        block = {
            "type": "verification",
            "summary": event.get("summary", ""),
            "verdict": event.get("verdict", "fail"),
            "verification": (
                dict(event.get("verification", {}))
                if isinstance(event.get("verification"), dict)
                else {}
            ),
        }
        run_id = event.get("run_id")
        if isinstance(run_id, str) and run_id:
            block["run_id"] = run_id
        tool_trace = event.get("tool_trace")
        if isinstance(tool_trace, list):
            block["tool_trace"] = [
                dict(item) for item in tool_trace if isinstance(item, dict)
            ]
        self._current_blocks.append(block)
