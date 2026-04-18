from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import AsyncGenerator
from unittest.mock import patch

import pytest

from runtime.query_engine import (
    QueryEngine,
    QueryTurnInput,
    ToolBatchCall,
    dispatch_tool_batch,
)
from tools.registry import ToolManifestEntry


def _manifest(
    name: str,
    *,
    read_only: bool,
    destructive: bool,
    concurrency_safe: bool,
) -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description=f"fake {name}",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection" if read_only else "execution",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_runtime_query_engine",
        read_only=read_only,
        destructive=destructive,
        concurrency_safe=concurrency_safe,
        planner_exposed=read_only,
        verifier_exposed=read_only,
        interrupt_behavior="restartable" if read_only else "avoid_interrupting",
        tool_validates_input=False,
        activity_summary_hint="inspect",
        result_summary_hint="result",
    )


class _FakeAgentManager:
    def __init__(self, base_dir: str = "/tmp/query-engine") -> None:
        self.base_dir = base_dir

    async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
        assert message == "hello"
        assert history == [{"role": "system", "content": "ctx"}]
        yield {"type": "token", "content": "ok"}
        yield {"type": "done"}


@pytest.mark.asyncio
async def test_query_engine_run_harness_turn_delegates_to_agent_manager():
    engine = QueryEngine(_FakeAgentManager())
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_harness_turn(turn)]

    assert events == [
        {"type": "token", "content": "ok"},
        {"type": "done", "turn_status": "ok"},
    ]


@pytest.mark.asyncio
async def test_query_engine_run_harness_turn_emits_plan_created_then_plan_updated_events():
    class _PlanningAgentManager(_FakeAgentManager):
        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            assert message == "hello"
            assert history == [{"role": "system", "content": "ctx"}]
            yield {
                "type": "tool_end",
                "tool": "plan_agent",
                "output": "planner summary",
                "run_id": "plan-run-1",
                "result": {
                    "status": "success",
                    "summary": "Planner produced 2 steps.",
                    "structured_payload": {
                        "agent_type": "plan",
                        "plan": {
                            "goal": "Investigate hello",
                            "steps": [
                                {"step_id": "step-1", "intent": "Inspect context"},
                                {"step_id": "step-2", "intent": "Draft response"},
                            ],
                        },
                        "tool_trace": [{"tool": "read_file", "summary": "README"}],
                    },
                },
            }
            yield {
                "type": "tool_end",
                "tool": "plan_agent",
                "output": "planner update summary",
                "run_id": "plan-run-2",
                "result": {
                    "status": "success",
                    "summary": "Planner updated the plan.",
                    "structured_payload": {
                        "agent_type": "plan",
                        "plan": {
                            "goal": "Investigate hello",
                            "steps": [
                                {"step_id": "step-1", "intent": "Inspect context"},
                            ],
                        },
                        "tool_trace": [{"tool": "search_memory", "summary": "memory"}],
                    },
                },
            }
            yield {"type": "done"}

    engine = QueryEngine(_PlanningAgentManager())
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_harness_turn(turn)]

    assert events == [
        {
            "type": "tool_end",
            "tool": "plan_agent",
            "output": "planner summary",
            "run_id": "plan-run-1",
            "result": {
                "status": "success",
                "summary": "Planner produced 2 steps.",
                "structured_payload": {
                    "agent_type": "plan",
                    "plan": {
                        "goal": "Investigate hello",
                        "steps": [
                            {"step_id": "step-1", "intent": "Inspect context"},
                            {"step_id": "step-2", "intent": "Draft response"},
                        ],
                    },
                    "tool_trace": [{"tool": "read_file", "summary": "README"}],
                },
            },
        },
        {
            "type": "plan_created",
            "run_id": "plan-run-1",
            "summary": "Planner produced 2 steps.",
            "plan": {
                "goal": "Investigate hello",
                "steps": [
                    {"step_id": "step-1", "intent": "Inspect context"},
                    {"step_id": "step-2", "intent": "Draft response"},
                ],
            },
            "tool_trace": [{"tool": "read_file", "summary": "README"}],
        },
        {
            "type": "tool_end",
            "tool": "plan_agent",
            "output": "planner update summary",
            "run_id": "plan-run-2",
            "result": {
                "status": "success",
                "summary": "Planner updated the plan.",
                "structured_payload": {
                    "agent_type": "plan",
                    "plan": {
                        "goal": "Investigate hello",
                        "steps": [
                            {"step_id": "step-1", "intent": "Inspect context"},
                        ],
                    },
                    "tool_trace": [{"tool": "search_memory", "summary": "memory"}],
                },
            },
        },
        {
            "type": "plan_updated",
            "run_id": "plan-run-2",
            "summary": "Planner updated the plan.",
            "plan": {
                "goal": "Investigate hello",
                "steps": [
                    {"step_id": "step-1", "intent": "Inspect context"},
                ],
            },
            "tool_trace": [{"tool": "search_memory", "summary": "memory"}],
        },
        {"type": "done", "turn_status": "ok"},
    ]


