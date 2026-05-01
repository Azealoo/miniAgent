"""Cancellation tests for the AsyncGenerator core agent loop.

Issue #78: client disconnect must propagate ``CancelledError`` to in-flight
tools (not be swallowed at any layer) and the runtime must persist whatever
the agent has already produced before the cancellation unwinds.

These tests cover three scopes:
  * the policy-wrapped tool layer (``tools.policy_wrappers.PolicyWrappedTool._arun``)
  * the SSE adapter (``runtime.query_engine.QueryEngine.stream_turn_sse``)
  * the harness loop (``runtime.query_engine.QueryEngine.run_harness_turn``)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest
from langchain_core.tools import BaseTool

sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime.query_engine import QueryEngine, QueryTurnInput
from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry


# --------------------------------------------------------------------------- #
# Tool-layer cancellation
# --------------------------------------------------------------------------- #


class _CancellableTool(BaseTool):
    name: str = "cancellable_tool"
    description: str = "Awaits forever until cancelled."
    response_format: str = "content_and_artifact"
    started: asyncio.Event = None  # type: ignore[assignment]

    def _run(self, *args, **kwargs):  # pragma: no cover - async-only test
        raise NotImplementedError

    async def _arun(self, *args, **kwargs):
        if self.started is not None:
            self.started.set()
        # Block on a future that will never resolve so the only way out is
        # CancelledError thrown in by the consumer.
        await asyncio.Future()


def _bare_manifest(name: str = "cancellable_tool") -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="Awaits forever until cancelled.",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_runtime_cancellation",
        read_only=True,
        destructive=False,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        tool_validates_input=False,
        activity_summary_hint="inspect",
        result_summary_hint="result",
    )


@pytest.mark.asyncio
async def test_async_tool_cancellation_is_not_converted_to_error_envelope():
    """An ``asyncio.CancelledError`` raised inside the wrapped tool must
    propagate verbatim, not be downgraded to an ``execution_failure`` envelope.

    If the wrapper swallowed the cancellation, the agent loop would keep
    running on a half-cancelled task tree and the SSE consumer would never
    see the disconnect actually unwind.
    """
    started = asyncio.Event()
    inner = _CancellableTool(started=started)
    wrapper = PolicyWrappedTool(
        name=inner.name,
        description=inner.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=inner,
        manifest=_bare_manifest(inner.name),
    )

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-1",
            request_id="request-1",
            allowed_access_scope="execution",
        )
    ):
        task = asyncio.create_task(wrapper._arun())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# --------------------------------------------------------------------------- #
# SSE-layer cancellation
# --------------------------------------------------------------------------- #


class _RecordingSessionManager:
    """Minimal SessionManager stand-in that records save_message calls."""

    def __init__(self, history: list[dict] | None = None) -> None:
        self._history = list(history or [])
        self.saved: list[dict[str, Any]] = []
        self.batches: list[list[dict[str, Any]]] = []

    async def auto_compress_if_needed(self, session_id: str, llm) -> None:
        return None

    def load_session_for_agent(self, session_id: str) -> list[dict]:
        return list(self._history)

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls=None,
        retrievals=None,
        request_id: str | None = None,
        blocks=None,
    ) -> None:
        self.saved.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "request_id": request_id,
                "blocks": list(blocks) if blocks else None,
            }
        )

    def save_messages_batch(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        batch: list[dict[str, Any]] = []
        for msg in messages:
            record = {
                "session_id": session_id,
                "role": msg["role"],
                "content": msg.get("content", ""),
                "request_id": msg.get("request_id"),
                "blocks": list(msg["blocks"]) if msg.get("blocks") else None,
            }
            self.saved.append(record)
            batch.append(record)
        self.batches.append(batch)


class _PartialThenStallAgentManager:
    """Yields one token then awaits forever, simulating an in-flight tool."""

    def __init__(self, session_manager) -> None:
        self.session_manager = session_manager
        self.base_dir = None  # skip approval-store touches in stream_turn_sse
        self.llm = None
        self.streaming_started = asyncio.Event()
        self.streaming_cancelled = asyncio.Event()

    async def astream(
        self, message: str, history: list[dict]
    ) -> AsyncGenerator[dict, None]:
        try:
            yield {"type": "token", "content": "partial draft "}
            self.streaming_started.set()
            await asyncio.Future()
        except asyncio.CancelledError:
            self.streaming_cancelled.set()
            raise


@pytest.mark.asyncio
async def test_stream_turn_sse_persists_partial_state_on_client_disconnect(
    monkeypatch,
):
    """Cancelling the task that's driving the SSE generator (which is what
    Starlette does on client disconnect) must:
      * propagate ``CancelledError`` into the agent's astream loop
      * persist the user message exactly once
      * persist the partial assistant segment so the next turn picks up
        from a consistent on-disk state
      * NOT consume pending approvals (the turn is retriable)
    """
    # ``stream_turn_sse`` imports ``maybe_compact_turn_boundary`` lazily, so
    # patch it at its source module rather than on ``runtime.query_engine``.
    monkeypatch.setattr(
        "runtime.compaction.maybe_compact_turn_boundary",
        lambda *args, **kwargs: _none_async(),
    )

    session_manager = _RecordingSessionManager(
        history=[{"role": "system", "content": "ctx"}]
    )
    agent_manager = _PartialThenStallAgentManager(session_manager)
    engine = QueryEngine(agent_manager)

    received_first_token = asyncio.Event()
    received: list[str] = []

    async def _drive_stream() -> None:
        async for chunk in engine.stream_turn_sse(
            message="hello",
            session_id="session-cancel-1",
        ):
            received.append(chunk)
            received_first_token.set()

    task = asyncio.create_task(_drive_stream())
    await received_first_token.wait()
    await agent_manager.streaming_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert any('"type": "token"' in chunk for chunk in received), (
        "the first token must reach the consumer before the cancel arrives"
    )
    assert agent_manager.streaming_cancelled.is_set(), (
        "CancelledError must reach the in-flight agent astream so its tool "
        "tasks can unwind at their next await point."
    )

    user_saves = [
        record for record in session_manager.saved if record["role"] == "user"
    ]
    assert len(user_saves) == 1, "user message must be persisted exactly once"
    assert user_saves[0]["content"] == "hello"

    assistant_saves = [
        record for record in session_manager.saved if record["role"] == "assistant"
    ]
    assert assistant_saves, "partial assistant segment must be persisted on cancel"
    assert any("partial draft" in record["content"] for record in assistant_saves), (
        "the streamed token captured before cancellation must be preserved"
    )


async def _none_async():
    return None


# --------------------------------------------------------------------------- #
# Harness-loop cancellation
# --------------------------------------------------------------------------- #


class _StallingAgentManager:
    def __init__(self) -> None:
        self.base_dir = None
        self.streaming_started = asyncio.Event()
        self.streaming_cancelled = asyncio.Event()

    async def astream(
        self, message: str, history: list[dict]
    ) -> AsyncGenerator[dict, None]:
        try:
            yield {
                "type": "tool_start",
                "tool": "long_running_tool",
                "input": "",
                "run_id": "run-1",
            }
            self.streaming_started.set()
            await asyncio.Future()
        except asyncio.CancelledError:
            self.streaming_cancelled.set()
            raise


@pytest.mark.asyncio
async def test_run_harness_turn_propagates_cancelled_error_to_inflight_tool():
    """``run_harness_turn`` must not catch ``CancelledError``: the cancel
    has to reach the agent's astream so any awaited tool is woken up with
    ``CancelledError`` at its next await point. Reproduces what Starlette
    does on client disconnect by cancelling the consumer task while the
    inner agent is parked on an awaited future.
    """
    agent_manager = _StallingAgentManager()
    engine = QueryEngine(agent_manager)
    turn = QueryTurnInput(message="hello", history=[])

    async def _drain() -> None:
        async for _event in engine.run_harness_turn(turn):
            pass

    consumer = asyncio.create_task(_drain())
    await agent_manager.streaming_started.wait()
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert agent_manager.streaming_cancelled.is_set(), (
        "cancellation must be delivered into the in-flight agent astream"
    )


# --------------------------------------------------------------------------- #
# Turn-level wallclock timeout
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_harness_turn_wallclock_timeout_emits_cancelled_error(
    monkeypatch,
):
    """When ``max_turn_wallclock_s`` is exceeded the harness must:
      * cancel the in-flight agent astream (so any awaited tool wakes up with
        ``CancelledError`` at its next await point)
      * emit a terminal ``error`` event with ``turn_status="cancelled"`` so
        the SSE adapter persists partial segments exactly like a client
        disconnect
      * not leak an uncaught ``TimeoutError`` out of the generator
    """
    monkeypatch.setattr(
        "runtime.query_engine.get_max_turn_wallclock_s",
        lambda: 0.05,
    )

    agent_manager = _StallingAgentManager()
    engine = QueryEngine(agent_manager)
    turn = QueryTurnInput(message="hello", history=[])

    events: list[dict[str, Any]] = []
    async for event in engine.run_harness_turn(turn):
        events.append(event)

    assert agent_manager.streaming_cancelled.is_set(), (
        "turn wallclock timeout must deliver CancelledError into the astream"
    )
    # A single terminal error event is the last thing on the wire, carrying
    # the cancel-class turn_status so the SSE layer reuses the disconnect
    # persistence path.
    assert events, "turn-timeout must produce at least one event"
    terminal = events[-1]
    assert terminal["type"] == "error"
    assert terminal.get("turn_status") == "cancelled"
    assert "wallclock" in terminal["error"].lower()


# --------------------------------------------------------------------------- #
# Per-tool wallclock timeout
# --------------------------------------------------------------------------- #


class _SleepingTool(BaseTool):
    name: str = "sleeping_tool"
    description: str = "Sleeps for the requested number of seconds."
    response_format: str = "content_and_artifact"
    entered: asyncio.Event = None  # type: ignore[assignment]

    def _run(self, seconds: float) -> str:  # pragma: no cover - async-only test
        raise NotImplementedError

    async def _arun(self, seconds: float) -> str:
        if self.entered is not None:
            self.entered.set()
        await asyncio.sleep(seconds)
        return "done"


def _sleeping_manifest() -> ToolManifestEntry:
    return ToolManifestEntry(
        name="sleeping_tool",
        description="Sleeps for the requested number of seconds.",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_runtime_cancellation",
        read_only=True,
        destructive=False,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        tool_validates_input=False,
        activity_summary_hint="inspect",
        result_summary_hint="result",
        sandbox=None,
    )


@pytest.mark.asyncio
async def test_per_tool_wallclock_override_cancels_stuck_tool(monkeypatch):
    """A config ``tool_wallclock.overrides[<name>]`` entry must be enforced
    in ``PolicyWrappedTool._arun``: the stuck tool is cancelled via
    ``asyncio.wait_for`` and the wrapper returns a ``blocked`` envelope
    with the ``sandbox_wall_clock_exceeded`` reason code.

    The manifest here carries no ``SandboxSpec``, so the override is the
    only source of the timeout — proving that the config knob alone is
    enough to bound a tool with no declared sandbox.
    """
    entered = asyncio.Event()
    inner = _SleepingTool(entered=entered)
    wrapper = PolicyWrappedTool(
        name=inner.name,
        description=inner.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=inner,
        manifest=_sleeping_manifest(),
    )

    monkeypatch.setattr(
        "tools.policy_wrappers.get_tool_wallclock_override_s",
        lambda name: 0.05 if name == "sleeping_tool" else None,
    )

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-tool-timeout",
            request_id="request-tool-timeout",
            allowed_access_scope="execution",
        )
    ):
        summary, artifact = await wrapper._arun(seconds=5.0)

    assert entered.is_set(), "the stuck tool must have started before the cap fired"
    assert summary.startswith("[BLOCKED]"), (
        "a wallclock-cancelled tool must surface a blocked envelope, not a success"
    )
    assert artifact["outcome"] == "blocked"
    assert (
        artifact["metadata"]["policy_block_reason"] == "sandbox_wall_clock_exceeded"
    )
    assert artifact["metadata"]["sandbox_wall_clock_seconds"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_client_disconnect_still_raises_cancelled_error_with_override(
    monkeypatch,
):
    """Client-disconnect cancellation must still propagate as
    ``CancelledError`` even when a per-tool override is configured — the
    wrapper must not convert a consumer-initiated cancel into the wallclock
    blocked envelope. This guards the disconnect path documented in issue
    #113 against a regression from the new timeout plumbing.
    """
    started = asyncio.Event()
    inner = _CancellableTool(started=started)
    wrapper = PolicyWrappedTool(
        name=inner.name,
        description=inner.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=inner,
        manifest=_bare_manifest(inner.name),
    )

    # A very long override is present but does not fire in this test — the
    # cancel comes from the consumer task, not the wait_for deadline.
    monkeypatch.setattr(
        "tools.policy_wrappers.get_tool_wallclock_override_s",
        lambda name: 60.0,
    )

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-disconnect",
            request_id="request-disconnect",
            allowed_access_scope="execution",
        )
    ):
        task = asyncio.create_task(wrapper._arun())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
