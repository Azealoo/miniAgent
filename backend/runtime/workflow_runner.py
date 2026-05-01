"""Minimal workflow step runner that drives typed step events.

Purpose of this module is narrow: iterate the declared steps of a
``WorkflowSpec``, invoke each step's Python executor, and emit the three
step-level ``RuntimeEvent`` shapes (``workflow_step_started``,
``workflow_step_ended``, ``workflow_step_failed``) through an ``emit``
callback. The emitter is transport-neutral — the SSE adapter wraps it in the
standard envelope via ``dump_runtime_event`` the same way every other runtime
event goes out.

This intentionally does NOT replicate the full DAG runner described in
``context/features/10-internal-dag-runner-mvp-spec.md``: no artifact
registration, no QC gate evaluation, no compliance hooks, no external
engines. Those land incrementally. What this module gives the system today is
the step-event stream so the UI can render live progress against any Python
workflow spec.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from workflow_specs import (
    LiteralBindingSource,
    PythonExecutor,
    StepOutputSource,
    WorkflowInputSource,
    WorkflowSpec,
    WorkflowStepDefinition,
)

EmitFn = Callable[[dict[str, Any]], None]


@dataclass
class ExecutionContext:
    """Runtime context passed to each Python step executor.

    Mirrors the attribute surface the existing runners under
    ``workflows/runners/`` already rely on (``base_dir``, ``relative_path``).
    """

    base_dir: Path
    run_id: str
    workflow_id: str
    step_id: str

    def relative_path(self, value: Any) -> str:
        raw = Path(str(value))
        if raw.is_absolute():
            try:
                return str(raw.relative_to(self.base_dir))
            except ValueError:
                return str(raw)
        return str(raw)


@dataclass
class StepOutcome:
    step_id: str
    status: Literal["ok", "failed", "skipped"]
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0
    attempts: int = 1


@dataclass
class WorkflowRunResult:
    workflow_id: str
    run_id: str
    status: Literal["ok", "failed"]
    step_outcomes: list[StepOutcome]


def _resolve_input(
    binding_source: Any,
    *,
    workflow_inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
    step_id: str,
    input_name: str,
) -> Any:
    if isinstance(binding_source, WorkflowInputSource):
        if binding_source.input_name not in workflow_inputs:
            raise KeyError(
                f"Step {step_id!r} input {input_name!r} references undefined workflow "
                f"input {binding_source.input_name!r}."
            )
        return workflow_inputs[binding_source.input_name]
    if isinstance(binding_source, StepOutputSource):
        prior = step_outputs.get(binding_source.step_id)
        if prior is None:
            raise KeyError(
                f"Step {step_id!r} input {input_name!r} references output of step "
                f"{binding_source.step_id!r} which has not produced outputs."
            )
        if binding_source.output_name not in prior:
            raise KeyError(
                f"Step {binding_source.step_id!r} did not emit output "
                f"{binding_source.output_name!r} required by {step_id!r}."
            )
        return prior[binding_source.output_name]
    if isinstance(binding_source, LiteralBindingSource):
        return binding_source.value
    raise TypeError(f"Unsupported binding source: {type(binding_source).__name__}")


def _summarize_outputs(outputs: Any) -> Optional[dict[str, Any]]:
    if outputs is None:
        return None
    if not isinstance(outputs, dict):
        return {"value": repr(outputs)[:500]}
    summary: dict[str, Any] = {}
    for key, value in outputs.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, (list, tuple, dict)):
            summary[key] = f"<{type(value).__name__} len={len(value)}>"
        else:
            summary[key] = f"<{type(value).__name__}>"
    return summary


def _load_python_executor(executor: PythonExecutor) -> Callable[..., Any]:
    module = import_module(executor.module)
    try:
        return getattr(module, executor.function)
    except AttributeError as exc:
        raise AttributeError(
            f"Module {executor.module!r} has no function {executor.function!r}."
        ) from exc


def run_workflow(
    spec: WorkflowSpec,
    inputs: dict[str, Any],
    *,
    base_dir: Path | str,
    run_id: str,
    emit: EmitFn,
) -> WorkflowRunResult:
    """Execute every step in ``spec.steps`` in declared order.

    Only ``python`` executors are supported today; spec-level validation already
    establishes that steps declare their executor type, so attempts to run a
    tool or external-engine step are reported as step failures rather than
    swallowed silently.
    """
    base_path = Path(base_dir)
    total = len(spec.steps)
    outcomes: list[StepOutcome] = []
    step_outputs: dict[str, dict[str, Any]] = {}
    workflow_status: Literal["ok", "failed"] = "ok"
    aborted = False

    for index, step in enumerate(spec.steps, start=1):
        if aborted:
            outcomes.append(StepOutcome(step_id=step.id, status="skipped"))
            continue

        outcome = _execute_step(
            step,
            spec=spec,
            step_index=index,
            total_steps=total,
            workflow_inputs=inputs,
            step_outputs=step_outputs,
            base_dir=base_path,
            run_id=run_id,
            emit=emit,
        )
        outcomes.append(outcome)

        if outcome.status == "ok":
            step_outputs[step.id] = outcome.outputs
            continue

        workflow_status = "failed"
        if step.failure_policy in ("fail_workflow", "block_workflow"):
            aborted = True
        # continue_with_warning: keep iterating.

    return WorkflowRunResult(
        workflow_id=spec.workflow_id,
        run_id=run_id,
        status=workflow_status,
        step_outcomes=outcomes,
    )


def _execute_step(
    step: WorkflowStepDefinition,
    *,
    spec: WorkflowSpec,
    step_index: int,
    total_steps: int,
    workflow_inputs: dict[str, Any],
    step_outputs: dict[str, dict[str, Any]],
    base_dir: Path,
    run_id: str,
    emit: EmitFn,
) -> StepOutcome:
    max_attempts = step.retry_policy.max_attempts
    last_error: Optional[str] = None
    last_duration_ms = 0

    for attempt in range(1, max_attempts + 1):
        emit(
            {
                "type": "workflow_step_started",
                "workflow_id": spec.workflow_id,
                "run_id": run_id,
                "step_id": step.id,
                "step_index": step_index,
                "total_steps": total_steps,
                "label": step.label,
                "attempt": attempt,
            }
        )

        start_ns = time.perf_counter_ns()
        try:
            resolved_inputs = {
                binding.name: _resolve_input(
                    binding.source,
                    workflow_inputs=workflow_inputs,
                    step_outputs=step_outputs,
                    step_id=step.id,
                    input_name=binding.name,
                )
                for binding in step.inputs
            }

            if not isinstance(step.executor, PythonExecutor):
                raise NotImplementedError(
                    f"workflow_runner only supports python executors; step {step.id!r} "
                    f"declares {step.executor.executor_type!r}."
                )

            executor_fn = _load_python_executor(step.executor)
            context = ExecutionContext(
                base_dir=base_dir,
                run_id=run_id,
                workflow_id=spec.workflow_id,
                step_id=step.id,
            )
            outputs = executor_fn(resolved_inputs, context)
        except Exception as exc:  # noqa: BLE001 — surface any runner failure as an event
            last_duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)
            last_error = f"{type(exc).__name__}: {exc}"
            terminal = attempt == max_attempts
            if terminal:
                emit(
                    {
                        "type": "workflow_step_failed",
                        "workflow_id": spec.workflow_id,
                        "run_id": run_id,
                        "step_id": step.id,
                        "step_index": step_index,
                        "total_steps": total_steps,
                        "duration_ms": last_duration_ms,
                        "error": last_error,
                        "failure_policy": step.failure_policy,
                        "attempt": attempt,
                    }
                )
                return StepOutcome(
                    step_id=step.id,
                    status="failed",
                    error=last_error,
                    duration_ms=last_duration_ms,
                    attempts=attempt,
                )
            # Non-terminal failure: swallow so the retry loop re-emits a new
            # workflow_step_started for the next attempt. We don't emit a
            # ``workflow_step_failed`` for intermediate attempts — the stream
            # stays clean and only the terminal outcome is reported.
            continue

        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)
        outputs_dict = outputs if isinstance(outputs, dict) else {}
        emit(
            {
                "type": "workflow_step_ended",
                "workflow_id": spec.workflow_id,
                "run_id": run_id,
                "step_id": step.id,
                "step_index": step_index,
                "total_steps": total_steps,
                "duration_ms": duration_ms,
                "outputs": _summarize_outputs(outputs_dict),
            }
        )
        return StepOutcome(
            step_id=step.id,
            status="ok",
            outputs=outputs_dict,
            duration_ms=duration_ms,
            attempts=attempt,
        )

    # Unreachable: loop either returns on success or on terminal failure.
    return StepOutcome(
        step_id=step.id,
        status="failed",
        error=last_error,
        duration_ms=last_duration_ms,
        attempts=max_attempts,
    )