@pytest.mark.asyncio
async def test_query_engine_run_harness_turn_emits_verification_result_event():
    class _VerifyingAgentManager(_FakeAgentManager):
        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            assert message == "hello"
            assert history == [{"role": "system", "content": "ctx"}]
            yield {
                "type": "tool_end",
                "tool": "verification_agent",
                "output": "verifier summary",
                "run_id": "verify-run-1",
                "result": {
                    "status": "success",
                    "summary": "Verifier verdict: pass. Looks good.",
                    "structured_payload": {
                        "agent_type": "verification",
                        "verification": {
                            "verdict": "pass",
                            "summary": "Looks good.",
                            "checks": [{"name": "coverage", "status": "pass", "note": "ok"}],
                        },
                        "tool_trace": [{"tool": "read_file", "summary": "result"}],
                    },
                },
            }
            yield {"type": "done"}

    engine = QueryEngine(_VerifyingAgentManager())
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_harness_turn(turn)]

    assert events == [
        {
            "type": "tool_end",
            "tool": "verification_agent",
            "output": "verifier summary",
            "run_id": "verify-run-1",
            "result": {
                "status": "success",
                "summary": "Verifier verdict: pass. Looks good.",
                "structured_payload": {
                    "agent_type": "verification",
                    "verification": {
                        "verdict": "pass",
                        "summary": "Looks good.",
                        "checks": [{"name": "coverage", "status": "pass", "note": "ok"}],
                    },
                    "tool_trace": [{"tool": "read_file", "summary": "result"}],
                },
            },
        },
        {
            "type": "verification_result",
            "run_id": "verify-run-1",
            "summary": "Verifier verdict: pass. Looks good.",
            "verdict": "pass",
            "verification": {
                "verdict": "pass",
                "summary": "Looks good.",
                "checks": [{"name": "coverage", "status": "pass", "note": "ok"}],
            },
            "tool_trace": [{"tool": "read_file", "summary": "result"}],
        },
        {"type": "done", "turn_status": "ok"},
    ]


