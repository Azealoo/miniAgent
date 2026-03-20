"""File-first checklist definition loading and deterministic scoring helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artifacts import (
    ArtifactReference,
    DatasetManifest,
    EvidenceReviewArtifact,
    WorkflowRun,
    load_artifact_document,
    normalize_identifier,
)

_RULE_SOURCES = {"dataset_manifest", "workflow_run", "report_bundle_manifest", "evidence_reviews"}
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"


def _require_non_empty(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def _normalize_relative_path(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("path must not be empty.")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("path must be relative, not absolute.")
    if "\\" in raw:
        raise ValueError("path must use forward slashes.")
    if raw == "." or "/../" in f"/{raw}/" or raw.startswith("../") or raw.endswith("/.."):
        raise ValueError("path must not contain '..'.")
    return candidate.as_posix()


def _coerce_payload(value: BaseModel | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Unsupported checklist payload source: {type(value)!r}")


def _relative_definition_path(path: Path) -> str:
    return path.resolve().relative_to(_REPO_ROOT).as_posix()


def _value_at_path(payload: Mapping[str, Any], field_path: str) -> Any:
    value: Any = payload
    for segment in field_path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            return None
        value = value[segment]
    return value


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


class ChecklistRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_type: Literal["artifact_present", "field_present", "list_min_items"]
    source: str | None = None
    artifact_type: str | None = None
    field_path: str | None = None
    min_count: int | None = None
    min_items: int | None = None
    minimum_matches: int | None = None

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _require_non_empty(value, field_name="source")
        if cleaned not in _RULE_SOURCES:
            raise ValueError(f"Unsupported checklist rule source {cleaned!r}.")
        return cleaned

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_identifier(value)

    @field_validator("field_path")
    @classmethod
    def _validate_field_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _require_non_empty(value, field_name="field_path")
        if cleaned.startswith(".") or cleaned.endswith(".") or ".." in cleaned:
            raise ValueError("field_path must use dot-separated segments without empty parts.")
        return cleaned

    @field_validator("min_count", "min_items", "minimum_matches")
    @classmethod
    def _validate_positive_ints(cls, value: int | None, info) -> int | None:
        if value is None:
            return None
        if value < 1:
            raise ValueError(f"{info.field_name} must be at least 1 when provided.")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> "ChecklistRule":
        if self.rule_type == "artifact_present":
            if self.artifact_type is None:
                raise ValueError("artifact_present rules require artifact_type.")
            if any(value is not None for value in (self.source, self.field_path, self.min_items, self.minimum_matches)):
                raise ValueError(
                    "artifact_present rules may only define artifact_type and optional min_count."
                )
            return self
        if self.source is None or self.field_path is None:
            raise ValueError(f"{self.rule_type} rules require source and field_path.")
        if self.rule_type == "field_present":
            if self.min_items is not None:
                raise ValueError("field_present rules may not define min_items.")
            return self
        if self.rule_type == "list_min_items":
            if self.min_items is None:
                raise ValueError("list_min_items rules require min_items.")
            return self
        return self


class ChecklistDefinitionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    description: str
    severity: Literal["required", "best_practice"]
    pass_criteria: str
    remediation_guidance: str
    rule: ChecklistRule

    @field_validator("item_id")
    @classmethod
    def _validate_item_id(cls, value: str) -> str:
        return normalize_identifier(value)

    @field_validator("description", "pass_criteria", "remediation_guidance")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class ChecklistDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checklist_id: str
    family: str
    label: str
    version: str
    description: str
    items: list[ChecklistDefinitionItem] = Field(min_length=1)

    @field_validator("checklist_id", "family")
    @classmethod
    def _validate_ids(cls, value: str, info) -> str:
        return normalize_identifier(_require_non_empty(value, field_name=info.field_name))

    @field_validator("label", "version", "description")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_unique_items(self) -> "ChecklistDefinition":
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Checklist definitions may not reuse item_id values.")
        return self


class _ChecklistContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    evaluated_artifacts: list[ArtifactReference]
    dataset_manifest: dict[str, Any] | None = None
    workflow_run: dict[str, Any] | None = None
    report_bundle_manifest: dict[str, Any] | None = None
    evidence_review_refs: list[ArtifactReference] = Field(default_factory=list)
    loadable_evidence_review_refs: list[ArtifactReference] = Field(default_factory=list)
    evidence_reviews: list[dict[str, Any]] = Field(default_factory=list)
    evidence_review_load_errors: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def load_checklist_definitions() -> dict[str, tuple[ChecklistDefinition, str]]:
    definitions: dict[str, tuple[ChecklistDefinition, str]] = {}
    for path in sorted(_DEFINITIONS_DIR.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Checklist definition {path} must deserialize to a mapping.")
        definition = ChecklistDefinition.model_validate(payload)
        definitions[definition.checklist_id] = (definition, _relative_definition_path(path))
    return definitions


def available_checklist_ids() -> list[str]:
    return sorted(load_checklist_definitions().keys())


def _build_context(
    *,
    evaluated_artifacts: list[ArtifactReference],
    dataset_manifest: DatasetManifest | Mapping[str, Any] | None,
    workflow_run: WorkflowRun | Mapping[str, Any] | None,
    report_bundle_manifest: Mapping[str, Any] | None,
    base_dir: Path | str | None,
) -> _ChecklistContext:
    evidence_review_refs = [ref for ref in evaluated_artifacts if ref.artifact_type == "evidence_review"]
    loadable_evidence_review_refs: list[ArtifactReference] = []
    evidence_reviews: list[dict[str, Any]] = []
    evidence_review_load_errors: list[str] = []
    if base_dir is not None:
        base_path = Path(base_dir).resolve()
        for ref in evidence_review_refs:
            try:
                document = load_artifact_document(base_path / ref.path)
                if not isinstance(document, EvidenceReviewArtifact):
                    raise ValueError(f"Expected evidence_review artifact at {ref.path!r}.")
                loadable_evidence_review_refs.append(ref)
                evidence_reviews.append(document.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001 - persist precise load failures in checklist results
                evidence_review_load_errors.append(f"{ref.path}: {exc}")

    return _ChecklistContext(
        evaluated_artifacts=evaluated_artifacts,
        dataset_manifest=_coerce_payload(dataset_manifest),
        workflow_run=_coerce_payload(workflow_run),
        report_bundle_manifest=_coerce_payload(report_bundle_manifest),
        evidence_review_refs=evidence_review_refs,
        loadable_evidence_review_refs=loadable_evidence_review_refs,
        evidence_reviews=evidence_reviews,
        evidence_review_load_errors=evidence_review_load_errors,
    )


def _source_documents(
    context: _ChecklistContext,
    source: str,
) -> tuple[list[tuple[dict[str, Any], list[ArtifactReference]]], list[str]]:
    if source == "dataset_manifest":
        if context.dataset_manifest is None:
            return [], ["dataset_manifest was not available."]
        manifest_ref = next(
            (ref for ref in context.evaluated_artifacts if ref.artifact_type == "dataset_manifest"),
            None,
        )
        refs = [manifest_ref] if manifest_ref is not None else []
        return [(context.dataset_manifest, refs)], []
    if source == "workflow_run":
        if context.workflow_run is None:
            return [], ["workflow_run was not available."]
        run_ref = next(
            (ref for ref in context.evaluated_artifacts if ref.artifact_type == "workflow_run"),
            None,
        )
        refs = [run_ref] if run_ref is not None else []
        return [(context.workflow_run, refs)], []
    if source == "report_bundle_manifest":
        if context.report_bundle_manifest is None:
            return [], ["report_bundle_manifest was not available."]
        return [(context.report_bundle_manifest, [])], []
    if source == "evidence_reviews":
        documents = [
            (payload, [ref])
            for payload, ref in zip(context.evidence_reviews, context.loadable_evidence_review_refs)
        ]
        reasons = list(context.evidence_review_load_errors)
        if not context.evidence_review_refs:
            reasons.append("No evidence_review artifacts were linked for checklist scoring.")
        elif not documents:
            reasons.append("No loadable evidence_review artifacts were available.")
        return documents, reasons
    raise ValueError(f"Unsupported checklist source {source!r}.")


def _evaluate_rule(
    rule: ChecklistRule,
    context: _ChecklistContext,
) -> tuple[Literal["pass", "fail"], str, list[ArtifactReference]]:
    if rule.rule_type == "artifact_present":
        matching_refs = [
            ref for ref in context.evaluated_artifacts if ref.artifact_type == rule.artifact_type
        ]
        required_count = rule.min_count or 1
        if len(matching_refs) >= required_count:
            noun = "artifact" if required_count == 1 else "artifacts"
            return (
                "pass",
                f"Found {len(matching_refs)} {rule.artifact_type} {noun}; required at least {required_count}.",
                matching_refs,
            )
        return (
            "fail",
            f"Found {len(matching_refs)} {rule.artifact_type} artifacts; required at least {required_count}.",
            matching_refs,
        )

    assert rule.source is not None
    assert rule.field_path is not None
    documents, reasons = _source_documents(context, rule.source)
    total_source_records = len(documents)
    if rule.source == "evidence_reviews":
        total_source_records = len(context.evidence_review_refs)
    if total_source_records == 0:
        evidence_refs = list(context.evidence_review_refs) if rule.source == "evidence_reviews" else []
        return "fail", "; ".join(reasons), evidence_refs
    if not documents:
        evidence_refs = list(context.evidence_review_refs) if rule.source == "evidence_reviews" else []
        return "fail", "; ".join(reasons), evidence_refs

    matches = 0
    evidence_refs: list[ArtifactReference] = (
        list(context.evidence_review_refs) if rule.source == "evidence_reviews" else []
    )
    for payload, refs in documents:
        value = _value_at_path(payload, rule.field_path)
        if rule.rule_type == "field_present":
            matched = _is_present(value)
        else:
            matched = isinstance(value, list) and len(value) >= (rule.min_items or 1)
        if matched:
            matches += 1
        if rule.source != "evidence_reviews":
            evidence_refs.extend(refs)

    required_matches = rule.minimum_matches if rule.minimum_matches is not None else total_source_records
    record_label = "linked source records" if rule.source == "evidence_reviews" else "checked source records"
    if matches >= required_matches:
        if rule.rule_type == "field_present":
            rationale = (
                f"Field {rule.field_path!r} was present in {matches} of {total_source_records} {record_label}."
            )
        else:
            rationale = (
                f"List field {rule.field_path!r} met the minimum length in {matches} of {total_source_records} {record_label}."
            )
        return "pass", rationale, evidence_refs

    if rule.rule_type == "field_present":
        failure = (
            f"Field {rule.field_path!r} was present in {matches} of {total_source_records} {record_label}; required {required_matches}."
        )
    else:
        failure = (
            f"List field {rule.field_path!r} met the minimum length in {matches} of {total_source_records} {record_label}; required {required_matches}."
        )
    if reasons:
        failure = f"{failure} {'; '.join(reasons)}"
    return "fail", failure, evidence_refs


def _evaluation_status_from_items(items: list[dict[str, Any]]) -> str:
    if any(item["status"] == "fail" and item["severity"] == "required" for item in items):
        return "blocked"
    if any(item["status"] == "fail" and item["severity"] == "best_practice" for item in items):
        return "warning"
    if any(item["status"] == "pass" for item in items):
        return "passed"
    return "not_applicable"


def build_checklist_results_payload(
    checklist_ids: list[str],
    *,
    run_id: str,
    source_workflow: str,
    subject_type: Literal["workflow_run", "report_bundle", "protocol_run", "evidence_review", "qa_review", "custom"],
    subject_label: str,
    evaluated_artifacts: list[ArtifactReference | Mapping[str, Any]],
    dataset_manifest: DatasetManifest | Mapping[str, Any] | None = None,
    workflow_run: WorkflowRun | Mapping[str, Any] | None = None,
    report_bundle_manifest: Mapping[str, Any] | None = None,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    refs = [
        ref if isinstance(ref, ArtifactReference) else ArtifactReference.model_validate(ref)
        for ref in evaluated_artifacts
    ]
    context = _build_context(
        evaluated_artifacts=refs,
        dataset_manifest=dataset_manifest,
        workflow_run=workflow_run,
        report_bundle_manifest=report_bundle_manifest,
        base_dir=base_dir,
    )

    definitions = load_checklist_definitions()
    evaluations: list[dict[str, Any]] = []
    for checklist_id in checklist_ids:
        try:
            definition, definition_path = definitions[checklist_id]
        except KeyError as exc:
            raise ValueError(f"Unknown checklist definition {checklist_id!r}.") from exc

        items: list[dict[str, Any]] = []
        for definition_item in definition.items:
            status, rationale, evidence_refs = _evaluate_rule(definition_item.rule, context)
            items.append(
                {
                    "item_id": definition_item.item_id,
                    "description": definition_item.description,
                    "severity": definition_item.severity,
                    "pass_criteria": definition_item.pass_criteria,
                    "remediation_guidance": definition_item.remediation_guidance,
                    "status": status,
                    "rationale": rationale,
                    "evidence_artifacts": [
                        ref.model_dump(mode="json")
                        for ref in {ref.path: ref for ref in evidence_refs}.values()
                    ],
                }
            )

        evaluations.append(
            {
                "checklist_id": definition.checklist_id,
                "family": definition.family,
                "label": definition.label,
                "version": definition.version,
                "definition_path": definition_path,
                "overall_status": _evaluation_status_from_items(items),
                "items": items,
                "summary": {
                    "total_items": len(items),
                    "passed_items": sum(1 for item in items if item["status"] == "pass"),
                    "failed_required_items": sum(
                        1 for item in items if item["status"] == "fail" and item["severity"] == "required"
                    ),
                    "failed_best_practice_items": sum(
                        1
                        for item in items
                        if item["status"] == "fail" and item["severity"] == "best_practice"
                    ),
                    "not_applicable_items": sum(
                        1 for item in items if item["status"] == "not_applicable"
                    ),
                },
            }
        )

    overall_status = "not_applicable"
    if any(item["overall_status"] == "blocked" for item in evaluations):
        overall_status = "blocked"
    elif any(item["overall_status"] == "warning" for item in evaluations):
        overall_status = "warning"
    elif any(item["overall_status"] == "passed" for item in evaluations):
        overall_status = "passed"

    notes: list[str] = []
    if not evaluations:
        notes.append("No applicable checklist definitions were selected for this subject.")
    notes.extend(context.evidence_review_load_errors)

    return {
        "run_id": run_id,
        "source_workflow": source_workflow,
        "subject_type": subject_type,
        "subject_label": subject_label,
        "evaluated_artifacts": [ref.model_dump(mode="json") for ref in refs],
        "overall_status": overall_status,
        "evaluations": evaluations,
        "summary": {
            "evaluated_checklist_count": len(evaluations),
            "passed_checklist_count": sum(
                1 for item in evaluations if item["overall_status"] == "passed"
            ),
            "warning_checklist_count": sum(
                1 for item in evaluations if item["overall_status"] == "warning"
            ),
            "blocked_checklist_count": sum(
                1 for item in evaluations if item["overall_status"] == "blocked"
            ),
            "not_applicable_checklist_count": sum(
                1 for item in evaluations if item["overall_status"] == "not_applicable"
            ),
            "failed_required_item_count": sum(
                item["summary"]["failed_required_items"] for item in evaluations
            ),
            "failed_best_practice_item_count": sum(
                item["summary"]["failed_best_practice_items"] for item in evaluations
            ),
        },
        "notes": notes,
    }


def checklist_failed_checks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    failed_checks: list[dict[str, Any]] = []
    for evaluation in payload.get("evaluations", []):
        if not isinstance(evaluation, Mapping):
            continue
        checklist_id = str(evaluation.get("checklist_id", "checklist")).strip() or "checklist"
        label = str(evaluation.get("label", checklist_id)).strip() or checklist_id
        for item in evaluation.get("items", []):
            if not isinstance(item, Mapping):
                continue
            if item.get("status") != "fail" or item.get("severity") != "required":
                continue
            item_id = str(item.get("item_id", "item")).strip() or "item"
            failed_checks.append(
                {
                    "id": normalize_identifier(f"{checklist_id}-{item_id}"),
                    "description": f"{label}: {str(item.get('description', '')).strip()}",
                    "severity": "error",
                    "artifact_type": "checklist_results",
                    "remediation": str(item.get("remediation_guidance", "")).strip()
                    or "Review the checklist artifact and supply the missing required information.",
                }
            )
    return failed_checks


def checklist_warning_messages(payload: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    for evaluation in payload.get("evaluations", []):
        if not isinstance(evaluation, Mapping):
            continue
        label = str(evaluation.get("label", evaluation.get("checklist_id", "checklist"))).strip()
        for item in evaluation.get("items", []):
            if not isinstance(item, Mapping):
                continue
            if item.get("status") != "fail" or item.get("severity") != "best_practice":
                continue
            description = str(item.get("description", "")).strip()
            if description:
                warnings.append(f"{label}: {description}")
    for note in payload.get("notes", []):
        if isinstance(note, str) and note.strip():
            candidate = note.strip()
            if candidate.startswith("No applicable checklist definitions were selected"):
                continue
            warnings.append(candidate)
    deduped: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        key = warning.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def checklist_recommended_remediation(payload: Mapping[str, Any]) -> list[str]:
    guidance: list[str] = []
    for evaluation in payload.get("evaluations", []):
        if not isinstance(evaluation, Mapping):
            continue
        for item in evaluation.get("items", []):
            if not isinstance(item, Mapping):
                continue
            if item.get("status") != "fail":
                continue
            remediation = item.get("remediation_guidance")
            if isinstance(remediation, str) and remediation.strip():
                guidance.append(remediation.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in guidance:
        key = entry.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped
