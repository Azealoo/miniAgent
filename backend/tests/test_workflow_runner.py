"""Behavioral tests for ``runtime.workflow_runner``.

The runner's contract is the step-level event stream. These tests drive it with
in-process Python executors (registered via a helper module) rather than the
real biology runners, so they stay hermetic and fast while still exercising
the full event-emission path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime.events import build_runtime_event  # noqa: E402
from runtime.workflow_runner import run_workflow  # noqa: E402
from workflow_specs import WorkflowSpec, validate_workflow_spec_payload  # noqa: E402


_TEST_RUNNER_MODULE_NAME = "tests._workflow_runner_inprocess"


@pytest.fixture(autouse=True)
def _inprocess_runner_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register a temporary module the specs under test can dotted-path into.

    The spec validator enforces a valid Python dotted module path, but it does
    not require the module to exist at validation time. Only
    ``run_workflow`` imports it; we wire up a dedicated module so each test
    can swap step functions without touching the real runner tree.
    """
    module = ModuleType(_TEST_RUNNER_MODULE_NAME)
    sys.modules[_TEST_RUNNER_MODULE_NAME] = module
    yield module
    sys.modules.pop(_TEST_RUNNER_MODULE_NAME, None)


def _register_step(module: ModuleType, name: str, fn: Callable[..., Any]) -> None:
    setattr(module, name, fn)


def _minimal_spec_payload(
    *,
    failure_policy: str = "fail_workflow",
    max_attempts: int = 1,
    step_b_module: str = _TEST_RUNNER_MODULE_NAME,
    step_b_function: str = "step_b",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "kind": "workflow_spec",
        "workflow_id": "demo_flow",
        "version": "1.0.0",
        "name": "Demo Flow",
        "purpose": "In-memory workflow for runner unit tests.",
        "engine": "internal_dag_runner_v1",
        "required_inputs": [
            {
                "name": "seed",
                "kind": "parameter",
                "data_type": "integer",
                "description": "Starting value fed into step_a.",
            }
        ],
        "runtime": {
            "provided_inputs": ["seed"],
            "generated_state": ["run_id", "created_at"],
            "state_artifact": "workflow_run",
            "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
        },
        "outputs": [
            {
                "name": "final",
                "kind": "value",
                "description": "Result from step_b.",
                "source": {"step_id": "step_b", "output_name": "value"},
            }
        ],
        "steps": [
            {
                "id": "step_a",
                "label": "First step",
                "executor": {
                    "executor_type": "python",
                    "module": _TEST_RUNNER_MODULE_NAME,
                    "function": "step_a",
                },
                "inputs": [
                    {
                        "name": "seed",
                        "source": {"source_type": "workflow_input", "input_name": "seed"},
                    }
                ],
                "outputs": [
                    {"name": "doubled", "kind": "value", "description": "2 * seed."}
                ],
                "prerequisites": [],
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                "failure_policy": "fail_workflow",
            },
            {
                "id": "step_b",
                "label": "Second step",
                "executor": {
                    "executor_type": "python",
                    "module": step_b_module,
                    "function": step_b_function,
                },
                "inputs": [
                    {
                        "name": "prior",
                        "source": {
                            "source_type": "step_output",
                            "step_id": "step_a",
                            "output_name": "doubled",
                        },
                    }
                ],
                "outputs": [
                    {"name": "value", "kind": "value", "description": "Final value."}
                ],
                "prerequisites": ["step_a"],
                "retry_policy": {"max_attempts": max_attempts, "backoff_seconds": 0},
                "failure_policy": failure_policy,
            },
        ],
    }


def _minimal_spec(**kwargs: Any) -> WorkflowSpec:
    return validate_workflow_spec_payload(_minimal_spec_payload(**kwargs))


def test_run_workflow_emits_started_and_ended_for_each_step(
    _inprocess_runner_module: ModuleType, tmp_path: Path
) -> None:
    _register_step(_inprocess_runner_module, "step_a", lambda inputs, ctx: {"doubled": inputs["seed"] * 2})
    _register_step(_inprocess_runner_module, "step_b", lambda inputs, ctx: {"value": inputs["prior"] + 1})

    events: list[dict[str, Any]] = []
    result = run_workflow(
        _minimal_spec(),
        inputs={"seed": 5},
        base_dir=tmp_path,
        run_id="wf-run-1",
        emit=events.append,
    )

    assert result.status == "ok"
    assert [o.status for o in result.step_outcomes] == ["ok", "ok"]
    assert result.step_outcomes[-1].outputs == {"value": 11}

    types = [event["type"] for event in events]
    assert types == [
        "workflow_step_started",
        "workflow_step_ended",
        "workflow_step_started",
        "workflow_step_ended",
    ]

    # Every emitted event must validate against the RuntimeEvent union — the
    # runner is wire-correct by construction, not by hand-rolled shapes.
    for payload in events:
        validated = build_runtime_event(payload)
        assert validated.type == payload["type"]

    started_a, ended_a, started_b, ended_b = events
    assert started_a["step_id"] == "step_a"
    assert started_a["step_index"] == 1
    assert started_a["total_steps"] == 2
    assert started_a["label"] == "First step"
    assert started_a["attempt"] == 1
    assert ended_a["outputs"] == {"doubled": 10}
    assert ended_b["outputs"] == {"value": 11}
    assert ended_b["step_index"] == 2