@pytest.mark.asyncio
async def test_query_engine_run_harness_turn_runs_single_repair_pass_with_latest_artifacts():
    class _RepairingAgentManager(_FakeAgentManager):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, list[dict]]] = []

        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            self.calls.append((message, history))
            if len(self.calls) == 1:
                assert message == "hello"
                assert history == [{"role": "system", "content": "ctx"}]
                yield {
                    "type": "tool_end",
                    "tool": "plan_agent",
                    "output": "planner summary",
                    "run_id": "plan-run-1",
                    "result": {
                        "status": "success",
                        "summary": "Planner produced 1 step.",
                        "structured_payload": {
                            "agent_type": "plan",
                            "plan": {
                                "goal": "Investigate hello",
                                "steps": [
                                    {"step_id": "step-1", "intent": "Inspect evidence"},
                                ],
                            },
                            "tool_trace": [{"tool": "read_file", "summary": "notes"}],
                        },
                    },
                }
                yield {"type": "token", "content": "Draft answer without citation."}
                yield {
                    "type": "tool_end",
                    "tool": "verification_agent",
                    "output": "verifier summary",
                    "run_id": "verify-run-1",
                    "result": {
                        "status": "success",
                        "summary": "Verifier verdict: repair_required. Add one citation.",
                        "structured_payload": {
                            "agent_type": "verification",
                            "verification": {
                                "verdict": "repair_required",
                                "summary": "Add one citation.",
                                "checks": [{"name": "support", "status": "fail", "note": "Need evidence."}],
                                "issues": ["Missing citation."],
                                "repair_instructions": ["Cite the evidence review artifact."],
                            },
                            "tool_trace": [{"tool": "evidence_review", "summary": "artifact"}],
                        },
                    },
                }
                yield {"type": "done"}
                return

            assert len(self.calls) == 2
            assert message == "hello"
            repair_message = history[-1]
            assert repair_message["role"] == "system"
            assert (
                "Do not present background guidance as verified current project state."
                in repair_message["content"]
            )
            assert "Original user task:\nhello" in repair_message["content"]
            assert '"goal": "Investigate hello"' in repair_message["content"]
            assert "Missing citation." in repair_message["content"]
            assert "Cite the evidence review artifact." in repair_message["content"]
            assert "Draft answer without citation." in repair_message["content"]
            yield {"type": "token", "content": "Repaired answer with citation."}
            yield {"type": "done"}

    manager = _RepairingAgentManager()
    engine = QueryEngine(manager)
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_harness_turn(turn)]

    assert events == [
        {
            "type": "tool_end",
            "tool": "plan_agent",
            "output": "planner summary",
            "run_id": "plan-run-1",
            "result": {
                "status": "success",
                "summary": "Planner produced 1 step.",
                "structured_payload": {
                    "agent_type": "plan",
                    "plan": {
                        "goal": "Investigate hello",
                        "steps": [
                            {"step_id": "step-1", "intent": "Inspect evidence"},
                        ],
                    },
                    "tool_trace": [{"tool": "read_file", "summary": "notes"}],
                },
            },
        },
        {
            "type": "plan_created",
            "run_id": "plan-run-1",
            "summary": "Planner produced 1 step.",
            "plan": {
                "goal": "Investigate hello",
                "steps": [
                    {"step_id": "step-1", "intent": "Inspect evidence"},
                ],
            },
            "tool_trace": [{"tool": "read_file", "summary": "notes"}],
        },
        {"type": "token", "content": "Draft answer without citation."},
        {
            "type": "tool_end",
            "tool": "verification_agent",
            "output": "verifier summary",
            "run_id": "verify-run-1",
            "result": {
                "status": "success",
                "summary": "Verifier verdict: repair_required. Add one citation.",
                "structured_payload": {
                    "agent_type": "verification",
                    "verification": {
                        "verdict": "repair_required",
                        "summary": "Add one citation.",
                        "checks": [{"name": "support", "status": "fail", "note": "Need evidence."}],
                        "issues": ["Missing citation."],
                        "repair_instructions": ["Cite the evidence review artifact."],
                    },
                    "tool_trace": [{"tool": "evidence_review", "summary": "artifact"}],
                },
            },
        },
        {
            "type": "verification_result",
            "run_id": "verify-run-1",
            "summary": "Verifier verdict: repair_required. Add one citation.",
            "verdict": "repair_required",
            "verification": {
                "verdict": "repair_required",
                "summary": "Add one citation.",
                "checks": [{"name": "support", "status": "fail", "note": "Need evidence."}],
                "issues": ["Missing citation."],
                "repair_instructions": ["Cite the evidence review artifact."],
            },
            "tool_trace": [{"tool": "evidence_review", "summary": "artifact"}],
        },
        {"type": "new_response"},
        {"type": "token", "content": "Repaired answer with citation."},
        {"type": "done", "turn_status": "ok"},
    ]


