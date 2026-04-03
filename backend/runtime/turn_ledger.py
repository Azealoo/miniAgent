from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TurnSegment:
    content: str
    tool_calls: list[dict[str, Any]]
    retrievals: list[dict[str, Any]]
    blocks: list[dict[str, Any]]


@dataclass(frozen=True)
class TurnResult:
    segments: list[TurnSegment]
    turn_status: str
    final_content: str


class TurnLedger:
    """Accumulates streamed runtime events into persisted assistant turn segments."""

    def __init__(self) -> None:
        self._segments: list[TurnSegment] = []
        self._current_content: list[str] = []
        self._current_tool_calls: list[dict[str, Any]] = []
        self._current_retrievals: list[dict[str, Any]] = []
        self._current_blocks: list[dict[str, Any]] = []
        self._pending_tools: dict[str, dict[str, Any]] = {}

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

        if event_type in {"plan_created", "plan_updated"}:
            self._append_plan_event(event)
            return [event]

        if event_type == "verification_result":
            self._append_verification_event(event)
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

    def _flush_segment(self) -> None:
        content = "".join(self._current_content)
        if (
            content
            or self._current_tool_calls
            or self._current_retrievals
            or self._current_blocks
        ):
            self._segments.append(
                TurnSegment(
                    content=content,
                    tool_calls=[dict(call) for call in self._current_tool_calls],
                    retrievals=[dict(item) for item in self._current_retrievals],
                    blocks=[dict(block) for block in self._current_blocks],
                )
            )

        self._current_content.clear()
        self._current_tool_calls.clear()
        self._current_retrievals.clear()
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
        call = {
            "tool": started["tool"],
            "input": started.get("input", ""),
            "output": output if isinstance(output, str) else "",
            "run_id": run_id,
        }
        if result is not None:
            call["result"] = result
        self._current_tool_calls.append(call)

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
        self._current_retrievals.extend(results)
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
