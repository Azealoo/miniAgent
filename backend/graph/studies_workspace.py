"""Study Dossier v1 read model derived from artifact registry records."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from artifacts import ArtifactRegistry, load_artifact_document
from artifacts.registry import ArtifactRegistryRecord


_EXPORT_ARTIFACT_TYPES = {"provenance", "biocompute", "eln_export", "eln_export_archive"}
_WORKFLOW_ACTIVE_STATES = {"created", "preflight_checked", "running", "waiting"}
_QA_CHECKLIST_NOT_STARTED = "not_started"


@dataclass(frozen=True)
class StudyArtifactCounts:
    dataset_manifests: int
    workflow_runs: int
    evidence_reviews: int
    claim_graphs: int
    compliance_reports: int
    qa_reports: int
    checklist_results: int
    exports: int


@dataclass(frozen=True)
class StudySummary:
    study_id: str
    title: str
    assay_type: str
    organism: str
    privacy_classification: str
    latest_activity_at: str | None
    run_count: int
    active_run_state: str
    evidence_state: str
    compliance_state: str
    qa_state: str
    export_available: bool
    artifact_counts: StudyArtifactCounts


@dataclass(frozen=True)
class StudiesWorkspaceResponse:
    items: list[StudySummary]


def list_studies_workspace(base_dir: str | Path) -> dict[str, Any]:
    registry = ArtifactRegistry(base_dir)
    snapshot = registry.ensure_snapshot()
    grouped_records = _group_records_by_dataset_id(snapshot.records)

    summaries = [
        summary
        for dataset_id, records in grouped_records.items()
        if (summary := _build_study_summary(Path(base_dir), dataset_id, records)) is not None
    ]
    summaries.sort(key=_study_summary_sort_key, reverse=True)
    return asdict(StudiesWorkspaceResponse(items=summaries))


def _group_records_by_dataset_id(
    records: Iterable[ArtifactRegistryRecord],
) -> dict[str, list[ArtifactRegistryRecord]]:
    grouped: dict[str, list[ArtifactRegistryRecord]] = defaultdict(list)
    for record in records:
        if record.status != "valid":
            continue
        dataset_id = _clean_text(record.dataset_id)
        if dataset_id is None:
            continue
        grouped[dataset_id].append(record)
    return grouped


def _build_study_summary(
    base_dir: Path,
    study_id: str,
    records: list[ArtifactRegistryRecord],
) -> StudySummary | None:
    manifest = _load_latest_document(base_dir, records, "dataset_manifest")
    if manifest is None:
        return None

    latest_activity = max((_record_activity_timestamp(record) for record in records), default=None)
    counts = _build_counts(records)

    workflow_run = _load_latest_document(base_dir, records, "workflow_run")
    evidence_review = _load_latest_document(base_dir, records, "evidence_review")
    compliance_report = _load_latest_document(base_dir, records, "compliance_report")
    qa_report = _load_latest_document(base_dir, records, "qa_report")
    checklist_results = _load_latest_document(base_dir, records, "checklist_results")

    qa_state = (
        _clean_text(getattr(qa_report, "overall_status", None))
        if qa_report is not None
        else _map_checklist_state(
            _clean_text(getattr(checklist_results, "overall_status", None))
        )
    )

    return StudySummary(
        study_id=study_id,
        title=manifest.design.study_name,
        assay_type=manifest.assay_type,
        organism=manifest.organism,
        privacy_classification=manifest.privacy_classification,
        latest_activity_at=_isoformat_or_none(latest_activity),
        run_count=len({record.run_id for record in records if _clean_text(record.run_id) is not None}),
        active_run_state=_map_workflow_state(_clean_text(getattr(workflow_run, "lifecycle_status", None))),
        evidence_state=_clean_text(getattr(evidence_review, "review_status", None)) or _QA_CHECKLIST_NOT_STARTED,
        compliance_state=_clean_text(getattr(compliance_report, "runtime_state", None)) or _QA_CHECKLIST_NOT_STARTED,
        qa_state=qa_state,
        export_available=counts.exports > 0,
        artifact_counts=counts,
    )


def _load_latest_document(
    base_dir: Path,
    records: list[ArtifactRegistryRecord],
    artifact_type: str,
) -> Any | None:
    ordered_records = sorted(
        (record for record in records if record.artifact_type == artifact_type),
        key=_record_sort_key,
        reverse=True,
    )

    for record in ordered_records:
        try:
            return load_artifact_document(base_dir / record.path)
        except Exception:
            continue
    return None


def _build_counts(records: list[ArtifactRegistryRecord]) -> StudyArtifactCounts:
    type_counts = Counter(record.artifact_type for record in records)
    export_count = sum(type_counts[artifact_type] for artifact_type in _EXPORT_ARTIFACT_TYPES)
    return StudyArtifactCounts(
        dataset_manifests=type_counts["dataset_manifest"],
        workflow_runs=type_counts["workflow_run"],
        evidence_reviews=type_counts["evidence_review"],
        claim_graphs=type_counts["claim_graph"],
        compliance_reports=type_counts["compliance_report"],
        qa_reports=type_counts["qa_report"],
        checklist_results=type_counts["checklist_results"],
        exports=export_count,
    )


def _record_activity_timestamp(record: ArtifactRegistryRecord) -> datetime:
    return record.created_at or record.indexed_at


def _record_sort_key(record: ArtifactRegistryRecord) -> tuple[datetime, str]:
    return (_record_activity_timestamp(record), record.path)


def _study_summary_sort_key(summary: StudySummary) -> tuple[int, str, str]:
    latest_activity = summary.latest_activity_at or ""
    return (1 if latest_activity else 0, latest_activity, summary.study_id)


def _map_workflow_state(value: str | None) -> str:
    if value is None:
        return "not_started"
    if value in _WORKFLOW_ACTIVE_STATES:
        return "active"
    if value in {"blocked", "failed", "completed"}:
        return value
    return "not_started"


def _map_checklist_state(value: str | None) -> str:
    if value is None or value == "not_applicable":
        return _QA_CHECKLIST_NOT_STARTED
    return value


def _isoformat_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