@pytest.mark.asyncio
async def test_query_engine_run_harness_turn_stops_after_one_repair_retry():
    class _StillFailingAgentManager(_FakeAgentManager):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            self.calls += 1
            assert message == "hello"
            if self.calls == 1:
                assert history == [{"role": "system", "content": "ctx"}]
                yield {"type": "token", "content": "First draft."}
                yield {
                    "type": "tool_end",
                    "tool": "verification_agent",
                    "output": "verifier summary",
                    "run_id": "verify-run-1",
                    "result": {
                        "status": "success",
                        "summary": "Verifier verdict: fail. Missing core details.",
                        "structured_payload": {
                            "agent_type": "verification",
                            "verification": {
                                "verdict": "fail",
                                "summary": "Missing core details.",
                                "checks": [{"name": "coverage", "status": "fail", "note": "Missing details."}],
                                "issues": ["Critical gap."],
                                "repair_instructions": ["Add the missing details."],
                            },
                            "tool_trace": [],
                        },
                    },
                }
                yield {"type": "done"}
                return

            if self.calls == 2:
                assert history[-1]["role"] == "system"
                yield {"type": "token", "content": "Second draft."}
                yield {
                    "type": "tool_end",
                    "tool": "verification_agent",
                    "output": "second verifier summary",
                    "run_id": "verify-run-2",
                    "result": {
                        "status": "success",
                        "summary": "Verifier verdict: fail. Still missing details.",
                        "structured_payload": {
                            "agent_type": "verification",
                            "verification": {
                                "verdict": "fail",
                                "summary": "Still missing details.",
                                "checks": [{"name": "coverage", "status": "fail", "note": "Still missing."}],
                                "issues": ["Critical gap remains."],
                                "repair_instructions": ["No more retries."],
                            },
                            "tool_trace": [],
                        },
                    },
                }
                yield {"type": "done"}
                return

            raise AssertionError("repair loop should stop after one retry")

    manager = _StillFailingAgentManager()
    engine = QueryEngine(manager)
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_harness_turn(turn)]

    assert manager.calls == 2
    assert [event["type"] for event in events].count("new_response") == 1
    assert [event["type"] for event in events].count("verification_result") == 2
    assert events[-1] == {"type": "done", "turn_status": "ok"}


@pytest.mark.asyncio
async def test_query_engine_can_treat_repair_required_as_advisory():
    class _RepairSuggestedAgentManager(_FakeAgentManager):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            self.calls += 1
            assert message == "hello"
            assert history == [{"role": "system", "content": "ctx"}]
            yield {"type": "token", "content": "Good-enough draft."}
            yield {
                "type": "tool_end",
                "tool": "verification_agent",
                "output": "verifier summary",
                "run_id": "verify-run-1",
                "result": {
                    "status": "success",
                    "summary": "Verifier verdict: repair_required. Optional improvement only.",
                    "structured_payload": {
                        "agent_type": "verification",
                        "verification": {
                            "verdict": "repair_required",
                            "summary": "Optional improvement only.",
                            "checks": [{"name": "polish", "status": "fail", "note": "Could be tighter."}],
                            "issues": ["Optional cleanup."],
                            "repair_instructions": ["Tighten the prose if desired."],
                        },
                        "tool_trace": [],
                    },
                },
            }
            yield {"type": "done"}

    manager = _RepairSuggestedAgentManager()
    engine = QueryEngine(manager)
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    with patch(
        "runtime.query_engine.get_verification_settings",
        return_value={"retry_on_repair_required": False},
    ):
        events = [event async for event in engine.run_harness_turn(turn)]

    assert manager.calls == 1
    assert [event["type"] for event in events].count("new_response") == 0
    assert events[-1] == {"type": "done", "turn_status": "ok"}


@pytest.mark.asyncio
async def test_query_engine_stops_runaway_planner_when_budget_exceeded():
    class _RunawayPlannerAgentManager(_FakeAgentManager):
        def __init__(self) -> None:
            super().__init__()
            self.tool_ends_emitted = 0

        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            for step in range(100):
                self.tool_ends_emitted += 1
                yield {
                    "type": "tool_end",
                    "tool": "plan_agent",
                    "output": "planner chunk " * 500,
                    "run_id": f"plan-run-{step}",
                    "result": {
                        "status": "success",
                        "summary": f"Planner step {step}.",
                        "structured_payload": {
                            "agent_type": "plan",
                            "plan": {"goal": "loop", "steps": []},
                            "tool_trace": [],
                        },
                    },
                }
            yield {"type": "done"}

    manager = _RunawayPlannerAgentManager()
    engine = QueryEngine(manager)
    turn = QueryTurnInput(message="hi", history=[])

    with patch(
        "runtime.query_engine.get_max_tokens_per_turn",
        return_value=2000,
    ):
        events = [event async for event in engine.run_harness_turn(turn)]

    error_events = [event for event in events if event.get("type") == "error"]
    assert len(error_events) == 1
    error = error_events[0]
    assert error["error"].startswith("turn budget exceeded at ")
    assert error["turn_status"] == "budget_exceeded"
    assert events[-1] is error

    tool_end_events = [event for event in events if event.get("type") == "tool_end"]
    assert tool_end_events, "prior tool_end events must be preserved before error"

    plan_events = [event for event in events if event.get("type") in {"plan_created", "plan_updated"}]
    assert plan_events, "prior plan_* events must be preserved before error"

    crossing_step = manager.tool_ends_emitted
    assert crossing_step < 100, "runaway planner must terminate before exhausting its loop"
    budget_crossing_tool_end = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "tool_end"
        and event.get("run_id") == f"plan-run-{crossing_step - 1}"
    )
    remaining_tool_ends = [
        event
        for event in events[budget_crossing_tool_end + 1 :]
        if event.get("type") == "tool_end"
    ]
    assert remaining_tool_ends == [], (
        "runtime must terminate within one step after crossing the budget"
    )