def test_run_workflow_emits_failed_and_aborts_on_fail_workflow(
    _inprocess_runner_module: ModuleType, tmp_path: Path
) -> None:
    _register_step(_inprocess_runner_module, "step_a", lambda inputs, ctx: {"doubled": inputs["seed"] * 2})

    def boom(inputs: dict[str, Any], ctx: Any) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    _register_step(_inprocess_runner_module, "step_b", boom)

    events: list[dict[str, Any]] = []
    result = run_workflow(
        _minimal_spec(),
        inputs={"seed": 1},
        base_dir=tmp_path,
        run_id="wf-run-2",
        emit=events.append,
    )

    assert result.status == "failed"
    assert [o.status for o in result.step_outcomes] == ["ok", "failed"]
    failed_outcome = result.step_outcomes[1]
    assert failed_outcome.error is not None
    assert "kaboom" in failed_outcome.error

    types = [event["type"] for event in events]
    assert types == [
        "workflow_step_started",
        "workflow_step_ended",
        "workflow_step_started",
        "workflow_step_failed",
    ]
    failed_event = events[-1]
    assert failed_event["step_id"] == "step_b"
    assert failed_event["failure_policy"] == "fail_workflow"
    assert "kaboom" in failed_event["error"]


def test_run_workflow_retries_until_max_attempts_then_emits_failed(
    _inprocess_runner_module: ModuleType, tmp_path: Path
) -> None:
    _register_step(_inprocess_runner_module, "step_a", lambda inputs, ctx: {"doubled": inputs["seed"] * 2})

    def flaky(inputs: dict[str, Any], ctx: Any) -> dict[str, Any]:
        raise ValueError("flake")

    _register_step(_inprocess_runner_module, "step_b", flaky)

    events: list[dict[str, Any]] = []
    result = run_workflow(
        _minimal_spec(max_attempts=3),
        inputs={"seed": 2},
        base_dir=tmp_path,
        run_id="wf-run-3",
        emit=events.append,
    )

    assert result.status == "failed"
    started_events = [event for event in events if event["type"] == "workflow_step_started" and event["step_id"] == "step_b"]
    failed_events = [event for event in events if event["type"] == "workflow_step_failed"]

    # 3 starts for step_b (one per attempt) but only a single terminal failed
    # event — intermediate attempts stay silent so the UI sees one outcome.
    assert [event["attempt"] for event in started_events] == [1, 2, 3]
    assert len(failed_events) == 1
    assert failed_events[0]["attempt"] == 3


def test_run_workflow_continues_after_continue_with_warning_step_failure(
    _inprocess_runner_module: ModuleType, tmp_path: Path
) -> None:
    _register_step(_inprocess_runner_module, "step_a", lambda inputs, ctx: (_ for _ in ()).throw(RuntimeError("oops")))
    _register_step(_inprocess_runner_module, "step_b", lambda inputs, ctx: {"value": 99})

    payload = _minimal_spec_payload()
    # Break the prerequisite link so step_b can still run when step_a aborts,
    # and relax step_a's failure_policy so the workflow keeps going.
    payload["steps"][0]["failure_policy"] = "continue_with_warning"
    payload["steps"][1]["inputs"] = [
        {
            "name": "prior",
            "source": {"source_type": "literal", "value": 42},
        }
    ]
    payload["steps"][1]["prerequisites"] = []
    spec = validate_workflow_spec_payload(payload)

    events: list[dict[str, Any]] = []
    result = run_workflow(
        spec,
        inputs={"seed": 0},
        base_dir=tmp_path,
        run_id="wf-run-4",
        emit=events.append,
    )

    assert result.status == "failed"
    assert [o.status for o in result.step_outcomes] == ["failed", "ok"]
    types = [event["type"] for event in events]
    assert types == [
        "workflow_step_started",
        "workflow_step_failed",
        "workflow_step_started",
        "workflow_step_ended",
    ]


def test_run_workflow_rejects_non_python_executor(
    _inprocess_runner_module: ModuleType, tmp_path: Path
) -> None:
    payload = _minimal_spec_payload()
    payload["steps"][0]["executor"] = {"executor_type": "tool", "tool_name": "slurm_tool"}
    spec = validate_workflow_spec_payload(payload)

    events: list[dict[str, Any]] = []
    result = run_workflow(
        spec,
        inputs={"seed": 0},
        base_dir=tmp_path,
        run_id="wf-run-5",
        emit=events.append,
    )

    assert result.status == "failed"
    failed = [event for event in events if event["type"] == "workflow_step_failed"]
    assert len(failed) == 1
    assert "python executors" in failed[0]["error"]
