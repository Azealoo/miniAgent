"""Minimal agent runtime kernel.

``CoreRuntime`` composes four primitives -- ``session_messages``,
``api_client``, ``tool_executor``, ``permission_policy`` -- into the
classic *message -> tool_call -> tool_result -> message* loop. Everything
BioAPEX-specific (memory indexing, skills, hooks, artifacts, workflows,
TurnLedger, compaction, repair retry, METRICS...) layers on top by wrapping
these primitives at construction time.

The kernel has no imports from ``memory``, ``skills``, ``artifacts``, or
``workflows`` so its unit tests run with trivial fakes and no on-disk state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Protocol

__all__ = [
    "ApiClient",
    "CoreRuntime",
    "PermissionDecision",
    "PermissionPolicy",
    "PermissionRuling",
    "ToolCall",
    "ToolExecutor",
    "ToolResult",
]


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class ToolCall:
    run_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    run_id: str
    name: str
    content: Any = None
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class PermissionRuling:
    decision: PermissionDecision
    reason: str | None = None

    @classmethod
    def allow(cls) -> "PermissionRuling":
        return cls(PermissionDecision.ALLOW)

    @classmethod
    def deny(cls, reason: str) -> "PermissionRuling":
        return cls(PermissionDecision.DENY, reason)


class ApiClient(Protocol):
    """Streams model events for a conversation.

    Recognised events: ``token``, ``tool_call``, ``message``, ``done``.
    Any other event is passed through to the caller verbatim.
    """

    def stream(
        self, messages: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]: ...


class ToolExecutor(Protocol):
    async def execute(self, call: ToolCall) -> ToolResult: ...


class PermissionPolicy(Protocol):
    def check(self, call: ToolCall) -> PermissionRuling: ...


@dataclass
class CoreRuntime:
    session_messages: list[dict[str, Any]]
    api_client: ApiClient
    tool_executor: ToolExecutor
    permission_policy: PermissionPolicy
    max_steps: int = 8

    async def run(
        self, user_message: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Drive a user turn to completion.

        Appends ``user_message`` if given, then loops: stream ``api_client``,
        capture assistant text + tool calls, append the assistant message,
        run each tool call through ``permission_policy`` + ``tool_executor``,
        append its result, repeat until the model emits no tool calls or
        ``max_steps`` is reached. Yields every upstream event plus the
        ``tool_result`` / ``tool_denied`` events it produces itself.
        """
        if user_message is not None:
            self.session_messages.append(
                {"role": "user", "content": user_message}
            )

        for _ in range(self.max_steps):
            pending: list[ToolCall] = []
            assistant_text: list[str] = []
            assistant_message: dict[str, Any] | None = None
            stop_event: dict[str, Any] | None = None

            async for event in self.api_client.stream(self.session_messages):
                kind = event.get("type")
                if kind == "token":
                    content = event.get("content")
                    if isinstance(content, str):
                        assistant_text.append(content)
                    yield event
                elif kind == "tool_call":
                    name = event.get("name")
                    if isinstance(name, str):
                        pending.append(
                            ToolCall(
                                run_id=str(event.get("run_id") or name),
                                name=name,
                                arguments=dict(event.get("arguments") or {}),
                            )
                        )
                    yield event
                elif kind == "message":
                    assistant_message = dict(event)
                    yield event
                elif kind == "done":
                    stop_event = dict(event)
                    yield event
                    break
                else:
                    yield event

            self.session_messages.append(
                assistant_message
                or {"role": "assistant", "content": "".join(assistant_text)}
            )

            if not pending:
                if stop_event is None:
                    yield {"type": "done", "stop_reason": "stop"}
                return

            for call in pending:
                ruling = self.permission_policy.check(call)
                if ruling.decision is PermissionDecision.DENY:
                    reason = ruling.reason or "permission policy denied this tool"
                    yield {
                        "type": "tool_denied",
                        "run_id": call.run_id,
                        "name": call.name,
                        "reason": reason,
                    }
                    self.session_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.run_id,
                            "name": call.name,
                            "content": f"denied: {reason}",
                        }
                    )
                    continue
                result = await self.tool_executor.execute(call)
                payload: dict[str, Any] = {
                    "type": "tool_result",
                    "run_id": result.run_id,
                    "name": result.name,
                    "content": result.content,
                }
                if result.error is not None:
                    payload["error"] = result.error
                yield payload
                self.session_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.run_id,
                        "name": result.name,
                        "content": result.error
                        if result.is_error
                        else result.content,
                    }
                )

        yield {"type": "done", "stop_reason": "max_steps"}