@pytest.mark.asyncio
async def test_query_engine_run_turn_attaches_turn_result_to_budget_error():
    class _RunawayPlannerAgentManager(_FakeAgentManager):
        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            yield {"type": "token", "content": "partial draft "}
            yield {
                "type": "tool_end",
                "tool": "plan_agent",
                "output": "x" * 20000,
                "run_id": "plan-run-1",
                "result": {
                    "status": "success",
                    "summary": "big planner output",
                    "structured_payload": {
                        "agent_type": "plan",
                        "plan": {"goal": "loop", "steps": []},
                        "tool_trace": [],
                    },
                },
            }
            yield {"type": "done"}

    engine = QueryEngine(_RunawayPlannerAgentManager())
    turn = QueryTurnInput(message="hi", history=[])

    with patch(
        "runtime.query_engine.get_max_tokens_per_turn",
        return_value=500,
    ):
        events = [event async for event in engine.run_turn(turn)]

    error_events = [event for event in events if event.get("type") == "error"]
    assert len(error_events) == 1
    error = error_events[0]
    assert error["error"].startswith("turn budget exceeded at ")
    turn_result = error["turn_result"]
    assert turn_result.turn_status == "budget_exceeded"
    assert any(
        "partial draft" in seg.content for seg in turn_result.segments
    ), "partial streamed content must be preserved on budget error"


@pytest.mark.asyncio
async def test_query_engine_run_harness_turn_uses_agent_path_when_not_protocol_or_workflow():
    engine = QueryEngine(_FakeAgentManager())
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_harness_turn(turn)]

    assert events == [
        {"type": "token", "content": "ok"},
        {"type": "done", "turn_status": "ok"},
    ]


@pytest.mark.asyncio
async def test_query_engine_run_turn_persists_message_then_runs_agent_directly():
    engine = QueryEngine(_FakeAgentManager())
    policy_context = SimpleNamespace()
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
        policy_context=policy_context,
    )

    events = [event async for event in engine.run_turn(turn)]

    assert events[:-1] == [
        {"type": "persist_user_message"},
        {"type": "token", "content": "ok"},
    ]
    assert events[-1]["type"] == "done"
    assert events[-1]["turn_status"] == "ok"
    turn_result = events[-1]["turn_result"]
    assert turn_result.turn_status == "ok"
    assert turn_result.final_content == "ok"
    assert len(turn_result.segments) == 1
    assert turn_result.segments[0].content == "ok"
    assert all(block["type"] != "tool_use" for block in turn_result.segments[0].blocks)


@pytest.mark.asyncio
async def test_query_engine_run_turn_uses_chat_only_dispatch_without_workflow_state():
    engine = QueryEngine(_FakeAgentManager())
    turn = QueryTurnInput(
        message="hello",
        history=[{"role": "system", "content": "ctx"}],
    )

    events = [event async for event in engine.run_turn(turn)]

    assert {"type": "token", "content": "ok"} in events
    assert events[-1]["type"] == "done"
    assert events[-1]["turn_status"] == "ok"


