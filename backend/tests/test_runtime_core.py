"""Unit tests for the minimal ``runtime.core`` kernel.

These tests construct a ``CoreRuntime`` purely from in-memory fakes. No
imports from ``memory``, ``skills``, ``artifacts``, or ``workflows`` are
required, which is the acceptance criterion from issue #92.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from runtime.core import (
    CoreRuntime,
    PermissionDecision,
    PermissionRuling,
    ToolCall,
    ToolResult,
)


class _ScriptedApiClient:
    """Replays a pre-recorded list of transcripts, one per ``stream`` call."""

    def __init__(self, transcripts: list[list[dict[str, Any]]]) -> None:
        self._transcripts = list(transcripts)
        self.calls: list[list[dict[str, Any]]] = []

    async def stream(
        self, messages: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append([dict(m) for m in messages])
        transcript = self._transcripts.pop(0) if self._transcripts else []
        for event in transcript:
            yield dict(event)


class _RecordingExecutor:
    def __init__(self, results: dict[str, ToolResult]) -> None:
        self._results = results
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        try:
            return self._results[call.run_id]
        except KeyError:
            return ToolResult(
                run_id=call.run_id,
                name=call.name,
                error=f"no fake for {call.run_id}",
            )


class _AllowAllPolicy:
    def check(self, call: ToolCall) -> PermissionRuling:  # noqa: ARG002
        return PermissionRuling.allow()


class _DenyPolicy:
    def __init__(self, deny_names: set[str], reason: str = "denied by test") -> None:
        self._deny_names = deny_names
        self._reason = reason

    def check(self, call: ToolCall) -> PermissionRuling:
        if call.name in self._deny_names:
            return PermissionRuling.deny(self._reason)
        return PermissionRuling.allow()


def _runtime(
    transcripts: list[list[dict[str, Any]]],
    *,
    messages: list[dict[str, Any]] | None = None,
    executor_results: dict[str, ToolResult] | None = None,
    policy: Any | None = None,
    max_steps: int = 8,
) -> tuple[CoreRuntime, _ScriptedApiClient, _RecordingExecutor]:
    api = _ScriptedApiClient(transcripts)
    executor = _RecordingExecutor(executor_results or {})
    runtime = CoreRuntime(
        session_messages=messages if messages is not None else [],
        api_client=api,
        tool_executor=executor,
        permission_policy=policy or _AllowAllPolicy(),
        max_steps=max_steps,
    )
    return runtime, api, executor


@pytest.mark.asyncio
async def test_plain_text_turn_appends_user_and_assistant_messages():
    runtime, api, executor = _runtime(
        [
            [
                {"type": "token", "content": "hi "},
                {"type": "token", "content": "there"},
                {"type": "done", "stop_reason": "stop"},
            ]
        ]
    )

    events = [event async for event in runtime.run("hello")]

    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert runtime.session_messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    assert executor.calls == []
    assert api.calls == [[{"role": "user", "content": "hello"}]]


@pytest.mark.asyncio
async def test_tool_call_round_trip_feeds_result_back_into_next_step():
    runtime, api, executor = _runtime(
        [
            [
                {
                    "type": "tool_call",
                    "run_id": "r1",
                    "name": "fetch",
                    "arguments": {"q": "x"},
                },
                {"type": "done", "stop_reason": "tool_use"},
            ],
            [
                {"type": "token", "content": "done"},
                {"type": "done", "stop_reason": "stop"},
            ],
        ],
        executor_results={
            "r1": ToolResult(run_id="r1", name="fetch", content="ok"),
        },
    )

    events = [event async for event in runtime.run("go")]

    assert [e["type"] for e in events] == [
        "tool_call",
        "done",
        "tool_result",
        "token",
        "done",
    ]
    assert executor.calls == [
        ToolCall(run_id="r1", name="fetch", arguments={"q": "x"})
    ]
    # Second API call should see the tool result message we appended.
    assert api.calls[1][-1] == {
        "role": "tool",
        "tool_call_id": "r1",
        "name": "fetch",
        "content": "ok",
    }


@pytest.mark.asyncio
async def test_permission_deny_skips_executor_and_feeds_denial_back():
    runtime, _api, executor = _runtime(
        [
            [
                {
                    "type": "tool_call",
                    "run_id": "r1",
                    "name": "rm_rf",
                    "arguments": {},
                },
                {"type": "done", "stop_reason": "tool_use"},
            ],
            [
                {"type": "token", "content": "ok"},
                {"type": "done", "stop_reason": "stop"},
            ],
        ],
        policy=_DenyPolicy({"rm_rf"}, reason="destructive"),
    )

    events = [event async for event in runtime.run("go")]

    denials = [e for e in events if e["type"] == "tool_denied"]
    assert denials == [
        {
            "type": "tool_denied",
            "run_id": "r1",
            "name": "rm_rf",
            "reason": "destructive",
        }
    ]
    assert executor.calls == []
    tool_msg = next(
        m for m in runtime.session_messages if m.get("role") == "tool"
    )
    assert tool_msg["content"] == "denied: destructive"


@pytest.mark.asyncio
async def test_executor_error_is_surfaced_and_fed_back_as_tool_message():
    runtime, _api, _executor = _runtime(
        [
            [
                {
                    "type": "tool_call",
                    "run_id": "r1",
                    "name": "fetch",
                    "arguments": {},
                },
                {"type": "done", "stop_reason": "tool_use"},
            ],
            [
                {"type": "token", "content": "bye"},
                {"type": "done", "stop_reason": "stop"},
            ],
        ],
        executor_results={
            "r1": ToolResult(run_id="r1", name="fetch", error="boom"),
        },
    )

    events = [event async for event in runtime.run("go")]

    result_event = next(e for e in events if e["type"] == "tool_result")
    assert result_event["error"] == "boom"
    tool_msg = next(
        m for m in runtime.session_messages if m.get("role") == "tool"
    )
    assert tool_msg["content"] == "boom"


@pytest.mark.asyncio
async def test_max_steps_bounds_the_loop_and_emits_terminal_done():
    runtime, _api, _executor = _runtime(
        [
            [
                {
                    "type": "tool_call",
                    "run_id": f"r{i}",
                    "name": "loop",
                    "arguments": {},
                },
                {"type": "done", "stop_reason": "tool_use"},
            ]
            for i in range(10)
        ],
        executor_results={
            f"r{i}": ToolResult(run_id=f"r{i}", name="loop", content="ok")
            for i in range(10)
        },
        max_steps=2,
    )

    events = [event async for event in runtime.run("go")]

    terminal = events[-1]
    assert terminal == {"type": "done", "stop_reason": "max_steps"}


@pytest.mark.asyncio
async def test_passthrough_event_is_yielded_unchanged():
    runtime, _api, _executor = _runtime(
        [
            [
                {"type": "custom", "payload": {"k": "v"}},
                {"type": "done", "stop_reason": "stop"},
            ]
        ]
    )

    events = [event async for event in runtime.run("go")]

    assert {"type": "custom", "payload": {"k": "v"}} in events


def test_permission_ruling_helpers():
    allow = PermissionRuling.allow()
    deny = PermissionRuling.deny("nope")
    assert allow.decision is PermissionDecision.ALLOW
    assert deny.decision is PermissionDecision.DENY
    assert deny.reason == "nope"


def test_core_module_has_no_optional_subsystem_imports():
    """Acceptance: ``runtime.core`` must not pull in memory/skills/artifacts.

    The kernel should be independently unit-testable. This guards against a
    future edit that casually imports one of those subsystems at module
    load.
    """
    import runtime.core as core_module

    source = core_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    for forbidden in ("memory", "skills", "artifacts", "workflows"):
        assert f"import {forbidden}" not in text
        assert f"from {forbidden}" not in text
