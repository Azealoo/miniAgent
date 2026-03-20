"""Internal DAG workflow runner with durable on-disk state."""

from __future__ import annotations

import importlib
import inspect
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Any, Callable, Mapping

import yaml

from artifacts import (
    ArtifactReference,
    DatasetManifest,
    RunLayout,
    SCHEMA_PACK_VERSION,
    WorkflowRun,
    build_content_hash_manifest,
    build_generated_output_relpath,
    build_user_supplied_relpath,
    load_artifact_document,
    normalize_identifier,
    prepare_run_directory,
    resolve_artifact_path,
    schema_format_for_artifact,
    stable_artifact_name,
    validate_artifact_payload,
    validate_artifact_root,
)
from artifacts.schemas import (
    WorkflowEnvironment,
    WorkflowIssueDetail,
    WorkflowStepRecord,
    WorkflowSummaryMetric,
)
from qc_policy import QCPolicyDefinition, QCPolicyEvaluation, evaluate_qc_policy
from workflow_specs import (
    ExternalEngineExecutor,
    LiteralBindingSource,
    PythonExecutor,
    StepOutputSource,
    WorkflowInputDefinition,
    WorkflowInputSource,
    WorkflowOutputDefinition,
    WorkflowSpec,
    WorkflowStepDefinition,
    load_workflow_spec,
)
from workflow_streaming import WORKFLOW_EVENT_CONTRACT_VERSION, normalize_workflow_stream_event

_RUN_FINAL_STATUSES = {"completed", "failed", "blocked"}
_STEP_READY_STATUS = {"created", "waiting"}
_STEP_COMPLETE_STATUS = "completed"
_WORKFLOW_INPUT_SNAPSHOT_NAME = "workflow_inputs.json"
_STEP_INPUT_SNAPSHOT_NAME = "resolved_inputs.json"
_STEP_OUTPUT_SNAPSHOT_NAME = "resolved_outputs.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _dump_yaml(payload: Any) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def _module_prefixes(module_name: str) -> list[str]:
    parts = module_name.split(".")
    return [".".join(parts[:index]) for index in range(1, len(parts) + 1)]


def _serialize_for_json(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        return _isoformat_z(value)
    if isinstance(value, ArtifactReference):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _serialize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_for_json(item) for item in value]
    return value


def _workflow_issue_detail_from_object(issue: Any) -> WorkflowIssueDetail | None:
    if isinstance(issue, Mapping):
        code = issue.get("code")
        message = issue.get("message")
        field_path = issue.get("field_path")
        path = issue.get("path")
    else:
        code = getattr(issue, "code", None)
        message = getattr(issue, "message", None)
        field_path = getattr(issue, "field_path", None)
        path = getattr(issue, "path", None)

    if not isinstance(code, str) or not code.strip():
        return None
    if not isinstance(message, str) or not message.strip():
        return None
    if field_path is not None and not isinstance(field_path, str):
        field_path = str(field_path)
    if path is not None and not isinstance(path, str):
        path = str(path)
    return WorkflowIssueDetail(
        code=code,
        message=message,
        field_path=field_path,
        path=path,
    )


def _dedupe_workflow_issue_details(details: list[WorkflowIssueDetail]) -> list[WorkflowIssueDetail]:
    deduped: list[WorkflowIssueDetail] = []
    seen: set[tuple[str, str | None, str, str | None]] = set()
    for detail in details:
        key = (detail.code, detail.field_path, detail.message, detail.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(detail)
    return deduped


def _workflow_issue_details_from_exception(exc: Exception) -> list[WorkflowIssueDetail]:
    result = getattr(exc, "result", None)
    raw_issues = getattr(result, "issues", None)
    if not isinstance(raw_issues, list):
        return []
    details = [
        detail
        for issue in raw_issues
        if (detail := _workflow_issue_detail_from_object(issue)) is not None
    ]
    return _dedupe_workflow_issue_details(details)


def _workflow_issue_details_from_qc_policy_evaluation(
    evaluation: QCPolicyEvaluation,
) -> list[WorkflowIssueDetail]:
    details: list[WorkflowIssueDetail] = []
    for check in evaluation.checks:
        if check.status == "pass":
            continue
        details.append(
            WorkflowIssueDetail(
                code=f"qc-policy-{check.status}",
                message=f"{evaluation.policy_id} {check.category}: {check.message}",
                field_path=check.metric_name,
                path=check.source_artifact.path if check.source_artifact is not None else None,
            )
        )
    return _dedupe_workflow_issue_details(details)


@dataclass(frozen=True)
class StepExecutionContext:
    base_dir: Path
    run_dir: Path
    relative_run_dir: PurePosixPath
    run_id: str
    created_at: datetime
    workflow_id: str
    step_id: str

    def resolve_path(self, value: str | Path) -> Path:
        raw_path = Path(str(value))
        if raw_path.is_absolute():
            return raw_path.resolve()
        return (self.base_dir / raw_path).resolve()

    def relative_path(self, value: str | Path) -> str:
        target = self.resolve_path(value)
        return target.relative_to(self.base_dir).as_posix()


@dataclass(frozen=True)
class WorkflowRunResult:
    run: WorkflowRun
    artifact_path: Path
    artifact_relpath: str
    run_dir: Path
    resumed: bool = False


WorkflowEventCallback = Callable[[dict[str, Any]], None]


def _workflow_artifact_payload(ref: ArtifactReference) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_type": ref.artifact_type,
        "path": ref.path,
    }
    if ref.id is not None:
        payload["id"] = ref.id
    if ref.run_id is not None:
        payload["run_id"] = ref.run_id
    return payload


@dataclass(frozen=True)
class _WorkflowRunStreamEmitter:
    spec: WorkflowSpec
    layout: RunLayout
    callback: WorkflowEventCallback | None = None

    def _emit(self, payload: dict[str, Any]) -> None:
        if self.callback is None:
            return
        self.callback(normalize_workflow_stream_event(payload))

    def start(self, *, resumed: bool, lifecycle_status: str) -> None:
        self._emit(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_start",
                "run_id": self.layout.run_id,
                "workflow_id": self.spec.workflow_id,
                "workflow_name": self.spec.name,
                "lifecycle_status": lifecycle_status,
                "resumed": resumed,
                "run_record_path": self.layout.run_record_relpath.as_posix(),
            }
        )

    def step_start(self, step: WorkflowStepDefinition) -> None:
        engine_name = step.executor.engine_name if isinstance(step.executor, ExternalEngineExecutor) else None
        self._emit(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_step_start",
                "run_id": self.layout.run_id,
                "workflow_id": self.spec.workflow_id,
                "step_id": step.id,
                "step_label": step.label,
                "status": "running",
                "executor_type": step.executor.executor_type,
                "prerequisite_step_ids": list(step.prerequisites),
                "engine_name": engine_name,
            }
        )

    def step_end(self, step: WorkflowStepDefinition, record: WorkflowStepRecord) -> None:
        self._emit(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_step_end",
                "run_id": self.layout.run_id,
                "workflow_id": self.spec.workflow_id,
                "step_id": step.id,
                "step_label": step.label,
                "status": record.status,
                "artifact_refs": [_workflow_artifact_payload(ref) for ref in record.outputs_produced],
                "warnings": list(record.warnings),
                "warning_details": [detail.model_dump(mode="json") for detail in record.warning_details],
                "errors": list(record.errors),
                "error_details": [detail.model_dump(mode="json") for detail in record.error_details],
            }
        )

    def blocked(
        self,
        *,
        reason: str,
        issue_details: list[WorkflowIssueDetail] | None = None,
        stage: str,
        blocking_source: str,
        step: WorkflowStepDefinition | None,
    ) -> None:
        self._emit(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_blocked",
                "run_id": self.layout.run_id,
                "workflow_id": self.spec.workflow_id,
                "lifecycle_status": "blocked",
                "reason": reason,
                "issue_details": [detail.model_dump(mode="json") for detail in issue_details or []],
                "stage": stage,
                "blocking_source": blocking_source,
                "step_id": step.id if step is not None else None,
                "step_label": step.label if step is not None else None,
            }
        )

    def artifact(
        self,
        ref: ArtifactReference,
        *,
        scope: str,
        step: WorkflowStepDefinition | None = None,
        output_name: str | None = None,
    ) -> None:
        self._emit(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_artifact",
                "run_id": self.layout.run_id,
                "workflow_id": self.spec.workflow_id,
                "artifact": _workflow_artifact_payload(ref),
                "scope": scope,
                "step_id": step.id if step is not None else None,
                "step_label": step.label if step is not None else None,
                "output_name": output_name,
            }
        )

    def done(self, run_document: WorkflowRun) -> None:
        completed_steps = sum(1 for record in run_document.steps if record.status == "completed")
        warning_count = len(run_document.warnings) + sum(len(record.warnings) for record in run_document.steps)
        self._emit(
            {
                "contract_version": WORKFLOW_EVENT_CONTRACT_VERSION,
                "type": "workflow_done",
                "run_id": self.layout.run_id,
                "workflow_id": self.spec.workflow_id,
                "lifecycle_status": run_document.lifecycle_status,
                "run_record_path": self.layout.run_record_relpath.as_posix(),
                "completed_steps": completed_steps,
                "total_steps": len(run_document.steps),
                "warning_count": warning_count,
            }
        )


