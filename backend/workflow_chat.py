"""Helpers for deterministic chat-triggered workflow execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifacts import SCHEMA_PACK_VERSION, WorkflowRun, normalize_identifier, prepare_run_directory
from artifacts.naming import build_run_directory, generate_run_id
from artifacts.schemas import WorkflowStepRecord
from workflow_runner import InternalDAGRunner, WorkflowRunResult
from workflow_specs import WorkflowInputDefinition, WorkflowSpec, load_workflow_spec
from workflow_streaming import WORKFLOW_EVENT_CONTRACT_VERSION, normalize_workflow_stream_event

_VALUE_TOKEN_RE = r"(?P<value>[A-Za-z0-9._/\-]+)"
_ATTACHMENT_BINDING_RE = re.compile(r"^(?P<name>[A-Za-z0-9_ -]+)\s*(?:=|:)\s*(?P<value>.+)$")


@dataclass(frozen=True)
class PreparedWorkflowChatRun:
    spec: WorkflowSpec
    spec_path: Path
    inputs: dict[str, Any]
    blocking_reason: str | None = None


@dataclass(frozen=True)
class MaterializedBlockedWorkflowChatRun:
    result: WorkflowRunResult
    workflow_events: list[dict[str, Any]]


def prepare_selected_workflow_run(
    base_dir: Path | str,
    workflow_id: str,
    *,
    message: str,
    attached_identifiers: list[str],
) -> PreparedWorkflowChatRun:
    base_path = Path(base_dir).resolve()
    spec_path = _find_workflow_spec_path(base_path, workflow_id)
    spec = load_workflow_spec(spec_path)

    bound_attachments, positional_attachments = _partition_attachment_bindings(
        spec,
        attached_identifiers,
    )
    resolved_inputs: dict[str, Any] = {}
    missing_inputs: list[str] = []

    for definition in spec.required_inputs:
        if definition.kind in {"artifact", "template"}:
            attachment_value = _consume_attachment_for_input(
                definition.name,
                bound_attachments,
                positional_attachments,
            )
            if attachment_value is None:
                missing_inputs.append(definition.name)
                continue
            resolved_inputs[definition.name] = attachment_value
            continue

        parsed_value = _parse_input_from_message(message, definition)
        if parsed_value is None:
            missing_inputs.append(definition.name)
            continue
        resolved_inputs[definition.name] = parsed_value

    for definition in spec.optional_inputs:
        if definition.kind in {"artifact", "template"}:
            attachment_value = _consume_attachment_for_input(
                definition.name,
                bound_attachments,
                positional_attachments,
            )
            if attachment_value is not None:
                resolved_inputs[definition.name] = attachment_value
            elif definition.kind == "template" and definition.template_path is not None:
                resolved_inputs[definition.name] = definition.template_path
            continue
        parsed_value = _parse_input_from_message(message, definition)
        if parsed_value is not None:
            resolved_inputs[definition.name] = parsed_value
        elif definition.default is not None:
            resolved_inputs[definition.name] = definition.default

    blocking_reason = None
    if missing_inputs:
        blocking_reason = (
            f"Missing required workflow inputs: {', '.join(missing_inputs)}. "
            "Provide required artifacts via attached identifiers and required metadata or parameters in the message."
        )

    return PreparedWorkflowChatRun(
        spec=spec,
        spec_path=spec_path,
        inputs=resolved_inputs,
        blocking_reason=blocking_reason,
    )


def materialize_blocked_workflow_run(
    base_dir: Path | str,
    prepared: PreparedWorkflowChatRun,
    *,
    reason: str,
    now: datetime | None = None,
) -> MaterializedBlockedWorkflowChatRun:
    base_path = Path(base_dir).resolve()
    runner = InternalDAGRunner(base_path)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    layout = prepare_run_directory(
        base_path,
        prepared.spec.workflow_id,
        created_at=timestamp,
    )
    normalized_inputs = _resolve_partial_workflow_inputs(
        runner,
        prepared.spec,
        prepared.inputs,
    )
    workflow_inputs_ref = runner._persist_workflow_inputs(layout, normalized_inputs)
    input_refs = runner._build_workflow_input_refs(prepared.spec, normalized_inputs)
    parameters = {
        definition.name: normalized_inputs[definition.name]
        for definition in prepared.spec.required_inputs + prepared.spec.optional_inputs
        if definition.name in normalized_inputs and definition.kind in {"parameter", "metadata", "template"}
    }
    run_document = WorkflowRun(
        schema_version=SCHEMA_PACK_VERSION,
        artifact_type="workflow_run",
        id=normalize_identifier(f"workflow-run-{prepared.spec.workflow_id}-{layout.run_id.lower()}"),
        run_id=layout.run_id,
        created_at=layout.created_at,
        source_workflow=prepared.spec.workflow_id,
        related_artifacts=runner._dedupe_refs([*input_refs, workflow_inputs_ref]),
        workflow={"name": prepared.spec.name, "slug": layout.workflow_slug},
        lifecycle_status="blocked",
        qc_status="failed",
        engine=prepared.spec.engine,
        parameters=parameters,
        environment=runner._workflow_environment(),
        inputs=input_refs,
        outputs=[],
        steps=[
            WorkflowStepRecord(
                id=step.id,
                name=step.label,
                status="created",
                start_time=None,
                end_time=None,
                inputs_resolved=[],
                outputs_produced=[],
                warnings=[],
                errors=[],
            )
            for step in prepared.spec.steps
        ],
        provenance_exports=[],
        biocompute_exports=[],
        warnings=[reason],
    )
    persisted_run = runner._persist_run_document(layout, run_document)
    workflow_events = _build_blocked_workflow_events_for_run(
        prepared,
        reason=reason,
        run_id=layout.run_id,
        run_record_path=layout.run_record_relpath.as_posix(),
    )
    return MaterializedBlockedWorkflowChatRun(
        result=runner._build_result(layout, persisted_run, resumed=False),
        workflow_events=workflow_events,
    )


def build_blocked_workflow_events(
    prepared: PreparedWorkflowChatRun,
    *,
    reason: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    run_id = generate_run_id(now=timestamp)
    run_dir = build_run_directory(prepared.spec.workflow_id, created_at=timestamp, run_id=run_id)
    return _build_blocked_workflow_events_for_run(
        prepared,
        reason=reason,
        run_id=run_id,
        run_record_path=(run_dir / "run.json").as_posix(),
    )


def _build_blocked_workflow_events_for_run(
    prepared: PreparedWorkflowChatRun,
    *,
    reason: str,
    run_id: str,
    run_record_path: str,
) -> list[dict[str, Any]]:
    return [
        normalize_workflow_stream_event(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_start",
                "run_id": run_id,
                "workflow_id": prepared.spec.workflow_id,
                "workflow_name": prepared.spec.name,
                "lifecycle_status": "created",
                "resumed": False,
                "run_record_path": run_record_path,
            }
        ),
        normalize_workflow_stream_event(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_blocked",
                "run_id": run_id,
                "workflow_id": prepared.spec.workflow_id,
                "lifecycle_status": "blocked",
                "reason": reason,
                "stage": "before_execution",
                "blocking_source": "unknown",
                "step_id": None,
                "step_label": None,
            }
        ),
        normalize_workflow_stream_event(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_done",
                "run_id": run_id,
                "workflow_id": prepared.spec.workflow_id,
                "lifecycle_status": "blocked",
                "run_record_path": run_record_path,
                "completed_steps": 0,
                "total_steps": len(prepared.spec.steps),
                "warning_count": 1,
            }
        ),
    ]


def _partition_attachment_bindings(
    spec: WorkflowSpec,
    attached_identifiers: list[str],
) -> tuple[dict[str, str], list[str]]:
    attachment_input_names = {
        definition.name
        for definition in spec.required_inputs + spec.optional_inputs
        if definition.kind in {"artifact", "template"}
    }
    named: dict[str, str] = {}
    positional: list[str] = []
    for raw_value in attached_identifiers:
        value = str(raw_value).strip()
        if not value:
            continue
        match = _ATTACHMENT_BINDING_RE.match(value)
        if match:
            bound_name = _match_attachment_binding_name(
                match.group("name"),
                attachment_input_names,
            )
            if bound_name is not None:
                named[bound_name] = match.group("value").strip()
                continue
        positional.append(value)
    return named, positional


def _match_attachment_binding_name(raw_name: str, valid_names: set[str]) -> str | None:
    candidate = raw_name.strip().lower().replace("-", "_").replace(" ", "_")
    if candidate in valid_names:
        return candidate
    return None


def _consume_attachment_for_input(
    input_name: str,
    named_attachments: dict[str, str],
    positional_attachments: list[str],
) -> str | None:
    named_value = named_attachments.pop(input_name, None)
    if named_value is not None:
        return named_value
    if positional_attachments:
        return positional_attachments.pop(0)
    return None


def _resolve_partial_workflow_inputs(
    runner: InternalDAGRunner,
    spec: WorkflowSpec,
    provided_inputs: dict[str, Any],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for definition in spec.required_inputs + spec.optional_inputs:
        if definition.name in provided_inputs:
            value = provided_inputs[definition.name]
        elif definition.kind == "template" and definition.template_path is not None:
            value = definition.template_path
        elif definition.default is not None:
            value = definition.default
        else:
            continue
        resolved[definition.name] = runner._normalize_input_value(definition, value)
    return resolved

def describe_blocked_workflow(prepared: PreparedWorkflowChatRun, reason: str) -> str:
    return f"Workflow {prepared.spec.name} blocked before execution: {reason}"


def describe_workflow_result(prepared: PreparedWorkflowChatRun, result: WorkflowRunResult) -> str:
    lifecycle_status = result.run.lifecycle_status
    if lifecycle_status == "completed":
        return (
            f"Workflow {prepared.spec.name} completed successfully. "
            f"Run ID: {result.run.run_id}. "
            f"Completed steps: {sum(1 for step in result.run.steps if step.status == 'completed')}/{len(result.run.steps)}. "
            f"Run record: {result.artifact_relpath}."
        )
    if lifecycle_status == "blocked":
        reason = result.run.warnings[0] if result.run.warnings else "Execution was blocked."
        return f"Workflow {prepared.spec.name} blocked: {reason}"
    if lifecycle_status == "failed":
        reason = next((error for step in result.run.steps for error in step.errors), "Execution failed.")
        return f"Workflow {prepared.spec.name} failed: {reason}"
    return f"Workflow {prepared.spec.name} finished with status {lifecycle_status}."


def _find_workflow_spec_path(base_dir: Path, workflow_id: str) -> Path:
    workflows_dir = base_dir / "workflows"
    for suffix in (".yaml", ".yml", ".json"):
        candidate = workflows_dir / f"{workflow_id}{suffix}"
        if candidate.exists():
            return candidate
    raise ValueError(f"Unknown workflow spec: {workflow_id!r}")


def _parse_input_from_message(message: str, definition: WorkflowInputDefinition) -> Any | None:
    raw_value = _extract_named_value(message, definition.name)
    if raw_value is None:
        return None

    if definition.data_type == "integer":
        try:
            return int(raw_value)
        except ValueError:
            return None
    if definition.data_type == "number":
        try:
            return float(raw_value)
        except ValueError:
            return None
    if definition.data_type == "boolean":
        lowered = raw_value.lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
        return None
    return raw_value


def _extract_named_value(message: str, input_name: str) -> str | None:
    aliases = [input_name, input_name.replace("_", " ")]
    for alias in aliases:
        escaped = re.escape(alias)
        patterns = [
            rf"\b{escaped}\b\s*(?:=|:)\s*{_VALUE_TOKEN_RE}",
            rf"\b{escaped}\b\s+{_VALUE_TOKEN_RE}",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group("value")
    return None


__all__ = [
    "MaterializedBlockedWorkflowChatRun",
    "PreparedWorkflowChatRun",
    "build_blocked_workflow_events",
    "describe_blocked_workflow",
    "describe_workflow_result",
    "materialize_blocked_workflow_run",
    "prepare_selected_workflow_run",
]
