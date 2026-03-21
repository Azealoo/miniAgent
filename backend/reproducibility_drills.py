"""File-first workflow reproducibility drills for operational replay checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from artifacts import (
    CONTENT_HASH_MANIFEST_FILENAME,
    SCHEMA_PACK_VERSION,
    ArtifactReference,
    ReproducibilityDrillCheck,
    ReproducibilityDrillComparison,
    ReproducibilityDrillReport,
    WorkflowRun,
    build_content_hash_manifest,
    build_generated_output_relpath,
    load_artifact_document,
    normalize_identifier,
    refresh_artifact_registry_path,
    resolve_artifact_path,
)
from artifacts.schemas import WorkflowEnvironment, WorkflowIssueDetail
from workflow_runner import InternalDAGRunner, WorkflowRunResult

DrillTier = Literal["ci", "scheduled", "manual"]
ComparisonTargetType = Literal["summary_metric", "artifact_field"]
ComparisonMode = Literal["exact", "absolute_tolerance"]

_MISSING = object()
_WORKFLOW_ENVIRONMENT_FIELDS = frozenset(WorkflowEnvironment.model_fields)


@dataclass(frozen=True)
class DrillComparisonDefinition:
    comparison_id: str
    description: str
    target_type: ComparisonTargetType
    expected_value: Any
    comparison_mode: ComparisonMode = "exact"
    stage: str | None = None
    metric_name: str | None = None
    artifact_type: str | None = None
    field_path: str | None = None
    absolute_tolerance: float | None = None

    def __post_init__(self) -> None:
        normalize_identifier(self.comparison_id)
        if not self.description.strip():
            raise ValueError("description must not be empty.")
        if self.target_type == "summary_metric":
            if self.stage is None or self.metric_name is None:
                raise ValueError("summary_metric comparisons require stage and metric_name.")
        if self.target_type == "artifact_field":
            if self.artifact_type is None or self.field_path is None:
                raise ValueError("artifact_field comparisons require artifact_type and field_path.")
        if self.comparison_mode == "absolute_tolerance" and self.absolute_tolerance is None:
            raise ValueError("absolute_tolerance comparisons require absolute_tolerance.")


@dataclass(frozen=True)
class WorkflowReproducibilityDrillDefinition:
    drill_id: str
    label: str
    execution_tier: DrillTier
    workflow_spec_path: str
    inputs: Mapping[str, Any]
    environment_references: Sequence[str] = ()
    comparisons: Sequence[DrillComparisonDefinition] = ()
    notes: Sequence[str] = ()

    def __post_init__(self) -> None:
        normalize_identifier(self.drill_id)
        if not self.label.strip():
            raise ValueError("label must not be empty.")
        if not self.workflow_spec_path.strip():
            raise ValueError("workflow_spec_path must not be empty.")


@dataclass(frozen=True)
class DrillExecutionResult:
    workflow_result: WorkflowRunResult
    report: ReproducibilityDrillReport
    report_path: Path


def run_workflow_reproducibility_drill(
    base_dir: Path | str,
    drill: WorkflowReproducibilityDrillDefinition,
    *,
    created_at: datetime | None = None,
) -> DrillExecutionResult:
    base_path = Path(base_dir).resolve()
    workflow_spec_path = resolve_artifact_path(base_path, drill.workflow_spec_path)
    workflow_result = InternalDAGRunner(base_path).run(
        workflow_spec_path,
        dict(drill.inputs),
        created_at=created_at,
    )
    run_document = workflow_result.run

    comparisons = [
        evaluate_drill_comparison(base_path, run_document, definition)
        for definition in drill.comparisons
    ]
    environment_check = validate_environment_references(
        base_path,
        run_document,
        drill.environment_references,
    )
    provenance_check, provenance_refs = validate_provenance_completeness(base_path, run_document)
    report_bundle_check, report_bundle_refs = validate_report_bundle_completeness(base_path, run_document)
    compliance_check, compliance_refs = validate_compliance_artifact_presence(base_path, run_document)

    checked_artifacts = _dedupe_refs(
        [*provenance_refs, *report_bundle_refs, *compliance_refs]
    )
    report_relpath = (
        workflow_result.run_dir.relative_to(base_path)
        / build_generated_output_relpath(f"{normalize_identifier(drill.drill_id)}.json", step="reproducibility-drills")
    ).as_posix()
    report_path = resolve_artifact_path(base_path, report_relpath)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    run_ref = ArtifactReference(
        artifact_type="workflow_run",
        path=workflow_result.artifact_relpath,
        id=normalize_identifier(
            f"workflow-run-{run_document.workflow.slug}-{run_document.run_id.lower()}"
        ),
        run_id=run_document.run_id,
    )
    related_artifacts = _dedupe_refs([run_ref, *checked_artifacts])
    report = ReproducibilityDrillReport(
        schema_version=SCHEMA_PACK_VERSION,
        artifact_type="reproducibility_drill_report",
        id=normalize_identifier(
            f"reproducibility-drill-{drill.drill_id}-{run_document.run_id.lower()}"
        ),
        run_id=run_document.run_id,
        created_at=_utcnow(),
        source_workflow=run_document.source_workflow or run_document.workflow.slug,
        related_artifacts=related_artifacts,
        drill_id=drill.drill_id,
        label=drill.label,
        execution_tier=drill.execution_tier,
        status=_overall_drill_status(
            comparisons,
            [environment_check, provenance_check, report_bundle_check, compliance_check],
        ),
        workflow_spec_path=_relative_to_base(base_path, workflow_spec_path),
        workflow_parameters=dict(run_document.parameters),
        environment_references=list(drill.environment_references),
        reproduced_run=run_ref,
        source_inputs=list(run_document.inputs),
        checked_artifacts=checked_artifacts,
        comparisons=comparisons,
        checks=[environment_check, provenance_check, report_bundle_check, compliance_check],
        notes=[
            "Executed through InternalDAGRunner without interactive chat/session state.",
            *list(drill.notes),
        ],
    )
    report_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    refresh_artifact_registry_path(base_path, report_relpath)

    report_ref = ArtifactReference(
        artifact_type="reproducibility_drill_report",
        path=report_relpath,
        id=report.id,
        run_id=run_document.run_id,
    )
    updated_run = run_document.model_copy(deep=True)
    updated_run.related_artifacts = _dedupe_refs([*updated_run.related_artifacts, report_ref])
    validated_run = WorkflowRun.model_validate(updated_run.model_dump(mode="json"))
    workflow_result.artifact_path.write_text(
        json.dumps(validated_run.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_content_hash_manifest(base_path, workflow_result.run_dir, validated_run)

    return DrillExecutionResult(
        workflow_result=WorkflowRunResult(
            run=validated_run,
            artifact_path=workflow_result.artifact_path,
            artifact_relpath=workflow_result.artifact_relpath,
            run_dir=workflow_result.run_dir,
            resumed=workflow_result.resumed,
        ),
        report=report,
        report_path=report_path,
    )


def evaluate_drill_comparison(
    base_dir: Path | str,
    run_document: WorkflowRun,
    definition: DrillComparisonDefinition,
) -> ReproducibilityDrillComparison:
    base_path = Path(base_dir).resolve()
    artifact_type: str | None = None
    artifact_path: str | None = None
    actual_value: Any = None

    if definition.target_type == "summary_metric":
        metric = next(
            (
                item
                for item in run_document.summary_metrics
                if item.stage == definition.stage and item.metric_name == definition.metric_name
            ),
            None,
        )
        if metric is not None:
            actual_value = metric.value
            if metric.source_artifact is not None:
                artifact_type = metric.source_artifact.artifact_type
                artifact_path = metric.source_artifact.path
    else:
        artifact_ref = _find_artifact_reference(run_document, definition.artifact_type or "")
        if artifact_ref is not None:
            artifact_type = artifact_ref.artifact_type
            artifact_path = artifact_ref.path
            actual_value = _read_artifact_field(
                base_path,
                artifact_ref.path,
                definition.field_path or "",
            )
            if actual_value is _MISSING:
                actual_value = None

    passed, observed_difference = _compare_values(
        actual=actual_value,
        expected=definition.expected_value,
        mode=definition.comparison_mode,
        absolute_tolerance=definition.absolute_tolerance,
    )

    return ReproducibilityDrillComparison(
        comparison_id=definition.comparison_id,
        description=definition.description,
        target_type=definition.target_type,
        comparison_mode=definition.comparison_mode,
        passed=passed,
        expected_value=definition.expected_value,
        actual_value=actual_value,
        stage=definition.stage,
        metric_name=definition.metric_name,
        artifact_type=artifact_type or definition.artifact_type,
        artifact_path=artifact_path,
        field_path=definition.field_path,
        absolute_tolerance=definition.absolute_tolerance,
        observed_difference=observed_difference,
    )


def validate_environment_references(
    base_dir: Path | str,
    run_document: WorkflowRun,
    required_references: Sequence[str],
) -> ReproducibilityDrillCheck:
    provenance_payload = _load_primary_provenance_payload(base_dir, run_document) or {}
    run_references = _collect_run_environment_references(run_document)
    provenance_references = _collect_provenance_environment_references(provenance_payload)

    issues: list[WorkflowIssueDetail] = []
    for reference in required_references:
        if reference not in run_references:
            issues.append(
                WorkflowIssueDetail(
                    code="missing_environment_reference",
                    message=f"Workflow run is missing required environment reference {reference!r}.",
                    field_path=_environment_reference_field_path(reference, scope="run"),
                )
            )
        if reference not in provenance_references:
            issues.append(
                WorkflowIssueDetail(
                    code="missing_environment_reference",
                    message=f"Provenance export is missing required environment reference {reference!r}.",
                    field_path=_environment_reference_field_path(reference, scope="provenance"),
                )
            )

    return ReproducibilityDrillCheck(
        check_id="environment_references_present",
        description="Required stored environment references are present in the rerun record and provenance export.",
        passed=not issues,
        severity="error",
        issues=issues,
    )


def validate_provenance_completeness(
    base_dir: Path | str,
    run_document: WorkflowRun,
) -> tuple[ReproducibilityDrillCheck, list[ArtifactReference]]:
    base_path = Path(base_dir).resolve()
    issues: list[WorkflowIssueDetail] = []
    checked_artifacts: list[ArtifactReference] = []

    if not run_document.provenance_exports:
        issues.append(
            WorkflowIssueDetail(
                code="missing_provenance_export",
                message="Workflow run did not record any provenance exports.",
                field_path="run.provenance_exports",
            )
        )
        return (
            ReproducibilityDrillCheck(
                check_id="provenance_completeness",
                description="Required lineage fields and export files are present for the reproduced run.",
                passed=False,
                severity="error",
                issues=issues,
            ),
            checked_artifacts,
        )

    for export_path in run_document.provenance_exports:
        artifact_type = "ro_crate" if "ro-crate" in export_path else "provenance"
        checked_artifacts.append(
            ArtifactReference(
                artifact_type=artifact_type,
                path=export_path,
                run_id=run_document.run_id,
            )
        )
        if not resolve_artifact_path(base_path, export_path).exists():
            issues.append(
                WorkflowIssueDetail(
                    code="missing_provenance_export",
                    message=f"Expected provenance export {export_path!r} does not exist on disk.",
                    path=export_path,
                )
            )

    provenance_payload = _load_primary_provenance_payload(base_path, run_document)
    if provenance_payload is None:
        issues.append(
            WorkflowIssueDetail(
                code="missing_provenance_export",
                message="Workflow run did not materialize a primary prov.json export.",
                field_path="run.provenance_exports",
            )
        )
    else:
        for field_path in (
            "workflow.workflow_id",
            "workflow.version",
            "workflow.run_record_path",
            "environment.platform",
            "environment.python_version",
        ):
            if _read_mapping_field(provenance_payload, field_path) is _MISSING:
                issues.append(
                    WorkflowIssueDetail(
                        code="missing_provenance_field",
                        message=f"Provenance export is missing required field {field_path!r}.",
                        field_path=field_path,
                    )
                )

        for field_name in ("tool_versions", "entity", "activity", "used", "wasGeneratedBy", "wasAssociatedWith"):
            value = provenance_payload.get(field_name)
            if not value:
                issues.append(
                    WorkflowIssueDetail(
                        code="missing_provenance_field",
                        message=f"Provenance export is missing required lineage collection {field_name!r}.",
                        field_path=field_name,
                    )
                )

        entity_payloads = provenance_payload.get("entity")
        activity_payloads = provenance_payload.get("activity")
        related_artifact_payloads = provenance_payload.get("related_artifacts")
        if isinstance(entity_payloads, dict):
            entity_by_path = {
                item.get("path"): item
                for item in entity_payloads.values()
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            related_artifact_paths = {
                item.get("path")
                for item in (related_artifact_payloads or [])
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            }
            for ref in [*run_document.inputs, *run_document.outputs]:
                entity = entity_by_path.get(ref.path)
                if entity is None and ref.path in related_artifact_paths:
                    continue
                if entity is None:
                    issues.append(
                        WorkflowIssueDetail(
                            code="missing_entity_lineage",
                            message=f"Provenance export is missing lineage for artifact {ref.path!r}.",
                            path=ref.path,
                        )
                    )
                    continue
                entity_hash = entity.get("hash")
                if not (
                    isinstance(entity_hash, dict)
                    and _has_text_value(entity_hash.get("algorithm"))
                    and _has_text_value(entity_hash.get("digest"))
                ):
                    issues.append(
                        WorkflowIssueDetail(
                            code="missing_entity_hash",
                            message=f"Provenance export is missing a content hash for artifact {ref.path!r}.",
                            path=ref.path,
                        )
                    )

        if isinstance(activity_payloads, dict):
            step_ids = {step.id for step in run_document.steps}
            recorded_step_ids = {
                item.get("step_id")
                for item in activity_payloads.values()
                if isinstance(item, dict) and isinstance(item.get("step_id"), str)
            }
            for step_id in sorted(step_ids - recorded_step_ids):
                issues.append(
                    WorkflowIssueDetail(
                        code="missing_step_lineage",
                        message=f"Provenance export is missing an activity record for workflow step {step_id!r}.",
                        field_path=f"activity.{step_id}",
                    )
                )

    return (
        ReproducibilityDrillCheck(
            check_id="provenance_completeness",
            description="Required lineage fields and export files are present for the reproduced run.",
            passed=not issues,
            severity="error",
            issues=issues,
        ),
        _dedupe_refs(checked_artifacts),
    )


def validate_report_bundle_completeness(
    base_dir: Path | str,
    run_document: WorkflowRun,
) -> tuple[ReproducibilityDrillCheck, list[ArtifactReference]]:
    base_path = Path(base_dir).resolve()
    issues: list[WorkflowIssueDetail] = []
    checked_artifacts: list[ArtifactReference] = []
    manifest_payload, manifest_ref = _load_report_bundle_manifest(base_path, run_document)

    if manifest_payload is None or manifest_ref is None:
        issues.append(
            WorkflowIssueDetail(
                code="missing_report_bundle_manifest",
                message="Report bundle manifest was not materialized for the reproduced run.",
                field_path="report_bundle_manifest",
            )
        )
        return (
            ReproducibilityDrillCheck(
                check_id="report_bundle_completeness",
                description="Report bundle outputs and referenced bundle artifacts are complete on disk.",
                passed=False,
                severity="error",
                issues=issues,
            ),
            checked_artifacts,
        )

    checked_artifacts.append(manifest_ref)
    manifest_value = _unwrap_report_bundle_payload(manifest_payload)
    report_markdown_path = manifest_value.get("report_markdown_path")
    if not _has_text_value(report_markdown_path):
        issues.append(
            WorkflowIssueDetail(
                code="missing_report_bundle_field",
                message="Report bundle manifest is missing report_markdown_path.",
                field_path="report_markdown_path",
            )
        )
    else:
        checked_artifacts.append(
            ArtifactReference(
                artifact_type="report_bundle",
                path=str(report_markdown_path),
                run_id=run_document.run_id,
            )
        )
        if not resolve_artifact_path(base_path, str(report_markdown_path)).exists():
            issues.append(
                WorkflowIssueDetail(
                    code="missing_report_bundle_artifact",
                    message=f"Report bundle markdown {report_markdown_path!r} is missing on disk.",
                    path=str(report_markdown_path),
                )
            )

    expected_artifacts = manifest_value.get("expected_artifacts")
    if not isinstance(expected_artifacts, list) or not expected_artifacts:
        issues.append(
            WorkflowIssueDetail(
                code="missing_report_bundle_field",
                message="Report bundle manifest did not record any expected_artifacts.",
                field_path="expected_artifacts",
            )
        )
    else:
        for item in expected_artifacts:
            if not isinstance(item, dict):
                continue
            artifact_type = item.get("artifact_type")
            artifact_path = item.get("path")
            if not isinstance(artifact_type, str) or not isinstance(artifact_path, str):
                continue
            checked_artifacts.append(
                ArtifactReference(
                    artifact_type=artifact_type,
                    path=artifact_path,
                    run_id=run_document.run_id,
                )
            )
            if not resolve_artifact_path(base_path, artifact_path).exists():
                issues.append(
                    WorkflowIssueDetail(
                        code="missing_report_bundle_artifact",
                        message=f"Report bundle expected artifact {artifact_path!r} is missing on disk.",
                        path=artifact_path,
                    )
                )

    missing_artifacts = manifest_value.get("missing_artifacts")
    if isinstance(missing_artifacts, list) and missing_artifacts:
        issues.append(
            WorkflowIssueDetail(
                code="incomplete_report_bundle",
                message="Report bundle manifest recorded missing_artifacts for a reproducibility drill replay.",
                field_path="missing_artifacts",
            )
        )

    return (
        ReproducibilityDrillCheck(
            check_id="report_bundle_completeness",
            description="Report bundle outputs and referenced bundle artifacts are complete on disk.",
            passed=not issues,
            severity="error",
            issues=issues,
        ),
        _dedupe_refs(checked_artifacts),
    )


def validate_compliance_artifact_presence(
    base_dir: Path | str,
    run_document: WorkflowRun,
) -> tuple[ReproducibilityDrillCheck, list[ArtifactReference]]:
    base_path = Path(base_dir).resolve()
    issues: list[WorkflowIssueDetail] = []
    checked_artifacts: list[ArtifactReference] = []

    manifest_payload, _ = _load_report_bundle_manifest(base_path, run_document)
    manifest_value = _unwrap_report_bundle_payload(manifest_payload) if manifest_payload is not None else {}
    compliance_refs = [
        ArtifactReference(
            artifact_type=str(item["artifact_type"]),
            path=str(item["path"]),
            run_id=run_document.run_id,
        )
        for item in manifest_value.get("expected_artifacts", [])
        if isinstance(item, dict)
        and item.get("artifact_type") == "compliance_report"
        and isinstance(item.get("path"), str)
    ]

    if not compliance_refs:
        compliance_refs = [
            ref
            for ref in [*run_document.related_artifacts, *run_document.outputs]
            if ref.artifact_type == "compliance_report"
        ]

    if not compliance_refs:
        issues.append(
            WorkflowIssueDetail(
                code="missing_compliance_artifact",
                message="No compliance_report artifact was linked from the reproduced workflow run.",
                field_path="related_artifacts",
            )
        )
    else:
        for ref in compliance_refs:
            checked_artifacts.append(ref)
            if not resolve_artifact_path(base_path, ref.path).exists():
                issues.append(
                    WorkflowIssueDetail(
                        code="missing_compliance_artifact",
                        message=f"Compliance artifact {ref.path!r} is missing on disk.",
                        path=ref.path,
                    )
                )

    return (
        ReproducibilityDrillCheck(
            check_id="compliance_artifact_presence",
            description="The reproduced run includes a persisted compliance_report artifact.",
            passed=not issues,
            severity="error",
            issues=issues,
        ),
        _dedupe_refs(checked_artifacts),
    )


def _compare_values(
    *,
    actual: Any,
    expected: Any,
    mode: ComparisonMode,
    absolute_tolerance: float | None,
) -> tuple[bool, float | None]:
    if mode == "exact":
        return actual == expected, None
    if not _is_numeric(actual) or not _is_numeric(expected) or absolute_tolerance is None:
        return False, None
    difference = abs(float(actual) - float(expected))
    return difference <= absolute_tolerance, difference


def _find_artifact_reference(run_document: WorkflowRun, artifact_type: str) -> ArtifactReference | None:
    for ref in [*run_document.outputs, *run_document.related_artifacts, *run_document.inputs]:
        if ref.artifact_type == artifact_type:
            return ref
    return None


def _read_artifact_field(base_dir: Path, artifact_path: str, field_path: str) -> Any:
    payload = load_artifact_document(resolve_artifact_path(base_dir, artifact_path)).model_dump(mode="json")
    return _read_mapping_field(payload, field_path)


def _read_mapping_field(payload: Mapping[str, Any], field_path: str) -> Any:
    current: Any = payload
    for segment in field_path.split("."):
        if not segment:
            return _MISSING
        if isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return _MISSING
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
            continue
        if not isinstance(current, Mapping) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _load_primary_provenance_payload(base_dir: Path | str, run_document: WorkflowRun) -> dict[str, Any] | None:
    base_path = Path(base_dir).resolve()
    prov_path = next((path for path in run_document.provenance_exports if path.endswith("prov.json")), None)
    if prov_path is None:
        return None
    candidate = resolve_artifact_path(base_path, prov_path)
    if not candidate.exists():
        return None
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _collect_run_environment_references(run_document: WorkflowRun) -> set[str]:
    references = _collect_mapping_environment_references(
        run_document.environment.model_dump(mode="json")
    )
    for step in run_document.steps:
        if step.external_execution is None:
            continue
        references.update(
            reference.strip()
            for reference in step.external_execution.environment_references
            if _has_text_value(reference)
        )
    return references


def _collect_provenance_environment_references(provenance_payload: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    environment_payload = provenance_payload.get("environment")
    if isinstance(environment_payload, Mapping):
        references.update(_collect_mapping_environment_references(environment_payload))

    activity_payloads = provenance_payload.get("activity")
    if isinstance(activity_payloads, Mapping):
        for activity in activity_payloads.values():
            if not isinstance(activity, Mapping):
                continue
            raw_references = activity.get("environment_references")
            if not isinstance(raw_references, list):
                continue
            references.update(
                reference.strip()
                for reference in raw_references
                if _has_text_value(reference)
            )
    return references


def _collect_mapping_environment_references(payload: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    for field_name, value in payload.items():
        if _has_text_value(value):
            references.add(f"{field_name}:{str(value).strip()}")
    return references


def _environment_reference_field_path(
    reference: str,
    *,
    scope: Literal["run", "provenance"],
) -> str:
    label = reference.split(":", 1)[0].strip().lower()
    if label in _WORKFLOW_ENVIRONMENT_FIELDS:
        prefix = "run.environment" if scope == "run" else "provenance.environment"
        return f"{prefix}.{label}"
    if scope == "run":
        return "run.steps[].external_execution.environment_references"
    return "provenance.activity.*.environment_references"


def _load_report_bundle_manifest(
    base_dir: Path,
    run_document: WorkflowRun,
) -> tuple[dict[str, Any] | None, ArtifactReference | None]:
    base_run_dir = _resolve_run_dir(base_dir, run_document)
    manifest_candidates = sorted(base_run_dir.rglob("report_bundle_manifest.json"))
    if not manifest_candidates:
        return None, None
    manifest_path = manifest_candidates[0]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None, None
    return (
        payload,
        ArtifactReference(
            artifact_type="report_bundle_manifest",
            path=_relative_to_base(base_dir, manifest_path),
            run_id=run_document.run_id,
        ),
    )


def _unwrap_report_bundle_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get("value")
    if isinstance(value, dict):
        return value
    return payload


def _resolve_run_dir(base_dir: Path | str, run_document: WorkflowRun) -> Path:
    base_path = Path(base_dir).resolve()
    candidate_paths = [
        *run_document.provenance_exports,
        *(ref.path for ref in run_document.outputs),
        *(ref.path for ref in run_document.related_artifacts),
    ]
    for relative_path in candidate_paths:
        candidate = resolve_artifact_path(base_path, relative_path)
        for parent in (candidate, *candidate.parents):
            if parent.name == run_document.run_id and (parent / "run.json").exists():
                return parent
    fallback = next(base_path.rglob(f"{run_document.run_id}/run.json"), None)
    if fallback is not None:
        return fallback.parent
    raise ValueError("Unable to resolve run directory for workflow reproducibility drill.")


def _refresh_content_hash_manifest(base_dir: Path, run_dir: Path, run_document: WorkflowRun) -> None:
    entries: dict[str, bytes] = {}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(run_dir).as_posix()
        if relative == CONTENT_HASH_MANIFEST_FILENAME:
            continue
        entries[relative] = path.read_bytes()
    manifest = build_content_hash_manifest(
        run_id=run_document.run_id,
        schema_version=SCHEMA_PACK_VERSION,
        created_at=run_document.created_at,
        source_workflow=run_document.source_workflow or run_document.workflow.slug,
        entries=entries,
    )
    content_hash_path = run_dir / CONTENT_HASH_MANIFEST_FILENAME
    content_hash_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    refresh_artifact_registry_path(base_dir, _relative_to_base(base_dir, content_hash_path))


def _relative_to_base(base_dir: Path | str, path: Path | str) -> str:
    target = Path(path).resolve()
    return target.relative_to(Path(base_dir).resolve()).as_posix()


def _dedupe_refs(refs: Sequence[ArtifactReference]) -> list[ArtifactReference]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for ref in refs:
        key = (ref.artifact_type, ref.path, ref.id, ref.run_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _overall_drill_status(
    comparisons: Sequence[ReproducibilityDrillComparison],
    checks: Sequence[ReproducibilityDrillCheck],
) -> Literal["passed", "failed"]:
    if all(item.passed for item in comparisons) and all(item.passed for item in checks):
        return "passed"
    return "failed"


def _has_text_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