@pytest.mark.asyncio
async def test_query_engine_run_turn_keeps_biology_questions_on_the_same_dispatch_path():
    class _ReviewingAgentManager(_FakeAgentManager):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, list[dict]]] = []

        async def astream(self, message: str, history: list[dict]) -> AsyncGenerator[dict, None]:
            self.calls.append((message, history))
            yield {"type": "token", "content": "Draft answer on the normal path."}
            yield {"type": "done"}

    agent_manager = _ReviewingAgentManager()
    engine = QueryEngine(agent_manager)
    turn = QueryTurnInput(
        message="What is the evidence for TP53 stress response?",
        history=[],
    )

    events = [event async for event in engine.run_turn(turn)]

    assert events[:-1] == [
        {"type": "persist_user_message"},
        {"type": "token", "content": "Draft answer on the normal path."},
    ]
    assert events[-1]["type"] == "done"
    assert events[-1]["turn_status"] == "ok"
    turn_result = events[-1]["turn_result"]
    assert turn_result.turn_status == "ok"
    assert turn_result.final_content == "Draft answer on the normal path."
    assert len(turn_result.segments) == 1
    assert turn_result.segments[0].content == "Draft answer on the normal path."
    assert all(block["type"] != "tool_use" for block in turn_result.segments[0].blocks)
    assert agent_manager.calls == [
        (
            "What is the evidence for TP53 stress response?",
            [],
        )
    ]


@pytest.mark.asyncio
async def test_dispatch_tool_batch_gathers_concurrency_safe_reads():
    """Read-only/concurrency-safe calls overlap via asyncio.gather.

    Each call increments a shared in-flight counter and sleeps briefly.
    If gather dispatches them together, the counter's peak equals the
    number of parallel calls; a serial implementation would peak at 1.
    """
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def _make_read_call(label: str):
        nonlocal in_flight, peak

        async def _invoke():
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.05)
                return f"{label}-done"
            finally:
                async with lock:
                    in_flight -= 1

        return _invoke

    calls = [
        ToolBatchCall(
            manifest=_manifest(
                f"read_{idx}",
                read_only=True,
                destructive=False,
                concurrency_safe=True,
            ),
            invoke=await _make_read_call(f"read-{idx}"),
        )
        for idx in range(4)
    ]

    results = await dispatch_tool_batch(calls)

    assert results == ["read-0-done", "read-1-done", "read-2-done", "read-3-done"]
    assert peak == 4, (
        f"expected all 4 read-only tools to run concurrently via gather, "
        f"observed peak={peak}"
    )


@pytest.mark.asyncio
async def test_dispatch_tool_batch_serializes_destructive_calls():
    """Destructive calls must run one at a time, in input order."""

    order: list[str] = []
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    def _make_destructive(label: str):
        async def _invoke():
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0.02)
                order.append(label)
                return label
            finally:
                async with lock:
                    in_flight -= 1

        return _invoke

    calls = [
        ToolBatchCall(
            manifest=_manifest(
                f"write_{idx}",
                read_only=False,
                destructive=True,
                concurrency_safe=False,
            ),
            invoke=_make_destructive(f"write-{idx}"),
        )
        for idx in range(3)
    ]

    results = await dispatch_tool_batch(calls)

    assert results == ["write-0", "write-1", "write-2"]
    assert order == ["write-0", "write-1", "write-2"]
    assert peak == 1, f"destructive tier must be serial, observed peak={peak}"


@pytest.mark.asyncio
async def test_dispatch_tool_batch_preserves_order_across_mixed_tiers():
    """A mixed batch returns results in the original input order."""

    async def _return(value):
        async def _invoke():
            await asyncio.sleep(0)
            return value

        return _invoke

    calls = [
        ToolBatchCall(
            manifest=_manifest(
                "read_a",
                read_only=True,
                destructive=False,
                concurrency_safe=True,
            ),
            invoke=await _return("a"),
        ),
        ToolBatchCall(
            manifest=_manifest(
                "write_b",
                read_only=False,
                destructive=True,
                concurrency_safe=False,
            ),
            invoke=await _return("b"),
        ),
        ToolBatchCall(
            manifest=_manifest(
                "read_c",
                read_only=True,
                destructive=False,
                concurrency_safe=True,
            ),
            invoke=await _return("c"),
        ),
    ]

    assert await dispatch_tool_batch(calls) == ["a", "b", "c"]
