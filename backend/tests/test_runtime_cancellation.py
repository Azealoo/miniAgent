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
