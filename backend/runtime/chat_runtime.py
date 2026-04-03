from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from runtime.query_engine import QueryEngine, QueryTurnInput
from runtime.turn_ledger import TurnResult
from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext

@dataclass(frozen=True)
class ChatStreamInput:
    message: str
    session_id: str


class ChatRuntime:
    def __init__(self, agent_manager) -> None:
        self.agent_manager = agent_manager

    async def stream_turn(self, request: ChatStreamInput) -> AsyncGenerator[str, None]:
        session_manager = self.agent_manager.session_manager
        assert session_manager is not None

        await session_manager.auto_compress_if_needed(
            request.session_id,
            self.agent_manager.llm,
        )
        history = session_manager.load_session_for_agent(request.session_id)

        request_id = str(uuid.uuid4())
        event_index = 0

        pending_tools: dict[str, dict[str, str]] = {}
        user_msg_saved = False
        policy_context = ToolPolicyExecutionContext(session_id=request.session_id)

        def _sse(payload: dict[str, Any]) -> str:
            nonlocal event_index
            payload_to_emit = dict(payload)
            event_index += 1
            payload_to_emit.setdefault("request_id", request_id)
            payload_to_emit.setdefault("event_index", event_index)
            return f"data: {json.dumps(payload_to_emit, ensure_ascii=False)}\n\n"

        def _attach_policy_payload(
            payload: dict[str, Any],
            result: dict[str, Any] | None,
        ) -> dict[str, Any]:
            if isinstance(result, dict):
                metadata = result.get("metadata")
                if isinstance(metadata, dict):
                    policy = metadata.get("policy")
                    if isinstance(policy, dict):
                        payload["policy"] = policy
            return payload

        def _emit_tool_start(
            tool_name: str,
            tool_input: str,
            run_id: str,
            *,
            extra_payload: dict[str, Any] | None = None,
        ) -> str:
            pending_tools[run_id] = {"tool": tool_name, "input": tool_input}
            payload: dict[str, Any] = {
                "type": "tool_start",
                "tool": tool_name,
                "input": tool_input,
                "run_id": run_id,
            }
            if extra_payload:
                payload.update(extra_payload)
            return _sse(payload)

        def _emit_tool_end(
            tool_name: str,
            run_id: str,
            output: str,
            *,
            result: dict[str, Any] | None = None,
            extra_payload: dict[str, Any] | None = None,
        ) -> str:
            pending_tools.pop(run_id, None)
            payload: dict[str, Any] = {
                "type": "tool_end",
                "tool": tool_name,
                "output": output,
                "run_id": run_id,
            }
            if result is not None:
                payload["result"] = result
            if extra_payload:
                payload.update(extra_payload)
            return _sse(_attach_policy_payload(payload, result))

        def _save_user_message() -> None:
            nonlocal user_msg_saved
            if user_msg_saved:
                return
            session_manager.save_message(
                request.session_id,
                "user",
                request.message,
                request_id=request_id,
            )
            user_msg_saved = True

        async def _finalize_turn(turn_result: TurnResult) -> list[str]:
            _save_user_message()
            for seg in turn_result.segments:
                session_manager.save_message(
                    request.session_id,
                    "assistant",
                    seg.content,
                    seg.tool_calls or None,
                    seg.retrievals or None,
                    request_id=request_id,
                    blocks=seg.blocks or None,
                )

            payloads: list[str] = []
            payloads.append(
                _sse(
                    {
                        "type": "done",
                        "content": turn_result.final_content,
                        "session_id": request.session_id,
                    }
                )
            )
            return payloads

        async def _consume_query_events(
            events: AsyncGenerator[dict[str, Any], None],
        ) -> AsyncGenerator[str, None]:
            async for event in events:
                event_type = event["type"]

                if event_type == "persist_user_message":
                    _save_user_message()
                    continue

                if event_type == "retrieval":
                    yield _sse(
                        {
                            "type": "retrieval",
                            "query": event["query"],
                            "results": event["results"],
                        }
                    )
                    continue

                if event_type == "token":
                    yield _sse({"type": "token", "content": event["content"]})
                    continue

                if event_type == "tool_start":
                    run_id = event.get("run_id", event["tool"])
                    extra_payload = {
                        key: value
                        for key, value in event.items()
                        if key not in {"type", "tool", "input", "run_id"}
                    }
                    yield _emit_tool_start(
                        event["tool"],
                        event["input"],
                        run_id,
                        extra_payload=extra_payload or None,
                    )
                    continue

                if event_type == "tool_end":
                    run_id = event.get("run_id", event["tool"])
                    extra_payload = {
                        key: value
                        for key, value in event.items()
                        if key not in {"type", "tool", "output", "run_id", "result"}
                    }
                    yield _emit_tool_end(
                        event["tool"],
                        run_id,
                        event["output"],
                        result=event.get("result"),
                        extra_payload=extra_payload or None,
                    )
                    continue

                if event_type in {"plan_created", "plan_updated", "verification_result"}:
                    yield _sse(event)
                    continue

                if event_type == "new_response":
                    yield _sse({"type": "new_response"})
                    continue

                if event_type == "done":
                    turn_result = event.get("turn_result")
                    if not isinstance(turn_result, TurnResult):
                        raise RuntimeError("runtime done event missing turn_result")
                    for payload in await _finalize_turn(turn_result):
                        yield payload
                    return

                if event_type == "error":
                    _save_user_message()
                    yield _sse({"type": "error", "error": event["error"]})
                    return

        with tool_policy_context(policy_context):
            try:
                turn = QueryTurnInput(
                    message=request.message,
                    history=list(history),
                    policy_context=policy_context,
                )
                query_engine = QueryEngine(self.agent_manager)
                async for payload in _consume_query_events(query_engine.run_turn(turn)):
                    yield payload
            except Exception as exc:
                _save_user_message()
                yield _sse({"type": "error", "error": str(exc)})
