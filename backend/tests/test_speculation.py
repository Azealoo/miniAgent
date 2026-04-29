"""Tests for speculative read-only tool execution.

Covers the three issue-#79 acceptance items: the ``speculation`` metadata
on a cache-hit tool envelope, the speculation trace JSONL that records
every started / accepted / discarded event, and a fixture-based benchmark
that demonstrates measurable latency reduction when a slow read-only tool
is speculated in parallel with ongoing stream work.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry
from tools.speculation import (
    SpeculationSession,
    canonical_args_digest,
    speculation_session,
)


class _SleepingReadOnlyTool(BaseTool):
    name: str = "slow_read"
    description: str = "Simulates a slow read-only tool."
    response_format: str = "content_and_artifact"
    sleep_s: float = 0.05
    call_count: int = 0

    def _run(self, path: str = "x", **kwargs):  # pragma: no cover - async path only
        raise NotImplementedError

    async def _arun(self, path: str = "x", **kwargs):
        type(self).call_count += 1
        await asyncio.sleep(self.sleep_s)
        return f"read:{path}"


class _DestructiveTool(BaseTool):
    name: str = "write_thing"
    description: str = "Destructive."
    response_format: str = "content_and_artifact"

    def _run(self, **kwargs):  # pragma: no cover
        return "ok"

    async def _arun(self, **kwargs):  # pragma: no cover
        return "ok"


def _read_only_manifest(name: str = "slow_read") -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="test read-only tool",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_speculation",
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


def _destructive_manifest() -> ToolManifestEntry:
    return replace(
        _read_only_manifest("write_thing"),
        read_only=False,
        destructive=True,
        concurrency_safe=False,
        interrupt_behavior="avoid_interrupting",
    )


def _wrap(tool: BaseTool, manifest: ToolManifestEntry) -> PolicyWrappedTool:
    return PolicyWrappedTool(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=tool,
        manifest=manifest,
    )


@pytest.fixture(autouse=True)
def _reset_tool_counters():
    _SleepingReadOnlyTool.call_count = 0
    yield
    _SleepingReadOnlyTool.call_count = 0


@pytest.fixture
def exec_ctx():
    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-spec",
            request_id="req-spec",
            turn_id="turn-spec",
            allowed_access_scope="execution",
        )
    ):
        yield


@pytest.fixture
def trace_dir() -> Path:
    return Path(os.environ["BIOAPEX_TOOL_TRACE_DIR"])


def _read_speculation_trace(trace_dir: Path) -> list[dict]:
    path = trace_dir / "speculation.jsonl"
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_canonical_args_digest_is_order_independent():
    a = canonical_args_digest((), {"b": 2, "a": 1})
    b = canonical_args_digest((), {"a": 1, "b": 2})
    assert a == b

    c = canonical_args_digest((), {"a": 1, "b": 3})
    assert a != c


def test_matching_speculation_is_consumed_and_tool_runs_once(exec_ctx, trace_dir):
    tool = _SleepingReadOnlyTool()
    wrapped = _wrap(tool, _read_only_manifest())

    async def _scenario():
        session = SpeculationSession(session_id="session-spec", turn_id="turn-spec")
        with speculation_session(session):
            assert wrapped.schedule_speculation({"path": "a.txt"}) is True
            # Let the speculation make progress before the real dispatch.
            await asyncio.sleep(0.01)
            summary, envelope = await wrapped._arun(path="a.txt")
        return summary, envelope

    summary, envelope = asyncio.run(_scenario())

    assert summary == "read:a.txt"
    spec_meta = envelope["metadata"]["speculation"]
    assert spec_meta["was_speculative"] is True
    assert spec_meta["speculation_duration_ms"] >= 0
    assert spec_meta["consumed_at"].endswith("Z")
    # The wrapped tool must have executed exactly once — the consumer
    # served the cached task instead of dispatching a second invocation.
    assert _SleepingReadOnlyTool.call_count == 1

    records = _read_speculation_trace(trace_dir)
    phases = [record["phase"] for record in records]
    assert phases == ["started", "accepted"]
    assert records[1]["tool_name"] == "slow_read"
    assert records[1]["speculation_duration_ms"] >= 0


def test_speculation_miss_on_different_args_falls_through(exec_ctx, trace_dir):
    tool = _SleepingReadOnlyTool()
    wrapped = _wrap(tool, _read_only_manifest())

    async def _scenario():
        session = SpeculationSession(session_id="session-spec", turn_id="turn-spec")
        with speculation_session(session):
            assert wrapped.schedule_speculation({"path": "a.txt"}) is True
            summary, envelope = await wrapped._arun(path="different.txt")
            # Exiting the session must cancel and log the stray speculation.
            await session.discard_pending("stream_ended")
        return summary, envelope

    summary, envelope = asyncio.run(_scenario())

    assert summary == "read:different.txt"
    assert "speculation" not in envelope["metadata"]
    # One speculative call (cancelled after launch) plus the real one.
    assert _SleepingReadOnlyTool.call_count >= 1

    records = _read_speculation_trace(trace_dir)
    phases = [record["phase"] for record in records]
    assert "started" in phases
    assert "discarded" in phases
    discarded = next(record for record in records if record["phase"] == "discarded")
    assert discarded["reason"] == "stream_ended"


def test_destructive_tool_is_not_speculatable(exec_ctx, trace_dir):
    wrapped = _wrap(_DestructiveTool(), _destructive_manifest())

    async def _scenario():
        session = SpeculationSession(session_id="session-spec", turn_id="turn-spec")
        with speculation_session(session):
            scheduled = wrapped.schedule_speculation({})
            assert scheduled is False
            assert session.scheduled_count() == 0

    asyncio.run(_scenario())
    assert _read_speculation_trace(trace_dir) == []


def test_speculation_disabled_via_env(monkeypatch, exec_ctx):
    monkeypatch.setenv("BIOAPEX_SPECULATIVE_TOOLS", "0")
    wrapped = _wrap(_SleepingReadOnlyTool(), _read_only_manifest())

    async def _scenario():
        session = SpeculationSession()
        with speculation_session(session):
            assert wrapped.schedule_speculation({"path": "a.txt"}) is False

    asyncio.run(_scenario())


def test_speculation_benchmark_shows_latency_reduction(exec_ctx):
    """Fixture-based benchmark — the acceptance criterion from issue #79.

    The fixture is a read-only tool with a 60ms sleep. The baseline waits
    for a 40ms stream-simulation gap and then dispatches the tool
    synchronously: total wall time ≈ 40ms + 60ms = ~100ms. The
    speculated run schedules the tool at t=0, lets the 40ms gap elapse
    in parallel, and then dispatches; total wall time ≈ max(40ms, 60ms)
    = ~60ms. We assert a meaningful reduction with generous slack so
    the test stays robust under CI jitter.
    """

    sleep_s = 0.06
    stream_gap_s = 0.04

    baseline_tool = _SleepingReadOnlyTool()
    baseline_tool.sleep_s = sleep_s
    baseline_wrapped = _wrap(baseline_tool, _read_only_manifest())

    async def _baseline():
        t0 = time.perf_counter()
        await asyncio.sleep(stream_gap_s)
        await baseline_wrapped._arun(path="bench.txt")
        return time.perf_counter() - t0

    speculative_tool = _SleepingReadOnlyTool()
    speculative_tool.sleep_s = sleep_s
    speculative_wrapped = _wrap(speculative_tool, _read_only_manifest())

    async def _speculative():
        session = SpeculationSession(session_id="bench", turn_id="bench")
        with speculation_session(session):
            t0 = time.perf_counter()
            assert speculative_wrapped.schedule_speculation({"path": "bench.txt"}) is True
            await asyncio.sleep(stream_gap_s)
            _, envelope = await speculative_wrapped._arun(path="bench.txt")
            elapsed = time.perf_counter() - t0
        assert envelope["metadata"]["speculation"]["was_speculative"] is True
        return elapsed

    baseline_elapsed = asyncio.run(_baseline())
    speculative_elapsed = asyncio.run(_speculative())

    # Speculation should save ≈ min(stream_gap_s, sleep_s) of wall time.
    # Require at least half that saving so CI jitter doesn't flake.
    min_expected_saving = min(stream_gap_s, sleep_s) * 0.5
    saving = baseline_elapsed - speculative_elapsed
    assert saving >= min_expected_saving, (
        f"speculation saved only {saving * 1000:.1f}ms; "
        f"baseline={baseline_elapsed * 1000:.1f}ms "
        f"speculative={speculative_elapsed * 1000:.1f}ms"
    )


def test_speculation_cancel_on_session_exit(exec_ctx, trace_dir):
    tool = _SleepingReadOnlyTool()
    tool.sleep_s = 0.5  # long enough that it cannot complete during the test
    wrapped = _wrap(tool, _read_only_manifest())

    async def _scenario():
        session = SpeculationSession(session_id="session-spec", turn_id="turn-spec")
        with speculation_session(session):
            wrapped.schedule_speculation({"path": "a.txt"})
            assert session.pending_count() == 1
            await session.discard_pending("stream_ended")
            assert session.pending_count() == 0

    asyncio.run(_scenario())
    records = _read_speculation_trace(trace_dir)
    phases = [record["phase"] for record in records]
    assert phases == ["started", "discarded"]
    assert records[1]["reason"] == "stream_ended"