class InternalDAGRunner:
    """Execute explicit workflow DAGs without hidden in-memory state."""

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir).resolve()

    def run(
        self,
        workflow: WorkflowSpec | Path | str,
        inputs: Mapping[str, Any] | None = None,
        *,
        run_dir: Path | str | None = None,
        restart_from_step: str | None = None,
        step_limit: int | None = None,
        created_at: datetime | None = None,
        event_callback: WorkflowEventCallback | None = None,
    ) -> WorkflowRunResult:
        if step_limit is not None and step_limit < 1:
            raise ValueError("step_limit must be at least 1 when provided.")
        if restart_from_step is not None and run_dir is None:
            raise ValueError("restart_from_step requires run_dir for an existing workflow run.")

        spec = self._load_workflow_spec(workflow)
        if run_dir is None:
            layout = prepare_run_directory(
                self.base_dir,
                spec.workflow_id,
                created_at=created_at or _utcnow(),
                artifact_root=validate_artifact_root("artifacts"),
            )
            resolved_inputs = self._resolve_workflow_inputs(spec, inputs or {})
            workflow_inputs_ref = self._persist_workflow_inputs(layout, resolved_inputs)
            run_document = self._build_initial_run_document(
                spec=spec,
                layout=layout,
                resolved_inputs=resolved_inputs,
                workflow_inputs_ref=workflow_inputs_ref,
            )
            run_document = self._persist_run_document(layout, run_document)
            resumed = False
        else:
            layout = self._load_existing_layout(spec, Path(run_dir))
            run_document = self._load_run_document(layout)
            layout = RunLayout(
                base_dir=layout.base_dir,
                workflow=layout.workflow,
                workflow_slug=layout.workflow_slug,
                run_id=layout.run_id,
                created_at=run_document.created_at,
                artifact_root=layout.artifact_root,
                relative_run_dir=layout.relative_run_dir,
                run_dir=layout.run_dir,
            )
            resolved_inputs = self._load_workflow_inputs(layout, spec, inputs)
            workflow_inputs_ref = self._workflow_inputs_ref(layout)
            run_document = self._prepare_resume_document(spec, layout, run_document, workflow_inputs_ref)
            if restart_from_step is not None:
                run_document = self._prepare_restart_document(layout, spec, run_document, restart_from_step)
            run_document = self._persist_run_document(layout, run_document)
            resumed = True

        emitter = _WorkflowRunStreamEmitter(spec=spec, layout=layout, callback=event_callback)
        emitter.start(resumed=resumed, lifecycle_status=run_document.lifecycle_status)
        emitter.artifact(self._run_record_ref(layout), scope="run_record")

        if run_document.lifecycle_status in _RUN_FINAL_STATUSES:
            emitter.done(run_document)
            return self._build_result(layout, run_document, resumed=resumed)

        step_output_values, step_output_refs = self._load_completed_step_outputs(layout, spec, run_document)
        run_document = self._apply_stage_policies(
            layout=layout,
            spec=spec,
            run_document=run_document,
            resolved_inputs=resolved_inputs,
            step_output_values=step_output_values,
            step_output_refs=step_output_refs,
            stage="before_execution",
            current_step=None,
            emitter=emitter,
        )
        if run_document.lifecycle_status in _RUN_FINAL_STATUSES:
            run_document = self._sync_workflow_outputs(
                layout,
                spec,
                run_document,
                step_output_values,
                step_output_refs,
                materialize_final_artifacts=True,
                emitter=None,
            )
            run_document = self._sync_related_artifacts(run_document, workflow_inputs_ref)
            run_document = self._sync_qc_status(run_document)
            run_document = self._persist_run_document(layout, run_document)
            emitter.done(run_document)
            return self._build_result(layout, run_document, resumed=resumed)

        run_document.lifecycle_status = "preflight_checked"
        run_document = self._sync_workflow_outputs(
            layout,
            spec,
            run_document,
            step_output_values,
            step_output_refs,
            materialize_final_artifacts=False,
            emitter=None,
        )
        run_document = self._sync_related_artifacts(run_document, workflow_inputs_ref)
        run_document = self._sync_qc_status(run_document)
        run_document = self._persist_run_document(layout, run_document)

        executed_steps = 0
        while True:
            if step_limit is not None and executed_steps >= step_limit:
                run_document.lifecycle_status = "waiting"
                run_document = self._sync_qc_status(run_document)
                run_document = self._persist_run_document(layout, run_document)
                break

            step = self._next_ready_step(spec, run_document)
            if step is None:
                break

            run_document.lifecycle_status = "running"
            run_document = self._persist_run_document(layout, run_document)
            run_document = self._execute_step(
                layout=layout,
                spec=spec,
                run_document=run_document,
                resolved_inputs=resolved_inputs,
                step=step,
                step_output_values=step_output_values,
                step_output_refs=step_output_refs,
                emitter=emitter,
            )
            run_document = self._sync_workflow_outputs(
                layout,
                spec,
                run_document,
                step_output_values,
                step_output_refs,
                materialize_final_artifacts=run_document.lifecycle_status in _RUN_FINAL_STATUSES,
                emitter=None,
            )
            run_document = self._sync_related_artifacts(run_document, workflow_inputs_ref)
            run_document = self._sync_qc_status(run_document)
            run_document = self._persist_run_document(layout, run_document)
            executed_steps += 1

            if run_document.lifecycle_status in _RUN_FINAL_STATUSES:
                break

        if run_document.lifecycle_status not in _RUN_FINAL_STATUSES:
            if self._all_steps_completed(run_document):
                run_document = self._apply_stage_policies(
                    layout=layout,
                    spec=spec,
                    run_document=run_document,
                    resolved_inputs=resolved_inputs,
                    step_output_values=step_output_values,
                    step_output_refs=step_output_refs,
                    stage="before_publish",
                    current_step=None,
                    emitter=emitter,
                )
                if run_document.lifecycle_status not in _RUN_FINAL_STATUSES:
                    run_document = self._sync_workflow_outputs(
                        layout,
                        spec,
                        run_document,
                        step_output_values,
                        step_output_refs,
                        materialize_final_artifacts=True,
                        emitter=emitter,
                    )
                    run_document = self._sync_related_artifacts(run_document, workflow_inputs_ref)
                    run_document.lifecycle_status = "completed"
            else:
                run_document.lifecycle_status = "waiting"
            run_document = self._sync_qc_status(run_document)
            run_document = self._persist_run_document(layout, run_document)

        emitter.done(run_document)
        return self._build_result(layout, run_document, resumed=resumed)

    def _load_workflow_spec(self, workflow: WorkflowSpec | Path | str) -> WorkflowSpec:
        if isinstance(workflow, WorkflowSpec):
            return workflow
        return load_workflow_spec(Path(workflow))

    def _resolve_workflow_inputs(
        self,
        spec: WorkflowSpec,
        provided_inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        definitions = {definition.name: definition for definition in spec.required_inputs + spec.optional_inputs}
        unknown_inputs = sorted(set(provided_inputs) - set(definitions))
        if unknown_inputs:
            raise ValueError(f"Unknown workflow inputs: {', '.join(unknown_inputs)}.")

        resolved: dict[str, Any] = {}
        missing_required: list[str] = []
        for definition in spec.required_inputs + spec.optional_inputs:
            if definition.name in provided_inputs:
                value = provided_inputs[definition.name]
            elif definition.kind == "template" and definition.template_path is not None:
                value = definition.template_path
            elif definition.default is not None:
                value = definition.default
            elif definition in spec.required_inputs:
                missing_required.append(definition.name)
                continue
            else:
                continue
            resolved[definition.name] = self._normalize_input_value(definition, value)

        if missing_required:
            raise ValueError(f"Missing required workflow inputs: {', '.join(missing_required)}.")

        return resolved

    def _normalize_input_value(self, definition: WorkflowInputDefinition, value: Any) -> Any:
        if definition.kind in {"artifact", "template"}:
            return self._coerce_project_relative_path(value)
        return value

    def _coerce_project_relative_path(self, value: Any) -> str:
        if isinstance(value, Mapping) and "path" in value:
            value = value["path"]

        candidate = Path(str(value))
        if candidate.is_absolute():
            resolved = candidate.resolve()
            try:
                return resolved.relative_to(self.base_dir).as_posix()
            except ValueError as exc:
                raise ValueError(f"Path {resolved} must stay under {self.base_dir}.") from exc

        normalized = PurePosixPath(str(value))
        if normalized.is_absolute():
            raise ValueError(f"Path {value!r} must stay relative to the project root.")
        if any(part == ".." for part in normalized.parts):
            raise ValueError(f"Path {value!r} must not escape the project root.")
        return normalized.as_posix()

    def _persist_workflow_inputs(self, layout: RunLayout, resolved_inputs: Mapping[str, Any]) -> ArtifactReference:
        relative_path = build_user_supplied_relpath(_WORKFLOW_INPUT_SNAPSHOT_NAME, slot="workflow-inputs")
        target = layout.user_input_path(_WORKFLOW_INPUT_SNAPSHOT_NAME, slot="workflow-inputs")
        payload = {
            "workflow_id": layout.workflow,
            "run_id": layout.run_id,
            "resolved_inputs": _serialize_for_json(dict(resolved_inputs)),
        }
        target.write_text(_dump_json(payload), encoding="utf-8")
        return ArtifactReference(
            artifact_type="workflow_input_bundle",
            path=(layout.relative_run_dir / relative_path).as_posix(),
            id=normalize_identifier(f"workflow-inputs-{layout.workflow}-{layout.run_id.lower()}"),
            run_id=layout.run_id,
        )

    def _workflow_inputs_ref(self, layout: RunLayout) -> ArtifactReference:
        relative_path = build_user_supplied_relpath(_WORKFLOW_INPUT_SNAPSHOT_NAME, slot="workflow-inputs")
        return ArtifactReference(
            artifact_type="workflow_input_bundle",
            path=(layout.relative_run_dir / relative_path).as_posix(),
            id=normalize_identifier(f"workflow-inputs-{layout.workflow}-{layout.run_id.lower()}"),
            run_id=layout.run_id,
        )

    def _load_workflow_inputs(
        self,
        layout: RunLayout,
        spec: WorkflowSpec,
        provided_inputs: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        snapshot_ref = self._workflow_inputs_ref(layout)
        snapshot_path = resolve_artifact_path(self.base_dir, snapshot_ref.path)
        if snapshot_path.exists():
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            loaded = payload.get("resolved_inputs")
            if not isinstance(loaded, dict):
                raise ValueError("Workflow input snapshot must include a resolved_inputs mapping.")
            return loaded
        if provided_inputs is None:
            raise ValueError("Cannot resume workflow run without a persisted workflow input snapshot.")
        return self._resolve_workflow_inputs(spec, provided_inputs)

    def _build_initial_run_document(
        self,
        *,
        spec: WorkflowSpec,
        layout: RunLayout,
        resolved_inputs: Mapping[str, Any],
        workflow_inputs_ref: ArtifactReference,
    ) -> WorkflowRun:
        run_ref = self._run_record_ref(layout)
        inputs = self._build_workflow_input_refs(spec, resolved_inputs)
        parameters = {
            definition.name: resolved_inputs[definition.name]
            for definition in spec.required_inputs + spec.optional_inputs
            if definition.name in resolved_inputs and definition.kind in {"parameter", "metadata", "template"}
        }
        related_artifacts = self._dedupe_refs([*inputs, workflow_inputs_ref])
        return WorkflowRun(
            schema_version=SCHEMA_PACK_VERSION,
            artifact_type="workflow_run",
            id=normalize_identifier(f"workflow-run-{spec.workflow_id}-{layout.run_id.lower()}"),
            run_id=layout.run_id,
            created_at=layout.created_at,
            source_workflow=spec.workflow_id,
            related_artifacts=related_artifacts,
            workflow={"name": spec.name, "slug": layout.workflow_slug},
            lifecycle_status="created",
            qc_status="pending",
            engine=spec.engine,
            parameters=_serialize_for_json(parameters),
            environment=self._workflow_environment(),
            inputs=inputs,
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
                for step in spec.steps
            ],
            provenance_exports=[],
            summary_metrics=[],
            warnings=[],
        )

    def _workflow_environment(self) -> WorkflowEnvironment:
        conda_env = os.environ.get("CONDA_DEFAULT_ENV")
        if not conda_env and os.environ.get("CONDA_PREFIX"):
            conda_env = Path(os.environ["CONDA_PREFIX"]).name
        return WorkflowEnvironment(
            conda_env=conda_env,
            platform=platform.system().lower(),
            python_version=platform.python_version(),
            hostname=socket.gethostname(),
        )

    def _build_workflow_input_refs(
        self,
        spec: WorkflowSpec,
        resolved_inputs: Mapping[str, Any],
    ) -> list[ArtifactReference]:
        refs: list[ArtifactReference] = []
        for definition in spec.required_inputs + spec.optional_inputs:
            if definition.name not in resolved_inputs:
                continue
            value = resolved_inputs[definition.name]
            if definition.kind == "artifact":
                refs.append(
                    ArtifactReference(
                        artifact_type=definition.artifact_type or "artifact",
                        path=self._coerce_project_relative_path(value),
                    )
                )
            elif definition.kind == "template":
                refs.append(
                    ArtifactReference(
                        artifact_type="template",
                        path=self._coerce_project_relative_path(value),
                    )
                )
        return refs

    def _load_existing_layout(self, spec: WorkflowSpec, run_dir: Path) -> RunLayout:
        run_path = run_dir.resolve()
        try:
            relative_run_dir = PurePosixPath(run_path.relative_to(self.base_dir).as_posix())
        except ValueError as exc:
            raise ValueError(f"Run directory {run_path} must stay under {self.base_dir}.") from exc
        if len(relative_run_dir.parts) < 4:
            raise ValueError(f"Run directory {run_path} is not a valid BioAPEX run path.")
        return RunLayout(
            base_dir=self.base_dir,
            workflow=spec.workflow_id,
            workflow_slug=relative_run_dir.parts[1],
            run_id=relative_run_dir.parts[-1],
            created_at=_utcnow(),
            artifact_root=PurePosixPath(relative_run_dir.parts[0]),
            relative_run_dir=relative_run_dir,
            run_dir=run_path,
        )

    def _load_run_document(self, layout: RunLayout) -> WorkflowRun:
        document = load_artifact_document(layout.run_record_path)
        if not isinstance(document, WorkflowRun):
            raise ValueError(f"Expected workflow_run artifact at {layout.run_record_path}.")
        return document

    def _prepare_resume_document(
        self,
        spec: WorkflowSpec,
        layout: RunLayout,
        run_document: WorkflowRun,
        workflow_inputs_ref: ArtifactReference,
    ) -> WorkflowRun:
        if run_document.workflow.slug != layout.workflow_slug:
            raise ValueError(
                f"Run {layout.run_id} belongs to workflow slug {run_document.workflow.slug!r}, not {layout.workflow_slug!r}."
            )
        if {record.id for record in run_document.steps} != {step.id for step in spec.steps}:
            raise ValueError("Persisted run steps do not match the current workflow spec.")
        for record in run_document.steps:
            if record.status == "running":
                record.status = "waiting"
                record.end_time = None
                warning = "Step was in running state during resume and was re-queued."
                if warning not in record.warnings:
                    record.warnings.append(warning)
        if run_document.lifecycle_status == "running":
            run_document.lifecycle_status = "waiting"
            if "Run resumed after interruption." not in run_document.warnings:
                run_document.warnings.append("Run resumed after interruption.")
        run_document.related_artifacts = self._dedupe_refs([*run_document.related_artifacts, workflow_inputs_ref])
        return run_document

    def _prepare_restart_document(
        self,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        restart_from_step: str,
    ) -> WorkflowRun:
        step_ids = {step.id for step in spec.steps}
        if restart_from_step not in step_ids:
            raise ValueError(
                f"restart_from_step {restart_from_step!r} was not found in workflow {spec.workflow_id!r}."
            )

        reset_steps = {restart_from_step, *self._descendants(spec, restart_from_step)}
        stale_ref_keys = self._stale_restart_ref_keys(layout, spec, run_document, reset_steps=reset_steps)
        self._delete_materialized_workflow_outputs(layout, spec, reset_steps=reset_steps)
        for record in run_document.steps:
            if record.id not in reset_steps:
                continue
            record.status = "created"
            record.start_time = None
            record.end_time = None
            record.inputs_resolved = []
            record.outputs_produced = []
            record.warnings = []
            record.warning_details = []
            record.errors = []
            record.error_details = []

        run_document.lifecycle_status = "waiting"
        run_document.outputs = []
        run_document.qc_policy_results = self._filter_retained_qc_policy_results(
            spec,
            run_document.qc_policy_results,
            reset_steps=reset_steps,
        )
        retained_summaries = [item.summary for item in run_document.qc_policy_results if item.summary]
        run_document.qc_summary = "\n".join(retained_summaries) if retained_summaries else None
        run_document.warnings = []
        run_document.warning_details = []
        run_document.related_artifacts = [
            ref for ref in run_document.related_artifacts if self._artifact_ref_key(ref) not in stale_ref_keys
        ]
        run_document.summary_metrics = [
            metric
            for metric in run_document.summary_metrics
            if metric.stage not in reset_steps
        ]
        return run_document

    def _stale_restart_ref_keys(
        self,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        *,
        reset_steps: set[str],
    ) -> set[tuple[str, str, str | None, str | None]]:
        stale_keys: set[tuple[str, str, str | None, str | None]] = set()
        for record in run_document.steps:
            if record.id not in reset_steps:
                continue
            stale_keys.update(self._artifact_ref_key(ref) for ref in record.outputs_produced)

        for workflow_output in spec.outputs:
            if workflow_output.kind != "artifact" or workflow_output.source.step_id not in reset_steps:
                continue
            if workflow_output.artifact_type is None:
                continue
            stable_relpath = layout.stable_artifact_relpath(workflow_output.artifact_type).as_posix()
            for ref in run_document.related_artifacts:
                if ref.artifact_type != workflow_output.artifact_type or ref.path != stable_relpath:
                    continue
                stale_keys.add(self._artifact_ref_key(ref))
        return stale_keys

    def _delete_materialized_workflow_outputs(
        self,
        layout: RunLayout,
        spec: WorkflowSpec,
        *,
        reset_steps: set[str],
    ) -> None:
        deleted_paths: set[str] = set()
        for workflow_output in spec.outputs:
            if workflow_output.kind != "artifact" or workflow_output.source.step_id not in reset_steps:
                continue
            if workflow_output.artifact_type is None:
                continue
            stable_relpath = layout.stable_artifact_relpath(workflow_output.artifact_type)
            stable_key = stable_relpath.as_posix()
            if stable_key in deleted_paths:
                continue
            target = resolve_artifact_path(layout.run_dir, stable_relpath.name)
            if not target.exists():
                continue
            target.unlink()
            try:
                from artifacts.registry import refresh_artifact_registry_path

                refresh_artifact_registry_path(layout.base_dir, stable_relpath)
            except Exception:
                pass
            deleted_paths.add(stable_key)

    def _filter_retained_qc_policy_results(
        self,
        spec: WorkflowSpec,
        evaluations: list[QCPolicyEvaluation],
        *,
        reset_steps: set[str],
    ) -> list[QCPolicyEvaluation]:
        gates_by_id = {gate.id: gate for gate in spec.qc_gates}
        retained: list[QCPolicyEvaluation] = []
        for evaluation in evaluations:
            if evaluation.stage == "before_publish":
                continue
            gate = gates_by_id.get(evaluation.gate_id or "")
            if gate is None:
                retained.append(evaluation)
                continue
            target = gate.target
            if isinstance(target, StepOutputSource) and target.step_id in reset_steps:
                continue
            retained.append(evaluation)
        return retained

    def _load_completed_step_outputs(
        self,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
    ) -> tuple[dict[tuple[str, str], Any], dict[tuple[str, str], ArtifactReference]]:
        values: dict[tuple[str, str], Any] = {}
        refs: dict[tuple[str, str], ArtifactReference] = {}
        steps_by_id = {step.id: step for step in spec.steps}

        for record in run_document.steps:
            if record.status != _STEP_COMPLETE_STATUS:
                continue
            step = steps_by_id[record.id]
            snapshot = self._load_step_output_snapshot(layout, step.id)
            for output in step.outputs:
                raw_ref = snapshot.get(output.name)
                if raw_ref is None:
                    continue
                ref = ArtifactReference.model_validate(raw_ref)
                refs[(step.id, output.name)] = ref
                values[(step.id, output.name)] = self._load_output_value(output.kind, ref)
        return values, refs

    def _load_step_output_snapshot(self, layout: RunLayout, step_id: str) -> dict[str, Any]:
        relative_path = build_generated_output_relpath(_STEP_OUTPUT_SNAPSHOT_NAME, step=step_id)
        path = resolve_artifact_path(layout.run_dir, relative_path)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        outputs = payload.get("outputs")
        if not isinstance(outputs, dict):
            raise ValueError(f"Invalid step output snapshot at {path}.")
        return outputs

    def _load_output_value(self, output_kind: str, ref: ArtifactReference) -> Any:
        if output_kind == "artifact":
            return ref.path
        target = resolve_artifact_path(self.base_dir, ref.path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "value" not in payload:
            raise ValueError(f"Workflow value snapshot at {target} is missing its 'value' payload.")
        return payload["value"]

    def _next_ready_step(self, spec: WorkflowSpec, run_document: WorkflowRun) -> WorkflowStepDefinition | None:
        statuses = {record.id: record.status for record in run_document.steps}
        for step in spec.steps:
            step_status = statuses[step.id]
            if step_status not in _STEP_READY_STATUS:
                continue
            if all(statuses[prerequisite] == _STEP_COMPLETE_STATUS for prerequisite in step.prerequisites):
                return step
        return None

    def _execute_step(
        self,
        *,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        resolved_inputs: Mapping[str, Any],
        step: WorkflowStepDefinition,
        step_output_values: dict[tuple[str, str], Any],
        step_output_refs: dict[tuple[str, str], ArtifactReference],
        emitter: _WorkflowRunStreamEmitter | None,
    ) -> WorkflowRun:
        record = self._step_record(run_document, step.id)
        record.status = "running"
        record.start_time = _utcnow()
        record.end_time = None
        if emitter is not None:
            emitter.step_start(step)

        context = StepExecutionContext(
            base_dir=self.base_dir,
            run_dir=layout.run_dir,
            relative_run_dir=layout.relative_run_dir,
            run_id=layout.run_id,
            created_at=layout.created_at,
            workflow_id=spec.workflow_id,
            step_id=step.id,
        )

        try:
            step_inputs = self._resolve_step_inputs(step, resolved_inputs, step_output_values)
            input_snapshot_ref = self._persist_step_inputs(layout, step.id, step_inputs)
            record.inputs_resolved = self._dedupe_refs(
                [*self._source_refs_for_step_inputs(step, resolved_inputs, step_output_refs), input_snapshot_ref]
            )
            run_document = self._apply_stage_policies(
                layout=layout,
                spec=spec,
                run_document=run_document,
                resolved_inputs=resolved_inputs,
                step_output_values=step_output_values,
                step_output_refs=step_output_refs,
                stage="before_step",
                current_step=step,
                emitter=emitter,
            )
            if run_document.lifecycle_status in _RUN_FINAL_STATUSES:
                record.end_time = _utcnow()
                if emitter is not None:
                    emitter.step_end(step, record)
                return run_document
            raw_outputs = self._run_step_executor(step, step_inputs, context)
            output_values = self._normalize_executor_outputs(step, raw_outputs)
            output_refs: list[ArtifactReference] = []
            emitted_outputs: list[tuple[str, ArtifactReference]] = []
            snapshot_payload: dict[str, Any] = {}
            for output in step.outputs:
                ref, persisted_value = self._persist_step_output(
                    layout=layout,
                    spec=spec,
                    step=step,
                    output_name=output.name,
                    output_kind=output.kind,
                    artifact_type=output.artifact_type,
                    raw_value=output_values[output.name],
                )
                step_output_values[(step.id, output.name)] = persisted_value
                step_output_refs[(step.id, output.name)] = ref
                output_refs.append(ref)
                emitted_outputs.append((output.name, ref))
                snapshot_payload[output.name] = ref.model_dump(mode="json")
            self._persist_step_output_snapshot(layout, step.id, snapshot_payload)
            record.outputs_produced = output_refs
            record.status = _STEP_COMPLETE_STATUS
            record.end_time = _utcnow()
            if emitter is not None:
                for output_name, ref in emitted_outputs:
                    emitter.artifact(ref, scope="step_output", step=step, output_name=output_name)
            run_document = self._apply_stage_policies(
                layout=layout,
                spec=spec,
                run_document=run_document,
                resolved_inputs=resolved_inputs,
                step_output_values=step_output_values,
                step_output_refs=step_output_refs,
                stage="after_step",
                current_step=step,
                emitter=emitter,
            )
            if emitter is not None:
                emitter.step_end(step, record)
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            issue_details = _workflow_issue_details_from_exception(exc)
            record.errors.append(error_message)
            record.error_details = _dedupe_workflow_issue_details([*record.error_details, *issue_details])
            record.end_time = _utcnow()
            if step.failure_policy == "continue_with_warning":
                record.status = _STEP_COMPLETE_STATUS
                record.warnings.append(error_message)
                record.warning_details = _dedupe_workflow_issue_details([*record.warning_details, *issue_details])
                run_document.warning_details = _dedupe_workflow_issue_details(
                    [*run_document.warning_details, *issue_details]
                )
                run_document.warnings.append(
                    f"Step {step.id} continued with warning after execution error: {error_message}"
                )
            else:
                terminal_status = "blocked" if step.failure_policy == "block_workflow" else "failed"
                record.status = terminal_status
                run_document.lifecycle_status = terminal_status
                if terminal_status == "blocked":
                    if error_message not in run_document.warnings:
                        run_document.warnings.append(error_message)
                    run_document.warning_details = _dedupe_workflow_issue_details(
                        [*run_document.warning_details, *issue_details]
                    )
                self._block_descendants(spec, run_document, failed_step_id=step.id, reason=error_message)
                if emitter is not None and terminal_status == "blocked":
                    emitter.blocked(
                        reason=error_message,
                        issue_details=issue_details,
                        stage="after_step",
                        blocking_source="step_failure",
                        step=step,
                    )
            if emitter is not None:
                emitter.step_end(step, record)
        return run_document

    def _resolve_step_inputs(
        self,
        step: WorkflowStepDefinition,
        resolved_inputs: Mapping[str, Any],
        step_output_values: Mapping[tuple[str, str], Any],
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for binding in step.inputs:
            source = binding.source
            if isinstance(source, WorkflowInputSource):
                values[binding.name] = resolved_inputs[source.input_name]
            elif isinstance(source, StepOutputSource):
                key = (source.step_id, source.output_name)
                if key not in step_output_values:
                    raise ValueError(
                        f"Required upstream output {source.step_id}.{source.output_name} is not available for step {step.id}."
                    )
                values[binding.name] = step_output_values[key]
            elif isinstance(source, LiteralBindingSource):
                values[binding.name] = source.value
            else:
                raise ValueError(f"Unsupported binding source for step {step.id}.")
        return values

    def _persist_step_inputs(
        self,
        layout: RunLayout,
        step_id: str,
        resolved_inputs: Mapping[str, Any],
    ) -> ArtifactReference:
        relative_path = build_generated_output_relpath(_STEP_INPUT_SNAPSHOT_NAME, step=step_id)
        payload = {
            "step_id": step_id,
            "resolved_inputs": _serialize_for_json(dict(resolved_inputs)),
        }
        self._write_json_under_run(layout, relative_path, payload)
        return ArtifactReference(
            artifact_type="step_input_snapshot",
            path=(layout.relative_run_dir / relative_path).as_posix(),
            id=normalize_identifier(f"{step_id}-inputs-{layout.run_id.lower()}"),
            run_id=layout.run_id,
        )

    def _source_refs_for_step_inputs(
        self,
        step: WorkflowStepDefinition,
        resolved_inputs: Mapping[str, Any],
        step_output_refs: Mapping[tuple[str, str], ArtifactReference],
    ) -> list[ArtifactReference]:
        refs: list[ArtifactReference] = []
        for binding in step.inputs:
            source = binding.source
            if isinstance(source, WorkflowInputSource):
                value = resolved_inputs[source.input_name]
                if isinstance(value, str):
                    candidate = (self.base_dir / value).resolve()
                    if not candidate.exists():
                        continue
                    refs.append(
                        ArtifactReference(
                            artifact_type="workflow_input",
                            path=self._coerce_project_relative_path(value),
                        )
                    )
            elif isinstance(source, StepOutputSource):
                ref = step_output_refs.get((source.step_id, source.output_name))
                if ref is not None:
                    refs.append(ref)
        return refs

    def _run_step_executor(
        self,
        step: WorkflowStepDefinition,
        step_inputs: Mapping[str, Any],
        context: StepExecutionContext,
    ) -> Any:
        executor = step.executor
        if isinstance(executor, PythonExecutor):
            callable_obj = self._load_python_callable(context.base_dir, executor.module, executor.function)
            return self._invoke_python_callable(callable_obj, step_inputs, context)
        if isinstance(executor, ExternalEngineExecutor):
            return self._run_external_command(step, executor, step_inputs, context)
        raise ValueError(
            f"Executor type {step.executor.executor_type!r} is not supported by the internal DAG runner MVP."
        )

    def _load_python_callable(self, search_root: Path, module_name: str, function_name: str):
        if str(search_root) not in sys.path:
            sys.path.insert(0, str(search_root))

        for prefix in _module_prefixes(module_name):
            loaded = sys.modules.get(prefix)
            if loaded is None:
                continue
            origin = getattr(loaded, "__file__", None)
            if origin is not None and str(search_root) not in str(origin):
                sys.modules.pop(prefix, None)

        importlib.invalidate_caches()
        module = importlib.import_module(module_name)
        try:
            return getattr(module, function_name)
        except AttributeError as exc:
            raise ValueError(f"Python executor function {function_name!r} was not found in {module_name!r}.") from exc

    def _invoke_python_callable(
        self,
        callable_obj,
        step_inputs: Mapping[str, Any],
        context: StepExecutionContext,
    ) -> Any:
        signature = inspect.signature(callable_obj)
        parameters = list(signature.parameters.values())
        if any(parameter.name == "context" for parameter in parameters):
            return callable_obj(dict(step_inputs), context=context)
        if len(parameters) >= 2:
            return callable_obj(dict(step_inputs), context)
        if len(parameters) == 1:
            return callable_obj(dict(step_inputs))
        return callable_obj()

    def _run_external_command(
        self,
        step: WorkflowStepDefinition,
        executor: ExternalEngineExecutor,
        step_inputs: Mapping[str, Any],
        context: StepExecutionContext,
    ) -> dict[str, Any]:
        rendered_entrypoint = self._render_external_template(
            executor.entrypoint,
            step_inputs,
            shell_quote=False,
        )
        command_template = executor.command or f"{executor.engine_name} run {executor.entrypoint}"
        command = self._render_external_template(command_template, step_inputs)
        argv = shlex.split(command)
        env = os.environ.copy()
        env.update(self._external_executor_environment(step_inputs, context))
        result = subprocess.run(
            argv,
            cwd=context.base_dir,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{command!r} failed.")
        if len(step.outputs) != 1:
            raise ValueError("External engine executor currently requires exactly one declared output.")
        return {
            step.outputs[0].name: {
                "engine_name": executor.engine_name,
                "entrypoint": rendered_entrypoint,
                "command": command,
                "argv": argv,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "inputs": _serialize_for_json(dict(step_inputs)),
                "environment_keys": sorted(
                    key for key in env if key.startswith("BIOAPEX_")
                ),
            }
        }

    def _normalize_executor_outputs(
        self,
        step: WorkflowStepDefinition,
        raw_outputs: Any,
    ) -> dict[str, Any]:
        if isinstance(raw_outputs, dict):
            output_map = dict(raw_outputs)
        elif len(step.outputs) == 1:
            output_map = {step.outputs[0].name: raw_outputs}
        else:
            raise ValueError(f"Step {step.id} must return a mapping keyed by declared output names.")

        missing = [output.name for output in step.outputs if output.name not in output_map]
        if missing:
            raise ValueError(f"Step {step.id} did not produce declared outputs: {', '.join(missing)}.")
        return output_map

    def _persist_step_output(
        self,
        *,
        layout: RunLayout,
        spec: WorkflowSpec,
        step: WorkflowStepDefinition,
        output_name: str,
        output_kind: str,
        artifact_type: str | None,
        raw_value: Any,
    ) -> tuple[ArtifactReference, Any]:
        if output_kind == "artifact":
            return self._persist_artifact_output(
                layout=layout,
                spec=spec,
                step=step,
                output_name=output_name,
                artifact_type=artifact_type,
                raw_value=raw_value,
            )
        return self._persist_value_output(layout=layout, step_id=step.id, output_name=output_name, raw_value=raw_value)

    def _persist_artifact_output(
        self,
        *,
        layout: RunLayout,
        spec: WorkflowSpec,
        step: WorkflowStepDefinition,
        output_name: str,
        artifact_type: str | None,
        raw_value: Any,
    ) -> tuple[ArtifactReference, str]:
        if artifact_type is None:
            raise ValueError(f"Artifact output {step.id}.{output_name} is missing artifact_type.")

        if isinstance(raw_value, ArtifactReference):
            ref = raw_value
            return ref, ref.path

        if isinstance(raw_value, (str, Path)):
            relative_path = self._coerce_project_relative_path(raw_value)
            ref = ArtifactReference(artifact_type=artifact_type, path=relative_path)
            return ref, relative_path

        if not isinstance(raw_value, dict):
            raise ValueError(
                f"Artifact output {step.id}.{output_name} must return a mapping payload or project-relative path."
            )

        run_ref = self._run_record_ref(layout)
        payload = dict(raw_value)
        payload.setdefault("schema_version", SCHEMA_PACK_VERSION)
        payload.setdefault("artifact_type", artifact_type)
        payload.setdefault(
            "id",
            normalize_identifier(f"{artifact_type}-{spec.workflow_id}-{step.id}-{layout.run_id.lower()}"),
        )
        payload.setdefault("run_id", layout.run_id)
        payload.setdefault("created_at", _isoformat_z(_utcnow()))
        if "source_workflow" not in payload and "source_tool" not in payload:
            payload["source_workflow"] = spec.workflow_id
        related_artifacts = payload.get("related_artifacts")
        if not isinstance(related_artifacts, list):
            related_artifacts = []
        related_artifacts.append(run_ref.model_dump(mode="json"))
        payload["related_artifacts"] = related_artifacts

        artifact_document = validate_artifact_payload(payload)
        file_format = schema_format_for_artifact(artifact_type)
        extension = ".json" if file_format == "json" else ".yaml"
        relative_path = build_generated_output_relpath(f"{output_name}{extension}", step=step.id)
        rendered = (
            _dump_json(artifact_document.model_dump(mode="json"))
            if file_format == "json"
            else _dump_yaml(artifact_document.model_dump(mode="json"))
        )
        self._write_text_under_run(layout, relative_path, rendered)
        ref = ArtifactReference(
            artifact_type=artifact_document.artifact_type,
            path=(layout.relative_run_dir / relative_path).as_posix(),
            id=artifact_document.id,
            run_id=artifact_document.run_id,
        )
        return ref, ref.path

    def _persist_value_output(
        self,
        *,
        layout: RunLayout,
        step_id: str,
        output_name: str,
        raw_value: Any,
    ) -> tuple[ArtifactReference, Any]:
        relative_path = build_generated_output_relpath(f"{output_name}.json", step=step_id)
        self._write_json_under_run(
            layout,
            relative_path,
            {
                "step_id": step_id,
                "output_name": output_name,
                "value": _serialize_for_json(raw_value),
            },
        )
        ref = ArtifactReference(
            artifact_type="workflow_value",
            path=(layout.relative_run_dir / relative_path).as_posix(),
            id=normalize_identifier(f"{step_id}-{output_name}-{layout.run_id.lower()}"),
            run_id=layout.run_id,
        )
        return ref, raw_value

    def _persist_step_output_snapshot(
        self,
        layout: RunLayout,
        step_id: str,
        output_refs: Mapping[str, Any],
    ) -> None:
        relative_path = build_generated_output_relpath(_STEP_OUTPUT_SNAPSHOT_NAME, step=step_id)
        self._write_json_under_run(
            layout,
            relative_path,
            {"step_id": step_id, "outputs": output_refs},
        )

    def _sync_workflow_outputs(
        self,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        step_output_values: Mapping[tuple[str, str], Any],
        step_output_refs: Mapping[tuple[str, str], ArtifactReference],
        *,
        materialize_final_artifacts: bool,
        emitter: _WorkflowRunStreamEmitter | None,
    ) -> WorkflowRun:
        outputs: list[ArtifactReference] = []
        for workflow_output in spec.outputs:
            key = (workflow_output.source.step_id, workflow_output.source.output_name)
            ref = step_output_refs.get(key)
            if ref is None:
                continue
            if workflow_output.kind == "artifact" and materialize_final_artifacts:
                ref = self._materialize_final_artifact(layout, workflow_output, ref)
                if emitter is not None:
                    emitter.artifact(ref, scope="workflow_output", output_name=workflow_output.name)
            outputs.append(ref)
        run_document.outputs = self._dedupe_refs(outputs)
        run_document.summary_metrics = self._collect_summary_metrics(step_output_values)
        return run_document

    def _collect_summary_metrics(
        self,
        step_output_values: Mapping[tuple[str, str], Any],
    ) -> list[WorkflowSummaryMetric]:
        metrics: list[WorkflowSummaryMetric] = []
        seen: set[tuple[str, str, str, str | None]] = set()

        for value in step_output_values.values():
            if not isinstance(value, Mapping):
                continue
            raw_metrics = value.get("summary_metrics")
            if not isinstance(raw_metrics, list):
                continue
            for item in raw_metrics:
                if not isinstance(item, Mapping):
                    continue
                stage = item.get("stage")
                metric_name = item.get("metric_name")
                if not isinstance(stage, str) or not stage.strip():
                    continue
                if not isinstance(metric_name, str) or not metric_name.strip():
                    continue
                source_artifact = item.get("source_artifact")
                source_path: str | None = None
                if isinstance(source_artifact, Mapping):
                    raw_path = source_artifact.get("path")
                    if isinstance(raw_path, str):
                        source_path = raw_path
                key = (
                    stage.strip(),
                    metric_name.strip(),
                    json.dumps(_serialize_for_json(item.get("value")), sort_keys=True),
                    source_path,
                )
                if key in seen:
                    continue
                seen.add(key)
                metrics.append(
                    WorkflowSummaryMetric(
                        stage=stage.strip(),
                        metric_name=metric_name.strip(),
                        value=_serialize_for_json(item.get("value")),
                        source_artifact=(
                            ArtifactReference.model_validate(source_artifact)
                            if isinstance(source_artifact, Mapping)
                            else None
                        ),
                    )
                )
        return metrics

    def _materialize_final_artifact(
        self,
        layout: RunLayout,
        workflow_output: WorkflowOutputDefinition,
        ref: ArtifactReference,
    ) -> ArtifactReference:
        if workflow_output.artifact_type is None:
            return ref
        stable_name = stable_artifact_name(workflow_output.artifact_type)
        stable_relpath = layout.relative_run_dir / stable_name
        if ref.path == stable_relpath.as_posix():
            return ref

        source_path = resolve_artifact_path(self.base_dir, ref.path)
        target = layout._track_path(resolve_artifact_path(layout.run_dir, PurePosixPath(stable_name)))
        target.write_bytes(source_path.read_bytes())
        return ArtifactReference(
            artifact_type=ref.artifact_type,
            path=stable_relpath.as_posix(),
            id=ref.id,
            run_id=ref.run_id,
        )

    def _apply_stage_policies(
        self,
        *,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        resolved_inputs: Mapping[str, Any],
        step_output_values: Mapping[tuple[str, str], Any],
        step_output_refs: Mapping[tuple[str, str], ArtifactReference],
        stage: str,
        current_step: WorkflowStepDefinition | None,
        emitter: _WorkflowRunStreamEmitter | None,
    ) -> WorkflowRun:
        for gate in spec.qc_gates:
            if gate.when != stage:
                continue
            if not self._qc_gate_applies_to_step(gate.target, current_step=current_step, stage=stage):
                continue
            run_document = self._apply_qc_gate(
                spec=spec,
                run_document=run_document,
                resolved_inputs=resolved_inputs,
                step_output_values=step_output_values,
                stage=stage,
                current_step=current_step,
                gate=gate,
                emitter=emitter,
            )
            if run_document.lifecycle_status in _RUN_FINAL_STATUSES:
                return run_document

        for hook in spec.compliance_hooks:
            if hook.stage != stage:
                continue
            if hook.step_id is not None and (current_step is None or hook.step_id != current_step.id):
                continue
            run_document = self._apply_compliance_hook(
                layout=layout,
                spec=spec,
                run_document=run_document,
                resolved_inputs=resolved_inputs,
                step_output_values=step_output_values,
                current_step=current_step,
                hook=hook,
                emitter=emitter,
            )
            if run_document.lifecycle_status in _RUN_FINAL_STATUSES:
                return run_document

        return run_document

    def _qc_gate_applies_to_step(
        self,
        target,
        *,
        current_step: WorkflowStepDefinition | None,
        stage: str,
    ) -> bool:
        if current_step is None:
            return True
        if stage == "after_step":
            return isinstance(target, StepOutputSource) and target.step_id == current_step.id
        if stage != "before_step":
            return True
        for binding in current_step.inputs:
            source = binding.source
            if isinstance(target, WorkflowInputSource) and isinstance(source, WorkflowInputSource):
                if source.input_name == target.input_name:
                    return True
            if isinstance(target, StepOutputSource) and isinstance(source, StepOutputSource):
                if source.step_id == target.step_id and source.output_name == target.output_name:
                    return True
        return False

    def _apply_qc_gate(
        self,
        *,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        resolved_inputs: Mapping[str, Any],
        step_output_values: Mapping[tuple[str, str], Any],
        stage: str,
        current_step: WorkflowStepDefinition | None,
        gate,
        emitter: _WorkflowRunStreamEmitter | None,
    ) -> WorkflowRun:
        try:
            value = self._resolve_binding_value(gate.target, resolved_inputs, step_output_values)
            policy = self._resolve_qc_policy_definition(gate.policy, value)
            if policy is None:
                self._validate_gate_target_value(spec, gate.target, value)
                return run_document

            evaluation = self._evaluate_qc_gate_policy(
                gate=gate,
                policy=policy,
                value=value,
                stage=stage,
            )
            run_document = self._record_qc_policy_evaluation(run_document, policy, evaluation)
            issue_details = _workflow_issue_details_from_qc_policy_evaluation(evaluation)
            if evaluation.overall_status == "pass":
                return run_document
            if evaluation.overall_status == "warn":
                return self._record_policy_warning(
                    run_document,
                    evaluation.summary,
                    current_step=current_step,
                    issue_details=issue_details,
                )
            if gate.failure_policy == "warn":
                return self._record_policy_warning(
                    run_document,
                    evaluation.summary,
                    current_step=current_step,
                    issue_details=issue_details,
                )
            return self._block_for_policy(
                spec=spec,
                run_document=run_document,
                reason=evaluation.summary,
                stage=stage,
                current_step=current_step,
                blocking_source="qc_gate",
                issue_details=issue_details,
                emitter=emitter,
            )
        except Exception as exc:
            reason = f"QC gate {gate.id} failed: {exc}"
            if gate.failure_policy == "warn":
                return self._record_policy_warning(run_document, reason, current_step=current_step)
            return self._block_for_policy(
                spec=spec,
                run_document=run_document,
                reason=reason,
                stage=stage,
                current_step=current_step,
                blocking_source="qc_gate",
                emitter=emitter,
            )

    def _resolve_qc_policy_definition(
        self,
        inline_policy: QCPolicyDefinition | None,
        value: Any,
    ) -> QCPolicyDefinition | None:
        if inline_policy is not None:
            return inline_policy
        loaded_document = self._load_qc_policy_source_document(value)
        if isinstance(loaded_document, DatasetManifest):
            return loaded_document.qc_policy
        if isinstance(loaded_document, Mapping):
            raw_policy = loaded_document.get("qc_policy")
            if isinstance(raw_policy, Mapping):
                return QCPolicyDefinition.model_validate(raw_policy)
        return None

    def _evaluate_qc_gate_policy(
        self,
        *,
        gate,
        policy: QCPolicyDefinition,
        value: Any,
        stage: str,
    ) -> QCPolicyEvaluation:
        loaded_document = self._load_qc_policy_source_document(value)
        assay_type: str | None = None
        evidence_payload: Any = value
        if isinstance(loaded_document, DatasetManifest):
            assay_type = loaded_document.assay_type
            evidence_payload = loaded_document.assay_extensions.get("qc_evidence")
        elif isinstance(loaded_document, Mapping):
            evidence_payload = self._extract_qc_evidence_payload(loaded_document)
            assay_type = loaded_document.get("assay_type") if isinstance(loaded_document.get("assay_type"), str) else None

        if evidence_payload is None:
            raise ValueError("QC policy targets must provide qc_evidence metrics for evaluation.")
        return evaluate_qc_policy(
            policy,
            evidence_payload,
            assay_type=assay_type,
            gate_id=gate.id,
            stage=stage,
        )

    def _load_qc_policy_source_document(self, value: Any) -> Any:
        candidate_path: str | None = None
        if isinstance(value, Mapping) and isinstance(value.get("path"), str):
            candidate_path = str(value["path"])
        elif isinstance(value, str):
            candidate_path = value
        if candidate_path is None:
            return value

        try:
            project_path = self._project_path(candidate_path)
        except ValueError:
            return value
        if not project_path.exists() or not project_path.is_file():
            return value
        if project_path.suffix not in {".json", ".yaml", ".yml"}:
            return value
        return load_artifact_document(project_path)

    def _extract_qc_evidence_payload(self, payload: Mapping[str, Any]) -> Any:
        if "metrics" in payload and "upstream_tools" in payload:
            return payload
        raw_qc_evidence = payload.get("qc_evidence")
        if isinstance(raw_qc_evidence, Mapping):
            return raw_qc_evidence
        assay_extensions = payload.get("assay_extensions")
        if isinstance(assay_extensions, Mapping):
            nested_qc_evidence = assay_extensions.get("qc_evidence")
            if isinstance(nested_qc_evidence, Mapping):
                return nested_qc_evidence
        return None

    def _record_qc_policy_evaluation(
        self,
        run_document: WorkflowRun,
        policy: QCPolicyDefinition,
        evaluation: QCPolicyEvaluation,
    ) -> WorkflowRun:
        policy_key = (policy.policy_id, policy.version)
        existing_policy_keys = {(item.policy_id, item.version) for item in run_document.qc_policies}
        if policy_key not in existing_policy_keys:
            run_document.qc_policies.append(policy)

        evaluation_key = (
            evaluation.policy_id,
            evaluation.version,
            evaluation.gate_id,
            evaluation.stage,
        )
        run_document.qc_policy_results = [
            item
            for item in run_document.qc_policy_results
            if (item.policy_id, item.version, item.gate_id, item.stage) != evaluation_key
        ]
        run_document.qc_policy_results.append(evaluation)
        summaries = [item.summary for item in run_document.qc_policy_results if item.summary]
        run_document.qc_summary = "\n".join(summaries) if summaries else None
        return run_document

    def _apply_compliance_hook(
        self,
        *,
        layout: RunLayout,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        resolved_inputs: Mapping[str, Any],
        step_output_values: Mapping[tuple[str, str], Any],
        current_step: WorkflowStepDefinition | None,
        hook,
        emitter: _WorkflowRunStreamEmitter | None,
    ) -> WorkflowRun:
        try:
            hook_inputs = self._resolve_named_bindings(hook.inputs, resolved_inputs, step_output_values)
            if hook.tool != "compliance_preflight":
                raise ValueError(f"Unsupported compliance hook tool {hook.tool!r}.")

            from compliance.preflight import CompliancePreflightInput, run_compliance_preflight

            payload = CompliancePreflightInput(
                user_message=self._build_compliance_user_message(spec, hook.id, hook.stage, hook_inputs),
                attached_identifiers=self._compliance_attached_identifiers(hook_inputs),
                selected_workflow=spec.workflow_id,
                session_id=layout.run_id,
            )
            result = run_compliance_preflight(self.base_dir, payload)
            compliance_ref = self._compliance_result_ref(result)
            run_document.related_artifacts = self._dedupe_refs(
                [*run_document.related_artifacts, compliance_ref]
            )
            if emitter is not None:
                emitter.artifact(compliance_ref, scope="related_artifact", step=current_step)
            if result.warning_text:
                run_document = self._record_policy_warning(
                    run_document,
                    f"Compliance hook {hook.id}: {result.warning_text}",
                    current_step=current_step,
                )
            if not result.should_continue:
                message = f"Compliance hook {hook.id} blocked execution: {result.tool_summary}"
                if hook.required:
                    return self._block_for_policy(
                        spec=spec,
                        run_document=run_document,
                        reason=message,
                        stage=hook.stage,
                        current_step=current_step,
                        blocking_source="compliance_hook",
                        emitter=emitter,
                    )
                return self._record_policy_warning(run_document, message, current_step=current_step)
        except Exception as exc:
            message = f"Compliance hook {hook.id} could not complete deterministically: {exc}"
            if hook.required:
                return self._block_for_policy(
                    spec=spec,
                    run_document=run_document,
                    reason=message,
                    stage=hook.stage,
                    current_step=current_step,
                    blocking_source="compliance_hook",
                    emitter=emitter,
                )
            return self._record_policy_warning(run_document, message, current_step=current_step)
        return run_document

    def _resolve_named_bindings(
        self,
        bindings,
        resolved_inputs: Mapping[str, Any],
        step_output_values: Mapping[tuple[str, str], Any],
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for binding in bindings:
            resolved[binding.name] = self._resolve_binding_value(binding.source, resolved_inputs, step_output_values)
        return resolved

    def _resolve_binding_value(
        self,
        source,
        resolved_inputs: Mapping[str, Any],
        step_output_values: Mapping[tuple[str, str], Any],
    ) -> Any:
        if isinstance(source, WorkflowInputSource):
            if source.input_name not in resolved_inputs:
                raise ValueError(f"Workflow input {source.input_name!r} is not available.")
            return resolved_inputs[source.input_name]
        if isinstance(source, StepOutputSource):
            key = (source.step_id, source.output_name)
            if key not in step_output_values:
                raise ValueError(f"Step output {source.step_id}.{source.output_name} is not available.")
            return step_output_values[key]
        if isinstance(source, LiteralBindingSource):
            return source.value
        raise ValueError("Unsupported binding source.")

    def _validate_gate_target_value(
        self,
        spec: WorkflowSpec,
        source,
        value: Any,
    ) -> None:
        if value is None:
            raise ValueError(f"{self._binding_label(source)} resolved to null.")

        if isinstance(value, str) and not value.strip():
            raise ValueError(f"{self._binding_label(source)} resolved to an empty string.")

        if isinstance(value, (list, tuple, dict, set)) and not value:
            raise ValueError(f"{self._binding_label(source)} resolved to an empty value.")

        if self._binding_is_path_like(spec, source):
            candidate = self._project_path(value)
            if not candidate.exists():
                raise ValueError(f"{self._binding_label(source)} path {candidate.relative_to(self.base_dir)} is missing.")

    def _binding_is_path_like(self, spec: WorkflowSpec, source) -> bool:
        if isinstance(source, WorkflowInputSource):
            definition = self._workflow_input_definition(spec, source.input_name)
            return definition.kind in {"artifact", "template"}
        if isinstance(source, StepOutputSource):
            output_definition = self._step_output_definition(spec, source.step_id, source.output_name)
            return output_definition.kind == "artifact"
        return False

    def _workflow_input_definition(self, spec: WorkflowSpec, input_name: str) -> WorkflowInputDefinition:
        for definition in spec.required_inputs + spec.optional_inputs:
            if definition.name == input_name:
                return definition
        raise KeyError(f"Workflow input definition {input_name!r} was not found.")

    def _step_output_definition(self, spec: WorkflowSpec, step_id: str, output_name: str):
        for step in spec.steps:
            if step.id != step_id:
                continue
            for output in step.outputs:
                if output.name == output_name:
                    return output
            raise KeyError(f"Step output definition {step_id}.{output_name} was not found.")
        raise KeyError(f"Workflow step {step_id!r} was not found.")

    def _project_path(self, value: Any) -> Path:
        if isinstance(value, Mapping) and "path" in value:
            value = value["path"]
        candidate = Path(str(value))
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.base_dir / candidate).resolve()
        try:
            resolved.relative_to(self.base_dir)
        except ValueError as exc:
            raise ValueError(f"Path {resolved} must stay under {self.base_dir}.") from exc
        return resolved

    def _binding_label(self, source) -> str:
        if isinstance(source, WorkflowInputSource):
            return f"workflow input {source.input_name}"
        if isinstance(source, StepOutputSource):
            return f"step output {source.step_id}.{source.output_name}"
        if isinstance(source, LiteralBindingSource):
            return "literal binding"
        return "binding"

    def _record_policy_warning(
        self,
        run_document: WorkflowRun,
        message: str,
        *,
        current_step: WorkflowStepDefinition | None,
        issue_details: list[WorkflowIssueDetail] | None = None,
    ) -> WorkflowRun:
        if message not in run_document.warnings:
            run_document.warnings.append(message)
        if issue_details:
            run_document.warning_details = _dedupe_workflow_issue_details(
                [*run_document.warning_details, *issue_details]
            )
        if current_step is not None:
            record = self._step_record(run_document, current_step.id)
            if message not in record.warnings:
                record.warnings.append(message)
            if issue_details:
                record.warning_details = _dedupe_workflow_issue_details(
                    [*record.warning_details, *issue_details]
                )
        return run_document

    def _block_for_policy(
        self,
        *,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        reason: str,
        stage: str,
        current_step: WorkflowStepDefinition | None,
        blocking_source: str,
        issue_details: list[WorkflowIssueDetail] | None = None,
        emitter: _WorkflowRunStreamEmitter | None,
    ) -> WorkflowRun:
        run_document.lifecycle_status = "blocked"
        if reason not in run_document.warnings:
            run_document.warnings.append(reason)
        if issue_details:
            run_document.warning_details = _dedupe_workflow_issue_details(
                [*run_document.warning_details, *issue_details]
            )

        if current_step is not None and stage == "before_step":
            record = self._step_record(run_document, current_step.id)
            record.status = "blocked"
            if reason not in record.errors:
                record.errors.append(reason)
            if issue_details:
                record.error_details = _dedupe_workflow_issue_details(
                    [*record.error_details, *issue_details]
                )
        elif current_step is not None and issue_details:
            record = self._step_record(run_document, current_step.id)
            record.warning_details = _dedupe_workflow_issue_details(
                [*record.warning_details, *issue_details]
            )

        if current_step is not None and stage in {"before_step", "after_step"}:
            self._block_descendants(spec, run_document, failed_step_id=current_step.id, reason=reason)

        if emitter is not None:
            emitter.blocked(
                reason=reason,
                issue_details=issue_details,
                stage=stage,
                blocking_source=blocking_source,
                step=current_step,
            )

        return run_document

    def _build_compliance_user_message(
        self,
        spec: WorkflowSpec,
        hook_id: str,
        stage: str,
        hook_inputs: Mapping[str, Any],
    ) -> str:
        rendered_inputs = ", ".join(
            f"{name}={self._stringify_external_value(value)}"
            for name, value in sorted(hook_inputs.items())
        )
        return (
            f"Workflow {spec.workflow_id} compliance hook {hook_id} at stage {stage}. "
            f"Resolved inputs: {rendered_inputs or 'none'}."
        )

    def _compliance_attached_identifiers(self, hook_inputs: Mapping[str, Any]) -> list[str]:
        identifiers: list[str] = []
        for value in hook_inputs.values():
            if isinstance(value, ArtifactReference):
                identifiers.append(value.path)
            elif isinstance(value, Mapping) and "path" in value and isinstance(value["path"], str):
                identifiers.append(value["path"])
            elif isinstance(value, (str, Path)):
                identifiers.append(str(value))
            elif isinstance(value, (list, tuple, set)):
                identifiers.extend(str(item) for item in value if str(item).strip())
        return identifiers

    def _compliance_result_ref(self, result) -> ArtifactReference:
        return ArtifactReference(
            artifact_type="compliance_report",
            path=result.artifact_relpath,
            id=result.report.id,
            run_id=result.report.run_id,
        )

    def _render_external_template(
        self,
        template: str,
        step_inputs: Mapping[str, Any],
        *,
        shell_quote: bool = True,
    ) -> str:
        parts: list[str] = []
        formatter = Formatter()
        for literal_text, field_name, format_spec, conversion in formatter.parse(template):
            parts.append(literal_text)
            if field_name is None:
                continue
            if format_spec or conversion:
                raise ValueError("External command templates do not support format specifiers or conversions.")
            if field_name not in step_inputs:
                raise ValueError(f"External command template references unknown input {field_name!r}.")
            rendered = self._stringify_external_value(step_inputs[field_name])
            parts.append(shlex.quote(rendered) if shell_quote else rendered)
        return "".join(parts)

    def _external_executor_environment(
        self,
        step_inputs: Mapping[str, Any],
        context: StepExecutionContext,
    ) -> dict[str, str]:
        environment = {
            "BIOAPEX_RUN_ID": context.run_id,
            "BIOAPEX_WORKFLOW_ID": context.workflow_id,
            "BIOAPEX_STEP_ID": context.step_id,
            "BIOAPEX_RUN_DIR": context.relative_run_dir.as_posix(),
        }
        for name, value in step_inputs.items():
            key = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
            environment[f"BIOAPEX_INPUT_{key}"] = self._stringify_external_value(value)
        return environment

    def _stringify_external_value(self, value: Any) -> str:
        if isinstance(value, ArtifactReference):
            return value.path
        if isinstance(value, Path):
            return value.as_posix()
        if isinstance(value, datetime):
            return _isoformat_z(value)
        if isinstance(value, (dict, list, tuple, set)):
            return json.dumps(_serialize_for_json(value), sort_keys=True)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _sync_related_artifacts(
        self,
        run_document: WorkflowRun,
        workflow_inputs_ref: ArtifactReference,
    ) -> WorkflowRun:
        run_document.related_artifacts = self._dedupe_refs(
            [*run_document.inputs, *run_document.outputs, *run_document.related_artifacts, workflow_inputs_ref]
        )
        return run_document

    def _sync_qc_status(self, run_document: WorkflowRun) -> WorkflowRun:
        qc_result_statuses = [item.overall_status for item in run_document.qc_policy_results]
        if run_document.lifecycle_status in {"failed", "blocked"} or "fail" in qc_result_statuses:
            run_document.qc_status = "failed"
        elif "warn" in qc_result_statuses or run_document.warnings or any(record.warnings for record in run_document.steps):
            run_document.qc_status = "warning"
        elif self._all_steps_completed(run_document):
            run_document.qc_status = "passed"
        else:
            run_document.qc_status = "pending"
        return run_document

    def _block_descendants(
        self,
        spec: WorkflowSpec,
        run_document: WorkflowRun,
        *,
        failed_step_id: str,
        reason: str,
    ) -> None:
        descendants = self._descendants(spec, failed_step_id)
        for record in run_document.steps:
            if record.id not in descendants:
                continue
            if record.status == _STEP_COMPLETE_STATUS:
                continue
            record.status = "blocked"
            record.errors.append(f"Blocked by prerequisite {failed_step_id}: {reason}")

    def _descendants(self, spec: WorkflowSpec, step_id: str) -> set[str]:
        remaining = {candidate.id: set(candidate.prerequisites) for candidate in spec.steps}
        descendants: set[str] = set()
        changed = True
        while changed:
            changed = False
            for candidate_id, prerequisites in remaining.items():
                if candidate_id == step_id or candidate_id in descendants:
                    continue
                if step_id in prerequisites or prerequisites.intersection(descendants):
                    descendants.add(candidate_id)
                    changed = True
        return descendants

    def _all_steps_completed(self, run_document: WorkflowRun) -> bool:
        return all(record.status == _STEP_COMPLETE_STATUS for record in run_document.steps)

    def _step_record(self, run_document: WorkflowRun, step_id: str) -> WorkflowStepRecord:
        for record in run_document.steps:
            if record.id == step_id:
                return record
        raise KeyError(f"Step record {step_id!r} was not found in workflow run.")

    def _write_json_under_run(self, layout: RunLayout, relative_path: PurePosixPath, payload: Any) -> None:
        self._write_text_under_run(layout, relative_path, _dump_json(payload))

    def _write_text_under_run(self, layout: RunLayout, relative_path: PurePosixPath, text: str) -> None:
        target = layout._track_path(resolve_artifact_path(layout.run_dir, relative_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def _persist_run_document(self, layout: RunLayout, run_document: WorkflowRun) -> WorkflowRun:
        validated = WorkflowRun.model_validate(run_document.model_dump(mode="json"))
        layout.run_record_path.write_text(_dump_json(validated.model_dump(mode="json")), encoding="utf-8")
        self._refresh_content_hash_manifest(layout)
        return validated

    def _refresh_content_hash_manifest(self, layout: RunLayout) -> None:
        entries: dict[str, bytes] = {}
        for path in sorted(layout.run_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(layout.run_dir).as_posix()
            if relative == "content_hashes.json":
                continue
            entries[relative] = path.read_bytes()
        manifest = build_content_hash_manifest(
            run_id=layout.run_id,
            schema_version=SCHEMA_PACK_VERSION,
            created_at=layout.created_at,
            source_workflow=layout.workflow,
            entries=entries,
        )
        layout.content_hash_manifest_path.write_text(_dump_json(manifest), encoding="utf-8")

    def _run_record_ref(self, layout: RunLayout) -> ArtifactReference:
        return ArtifactReference(
            artifact_type="workflow_run",
            path=layout.run_record_relpath.as_posix(),
            id=normalize_identifier(f"workflow-run-{layout.workflow}-{layout.run_id.lower()}"),
            run_id=layout.run_id,
        )

    def _dedupe_refs(self, refs: list[ArtifactReference]) -> list[ArtifactReference]:
        deduped: list[ArtifactReference] = []
        seen: set[tuple[str, str, str | None, str | None]] = set()
        for ref in refs:
            key = self._artifact_ref_key(ref)
            if key in seen:
                continue
            deduped.append(ref)
            seen.add(key)
        return deduped

    def _artifact_ref_key(self, ref: ArtifactReference) -> tuple[str, str, str | None, str | None]:
        return (ref.artifact_type, ref.path, ref.id, ref.run_id)

    def _build_result(self, layout: RunLayout, run_document: WorkflowRun, *, resumed: bool) -> WorkflowRunResult:
        return WorkflowRunResult(
            run=run_document,
            artifact_path=layout.run_record_path,
            artifact_relpath=layout.run_record_relpath.as_posix(),
            run_dir=layout.run_dir,
            resumed=resumed,
        )
