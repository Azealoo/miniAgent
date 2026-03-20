"""Structured artifact schemas for the BioAPEX core schema pack v1."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from qc_policy import QCPolicyDefinition, QCPolicyEvaluation

from .naming import is_valid_run_id

SCHEMA_PACK_VERSION = "1.0.0"

ArtifactFormat = Literal["json", "yaml"]

ARTIFACT_FORMATS: dict[str, ArtifactFormat] = {
    "dataset_manifest": "yaml",
    "fastqc_run": "json",
    "fastqc_metrics": "json",
    "multiqc_run": "json",
    "multiqc_metrics": "json",
    "count_matrix": "json",
    "normalized_count_matrix": "json",
    "differential_expression_results": "json",
    "differential_expression_run": "json",
    "workflow_run": "json",
    "provenance": "json",
    "biocompute": "json",
    "evidence_card": "yaml",
    "evidence_review": "json",
    "claim_graph": "json",
    "entity_grounding": "json",
    "compliance_report": "json",
    "protocol_run": "yaml",
    "qa_report": "json",
}

_NORMALIZED_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
_NORMALIZE_IDENTIFIER_CHARS_RE = re.compile(r"[^a-z0-9._:-]+")

RiskCategory = Literal[
    "none",
    "biosafety",
    "human_subjects",
    "privacy",
    "dangerous_procedure",
    "export_control",
]
WorkflowLifecycleStatus = Literal[
    "created",
    "preflight_checked",
    "running",
    "waiting",
    "failed",
    "completed",
    "blocked",
]
WorkflowQCStatus = Literal["pending", "passed", "warning", "failed", "not_applicable"]
ConfidenceLevel = Literal["low", "medium", "high"]
ComplianceDisposition = Literal["allow", "allow_with_warning", "require_approval", "block"]
ComplianceRuntimeState = Literal[
    "preflight_pending",
    "allowed",
    "warning_issued",
    "blocked",
    "approval_required",
    "approved_override",
]
ComplianceApprovalScope = Literal["message", "workflow", "run"]
ComplianceDecisionSource = Literal["deterministic_rules", "safe_fallback", "human_override"]
ComplianceBlockStatus = Literal["not_blocked", "blocked"]
ComplianceSeverity = Literal["low", "medium", "high", "critical"]
ProtocolCompletionState = Literal["not_started", "in_progress", "completed", "blocked", "aborted"]
ProtocolStepStatus = Literal["pending", "in_progress", "completed", "blocked", "skipped"]
DeviationSeverity = Literal["minor", "major", "critical"]
DeviationOrigin = Literal["manual", "automatic"]
QAOverallStatus = Literal["passed", "warning", "failed", "blocked"]
QACheckSeverity = Literal["warning", "error", "critical"]
PrivacyClassification = Literal["public", "internal", "controlled", "restricted"]
AnalysisKind = Literal["descriptive", "comparative"]
AssayType = Literal[
    "bulk_rna_seq",
    "scrna_seq",
    "atac_seq",
    "perturb_seq",
    "crispr_screen",
    "proteomics",
    "metabolomics",
    "custom",
]
EvidenceSourceDatabase = Literal["pubmed", "pmc", "uniprot", "ensembl", "doi", "custom"]
EvidenceReviewStatus = Literal["supported", "mixed", "insufficient_evidence"]
GroundedEntityType = Literal["gene", "protein", "transcript"]
GroundedEntitySourceDatabase = Literal["ensembl", "uniprot", "ncbigene", "custom"]
GroundingResultStatus = Literal["resolved", "ambiguous", "unresolved"]
ClaimGraphNodeType = Literal["claim", "evidence_card", "entity", "workflow_result"]
ClaimGraphEdgeType = Literal["supports", "contradicts", "mentions", "derived_from", "evaluated_by"]
ClaimGraphClaimStatus = Literal["proposed", "supported", "mixed", "insufficient_evidence"]
ClaimGraphProvenanceSource = Literal[
    "evidence_card_claim",
    "evidence_review_conclusion",
    "workflow_summary",
]
WorkflowResultArtifactType = Literal["workflow_run", "evidence_review"]
FastQCSequencingLayout = Literal["single_end", "paired_end"]
FastQCReadLabel = Literal["single", "read1", "read2"]
FastQCModuleStatus = Literal["pass", "warn", "fail"]
MatrixFormat = Literal["tsv"]


def _require_non_empty(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def normalize_identifier(value: str) -> str:
    candidate = _require_non_empty(value, field_name="identifier").lower()
    candidate = candidate.replace("/", "-").replace(" ", "-")
    candidate = _NORMALIZE_IDENTIFIER_CHARS_RE.sub("-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("._:-")
    if not candidate or not _NORMALIZED_IDENTIFIER_RE.fullmatch(candidate):
        raise ValueError(
            "Identifiers must use lowercase letters, digits, and separators . _ : - only."
        )
    return candidate


def _require_normalized_identifier(value: str, *, field_name: str) -> str:
    cleaned = _require_non_empty(value, field_name=field_name)
    normalized = normalize_identifier(cleaned)
    if cleaned != normalized:
        raise ValueError(f"{field_name} must already be normalized as {normalized!r}.")
    return normalized


def _require_prefixed_identifier(value: str, *, field_name: str) -> str:
    cleaned = _require_non_empty(value, field_name=field_name)
    prefix, separator, suffix = cleaned.partition(":")
    if separator != ":":
        raise ValueError(f"{field_name} must use the format '<source>:<identifier>'.")
    normalized_prefix = normalize_identifier(prefix)
    normalized_suffix = suffix.strip()
    if not normalized_suffix:
        raise ValueError(f"{field_name} suffix must not be empty.")
    if any(ch.isspace() for ch in normalized_suffix):
        raise ValueError(f"{field_name} must not contain whitespace.")
    normalized = f"{normalized_prefix}:{normalized_suffix}"
    if cleaned != normalized:
        raise ValueError(f"{field_name} must already be normalized as {normalized!r}.")
    return normalized


def _normalize_relative_path(value: str | PurePosixPath) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Path must not be empty.")
    if "\\" in raw:
        raise ValueError("Paths must use forward slashes.")

    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise ValueError("Paths must be relative, not absolute.")
    if candidate.parts == (".",):
        raise ValueError("Paths must not resolve to '.'.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Paths must not contain '..'.")
    return str(candidate)


def _clean_unique_text_list(values: list[str], *, field_name: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = _require_non_empty(item, field_name=field_name)
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _normalize_timestamp(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone information.")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _normalize_legacy_deviation_payload(
    value: Any,
    *,
    parent_run_id: str | None = None,
) -> Any:
    if not isinstance(value, dict):
        return value

    payload = dict(value)
    if parent_run_id and "run_id" not in payload:
        payload["run_id"] = parent_run_id

    legacy_description = payload.get("description")
    if not isinstance(legacy_description, str) or not legacy_description.strip():
        return payload

    description = legacy_description.strip()
    payload.setdefault("actual_behavior", description)
    payload.setdefault(
        "original_expected_behavior",
        "Legacy deviation record did not capture the original expected behavior.",
    )
    payload.setdefault(
        "reason",
        "Imported from a legacy deviation record that stored only a free-text description.",
    )
    payload.setdefault(
        "impact_assessment",
        "Legacy deviation record did not preserve a structured impact assessment and should be reviewed manually.",
    )
    payload.setdefault("author_or_agent", "legacy_record")
    payload.pop("description", None)
    return payload


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    path: str
    id: str | None = None
    run_id: str | None = None

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="artifact_type")

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not is_valid_run_id(value):
            raise ValueError(f"Invalid run_id format: {value!r}")
        return value


class ArtifactDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SCHEMA_PACK_VERSION)
    artifact_type: str
    id: str
    run_id: str
    created_at: datetime
    source_workflow: str | None = None
    source_tool: str | None = None
    source_agent: str | None = None
    related_artifacts: list[ArtifactReference]

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_PACK_VERSION:
            raise ValueError(f"Unsupported schema version {value!r}; expected {SCHEMA_PACK_VERSION!r}.")
        return value

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        if not is_valid_run_id(value):
            raise ValueError(f"Invalid run_id format: {value!r}")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value, field_name="created_at")

    @model_validator(mode="after")
    def _validate_source_context(self) -> "ArtifactDocument":
        if not any((self.source_workflow, self.source_tool)):
            raise ValueError(
                "Artifacts must include at least one of source_workflow or source_tool."
            )
        return self


class DatasetDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_name: str
    experiment_type: str
    condition_summary: str
    analysis_kind: AnalysisKind = "descriptive"
    condition_fields: list[str] | None = None
    batch_fields: list[str] | None = None
    replicate_structure: str | None = None
    timepoints: list[str] = Field(default_factory=list)
    factors: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("study_name", "condition_summary")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("experiment_type")
    @classmethod
    def _validate_experiment_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="experiment_type")

    @field_validator("condition_fields", "batch_fields")
    @classmethod
    def _validate_design_fields(cls, value: list[str] | None, info) -> list[str] | None:
        if value is None:
            return None
        return [_require_non_empty(item, field_name=info.field_name) for item in value]

class DatasetManifest(ArtifactDocument):
    artifact_type: Literal["dataset_manifest"] = "dataset_manifest"
    assay_type: AssayType
    organism: str
    reference_build: str | None = None
    reference_resource: str | None = None
    sample_sheet_path: str | None = None
    privacy_classification: PrivacyClassification
    design: DatasetDesign
    source_files: list[str] = Field(min_length=1)
    qc_policy: QCPolicyDefinition | None = None
    assay_extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("organism")
    @classmethod
    def _validate_normalized_fields(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("reference_build")
    @classmethod
    def _validate_reference_build(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="reference_build")

    @field_validator("reference_resource")
    @classmethod
    def _validate_reference_resource(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="reference_resource")

    @field_validator("sample_sheet_path")
    @classmethod
    def _validate_sample_sheet_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value)

    @field_validator("source_files")
    @classmethod
    def _validate_source_files(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]

    @field_validator("assay_extensions")
    @classmethod
    def _validate_assay_extensions(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[_require_normalized_identifier(str(key), field_name="assay_extensions")] = item
        return normalized


class FastQCInputFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    read_label: FastQCReadLabel
    path: str
    sha256: str
    size_bytes: int
    row_number: int | None = None

    @field_validator("sample_id")
    @classmethod
    def _validate_sample_id(cls, value: str) -> str:
        return _require_non_empty(value, field_name="sample_id")

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="sha256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", cleaned):
            raise ValueError("sha256 must be a 64-character lowercase hexadecimal digest.")
        return cleaned

    @field_validator("size_bytes")
    @classmethod
    def _validate_size_bytes(cls, value: int) -> int:
        if value < 0:
            raise ValueError("size_bytes must be non-negative.")
        return value

    @field_validator("row_number")
    @classmethod
    def _validate_row_number(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 2:
            raise ValueError("row_number must refer to a data row in the sample sheet.")
        return value


class FastQCModuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    module_name: str
    status: FastQCModuleStatus

    @field_validator("module_id")
    @classmethod
    def _validate_module_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="module_id")

    @field_validator("module_name")
    @classmethod
    def _validate_module_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="module_name")


class FastQCReportArtifactSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    read_label: FastQCReadLabel
    html_report: ArtifactReference
    zip_archive: ArtifactReference

    @field_validator("sample_id")
    @classmethod
    def _validate_sample_id(cls, value: str) -> str:
        return _require_non_empty(value, field_name="sample_id")


class FastQCSampleMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    read_label: FastQCReadLabel
    input_file: ArtifactReference
    html_report: ArtifactReference
    zip_archive: ArtifactReference
    total_sequences: int | None = None
    sequences_flagged_as_poor_quality: int | None = None
    sequence_length: str | None = None
    percent_gc: float | None = None
    min_per_base_quality: float | None = None
    module_results: list[FastQCModuleResult] = Field(default_factory=list)
    overall_status: FastQCModuleStatus

    @field_validator("sample_id")
    @classmethod
    def _validate_sample_id(cls, value: str) -> str:
        return _require_non_empty(value, field_name="sample_id")

    @field_validator("sequence_length")
    @classmethod
    def _validate_sequence_length(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="sequence_length")

    @field_validator("total_sequences", "sequences_flagged_as_poor_quality")
    @classmethod
    def _validate_counts(cls, value: int | None, info) -> int | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value

    @model_validator(mode="after")
    def _validate_unique_module_results(self) -> "FastQCSampleMetrics":
        module_ids = [item.module_id for item in self.module_results]
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("module_results may not define duplicate module_id entries.")
        return self


class FastQCModuleAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    module_name: str
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0

    @field_validator("module_id")
    @classmethod
    def _validate_module_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="module_id")

    @field_validator("module_name")
    @classmethod
    def _validate_module_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="module_name")

    @field_validator("pass_count", "warn_count", "fail_count")
    @classmethod
    def _validate_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value


class FastQCAggregateMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequencing_layout: FastQCSequencingLayout
    sample_count: int
    input_file_count: int
    total_reads: int
    total_reads_millions: float
    min_per_base_quality: float | None = None
    fastqc_pass_rate: float
    module_status_counts: list[FastQCModuleAggregate] = Field(default_factory=list)

    @field_validator("sample_count", "input_file_count", "total_reads")
    @classmethod
    def _validate_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value

    @field_validator("total_reads_millions", "fastqc_pass_rate")
    @classmethod
    def _validate_floats(cls, value: float, info) -> float:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        if info.field_name == "fastqc_pass_rate" and value > 1:
            raise ValueError("fastqc_pass_rate must be between 0 and 1.")
        return value

    @model_validator(mode="after")
    def _validate_unique_modules(self) -> "FastQCAggregateMetrics":
        module_ids = [item.module_id for item in self.module_status_counts]
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("module_status_counts may not define duplicate module_id entries.")
        return self


class FastQCRun(ArtifactDocument):
    artifact_type: Literal["fastqc_run"] = "fastqc_run"
    tool_name: Literal["fastqc"] = "fastqc"
    tool_version: str
    sequencing_layout: FastQCSequencingLayout
    sample_sheet_path: str
    output_directory: str
    command: list[str] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_files: list[FastQCInputFileRecord] = Field(min_length=1)
    reports: list[FastQCReportArtifactSet] = Field(min_length=1)
    stdout_path: str | None = None
    stderr_path: str | None = None
    metrics_artifact: ArtifactReference | None = None

    @field_validator("tool_version")
    @classmethod
    def _validate_tool_version(cls, value: str) -> str:
        return _require_non_empty(value, field_name="tool_version")

    @field_validator("sample_sheet_path", "output_directory", "stdout_path", "stderr_path")
    @classmethod
    def _validate_optional_paths(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value)

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="command") for item in value]


class FastQCMetrics(ArtifactDocument):
    artifact_type: Literal["fastqc_metrics"] = "fastqc_metrics"
    tool_name: Literal["fastqc"] = "fastqc"
    tool_version: str
    sequencing_layout: FastQCSequencingLayout
    sample_sheet_path: str
    run_artifact: ArtifactReference | None = None
    sample_metrics: list[FastQCSampleMetrics] = Field(min_length=1)
    aggregate_metrics: FastQCAggregateMetrics

    @field_validator("tool_version")
    @classmethod
    def _validate_tool_version(cls, value: str) -> str:
        return _require_non_empty(value, field_name="tool_version")

    @field_validator("sample_sheet_path")
    @classmethod
    def _validate_sample_sheet_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class MultiQCSampleMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    input_file_count: int
    total_reads: int
    total_reads_millions: float
    min_per_base_quality: float | None = None
    fastqc_status: FastQCModuleStatus

    @field_validator("sample_id")
    @classmethod
    def _validate_sample_id(cls, value: str) -> str:
        return _require_non_empty(value, field_name="sample_id")

    @field_validator("input_file_count", "total_reads")
    @classmethod
    def _validate_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value

    @field_validator("total_reads_millions")
    @classmethod
    def _validate_total_reads_millions(cls, value: float) -> float:
        if value < 0:
            raise ValueError("total_reads_millions must be non-negative.")
        return value


class MultiQCAggregateMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int
    input_file_count: int
    total_reads: int
    total_reads_millions: float
    min_per_base_quality: float | None = None
    fastqc_pass_rate: float
    report_sample_count: int
    report_module_count: int
    report_modules: list[str] = Field(default_factory=list)

    @field_validator("sample_count", "input_file_count", "total_reads", "report_sample_count", "report_module_count")
    @classmethod
    def _validate_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value

    @field_validator("total_reads_millions", "fastqc_pass_rate")
    @classmethod
    def _validate_floats(cls, value: float, info) -> float:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        if info.field_name == "fastqc_pass_rate" and value > 1:
            raise ValueError("fastqc_pass_rate must be between 0 and 1.")
        return value

    @field_validator("report_modules")
    @classmethod
    def _validate_report_modules(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="report_modules") for item in value]

    @model_validator(mode="after")
    def _validate_unique_report_modules(self) -> "MultiQCAggregateMetrics":
        if len(self.report_modules) != len(set(self.report_modules)):
            raise ValueError("report_modules may not define duplicate entries.")
        return self


class MultiQCRun(ArtifactDocument):
    artifact_type: Literal["multiqc_run"] = "multiqc_run"
    tool_name: Literal["multiqc"] = "multiqc"
    tool_version: str
    sample_sheet_path: str
    output_directory: str
    input_directories: list[str] = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    upstream_fastqc_run: ArtifactReference | None = None
    upstream_fastqc_metrics: ArtifactReference | None = None
    report_html: ArtifactReference
    report_data_directory: ArtifactReference | None = None
    report_summary_data: ArtifactReference | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    metrics_artifact: ArtifactReference | None = None

    @field_validator("tool_version")
    @classmethod
    def _validate_tool_version(cls, value: str) -> str:
        return _require_non_empty(value, field_name="tool_version")

    @field_validator("sample_sheet_path", "output_directory", "stdout_path", "stderr_path")
    @classmethod
    def _validate_optional_paths(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value)

    @field_validator("input_directories")
    @classmethod
    def _validate_input_directories(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="command") for item in value]


class MultiQCMetrics(ArtifactDocument):
    artifact_type: Literal["multiqc_metrics"] = "multiqc_metrics"
    tool_name: Literal["multiqc"] = "multiqc"
    tool_version: str
    sample_sheet_path: str
    run_artifact: ArtifactReference | None = None
    upstream_fastqc_run: ArtifactReference | None = None
    upstream_fastqc_metrics: ArtifactReference | None = None
    report_html: ArtifactReference
    report_data_directory: ArtifactReference | None = None
    report_summary_data: ArtifactReference | None = None
    sample_names: list[str] = Field(default_factory=list)
    report_modules: list[str] = Field(default_factory=list)
    sample_metrics: list[MultiQCSampleMetrics] = Field(min_length=1)
    aggregate_metrics: MultiQCAggregateMetrics

    @field_validator("tool_version")
    @classmethod
    def _validate_tool_version(cls, value: str) -> str:
        return _require_non_empty(value, field_name="tool_version")

    @field_validator("sample_sheet_path")
    @classmethod
    def _validate_sample_sheet_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("sample_names", "report_modules")
    @classmethod
    def _validate_string_lists(cls, value: list[str], info) -> list[str]:
        return [_require_non_empty(item, field_name=info.field_name) for item in value]

    @model_validator(mode="after")
    def _validate_unique_strings(self) -> "MultiQCMetrics":
        if len(self.sample_names) != len(set(self.sample_names)):
            raise ValueError("sample_names may not define duplicate entries.")
        if len(self.report_modules) != len(set(self.report_modules)):
            raise ValueError("report_modules may not define duplicate entries.")
        return self


class DifferentialExpressionContrast(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contrast_label: str
    condition_field: str
    baseline_condition: str
    comparison_condition: str

    @field_validator("contrast_label", "condition_field", "baseline_condition", "comparison_condition")
    @classmethod
    def _validate_required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_distinct_conditions(self) -> "DifferentialExpressionContrast":
        if self.baseline_condition == self.comparison_condition:
            raise ValueError("baseline_condition and comparison_condition must differ.")
        return self


class DifferentialExpressionDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_formula: str
    modeled_factors: list[str] = Field(default_factory=list)
    batch_fields_expected: list[str] = Field(default_factory=list)
    batch_fields_modeled: list[str] = Field(default_factory=list)
    missing_batch_fields: list[str] = Field(default_factory=list)
    replicate_counts: dict[str, int] = Field(default_factory=dict)
    minimum_condition_replicates: int

    @field_validator("design_formula")
    @classmethod
    def _validate_design_formula(cls, value: str) -> str:
        return _require_non_empty(value, field_name="design_formula")

    @field_validator("modeled_factors", "batch_fields_expected", "batch_fields_modeled", "missing_batch_fields")
    @classmethod
    def _validate_identifier_lists(cls, value: list[str], info) -> list[str]:
        return [_require_normalized_identifier(item, field_name=info.field_name.rstrip("s")) for item in value]

    @field_validator("replicate_counts")
    @classmethod
    def _validate_replicate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for key, item in value.items():
            condition = _require_non_empty(key, field_name="replicate_counts")
            if item < 0:
                raise ValueError("replicate_counts values must be non-negative.")
            normalized[condition] = item
        return normalized

    @field_validator("minimum_condition_replicates")
    @classmethod
    def _validate_minimum_replicates(cls, value: int) -> int:
        if value < 0:
            raise ValueError("minimum_condition_replicates must be non-negative.")
        return value

    @model_validator(mode="after")
    def _validate_batch_field_consistency(self) -> "DifferentialExpressionDesign":
        expected = set(self.batch_fields_expected)
        modeled = set(self.batch_fields_modeled)
        missing = set(self.missing_batch_fields)
        if not modeled.issubset(expected):
            raise ValueError("batch_fields_modeled must be a subset of batch_fields_expected.")
        if not missing.issubset(expected):
            raise ValueError("missing_batch_fields must be a subset of batch_fields_expected.")
        if modeled & missing:
            raise ValueError("batch fields may not be both modeled and missing.")
        return self


class CountMatrix(ArtifactDocument):
    artifact_type: Literal["count_matrix"] = "count_matrix"
    engine_name: str
    engine_version: str
    matrix_path: str
    matrix_format: MatrixFormat = "tsv"
    sample_sheet_path: str
    condition_field: str
    batch_fields: list[str] = Field(default_factory=list)
    sample_ids: list[str] = Field(min_length=1)
    gene_ids: list[str] = Field(min_length=1)
    library_sizes: dict[str, int] = Field(default_factory=dict)
    upstream_multiqc_run: ArtifactReference | None = None
    upstream_multiqc_metrics: ArtifactReference | None = None

    @field_validator("engine_name")
    @classmethod
    def _validate_engine_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine_name")

    @field_validator("engine_version", "condition_field")
    @classmethod
    def _validate_required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("matrix_path", "sample_sheet_path")
    @classmethod
    def _validate_paths(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("batch_fields")
    @classmethod
    def _validate_batch_fields(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="batch_field") for item in value]

    @field_validator("sample_ids", "gene_ids")
    @classmethod
    def _validate_string_lists(cls, value: list[str], info) -> list[str]:
        return [_require_non_empty(item, field_name=info.field_name.rstrip("s")) for item in value]

    @field_validator("library_sizes")
    @classmethod
    def _validate_library_sizes(cls, value: dict[str, int]) -> dict[str, int]:
        normalized: dict[str, int] = {}
        for sample_id, size in value.items():
            cleaned_sample_id = _require_non_empty(sample_id, field_name="sample_id")
            if size < 0:
                raise ValueError("library_sizes values must be non-negative.")
            normalized[cleaned_sample_id] = size
        return normalized

    @model_validator(mode="after")
    def _validate_uniqueness(self) -> "CountMatrix":
        if len(self.sample_ids) != len(set(self.sample_ids)):
            raise ValueError("sample_ids may not define duplicate entries.")
        if len(self.gene_ids) != len(set(self.gene_ids)):
            raise ValueError("gene_ids may not define duplicate entries.")
        if set(self.library_sizes) - set(self.sample_ids):
            raise ValueError("library_sizes keys must be present in sample_ids.")
        return self


class NormalizedCountMatrix(ArtifactDocument):
    artifact_type: Literal["normalized_count_matrix"] = "normalized_count_matrix"
    engine_name: str
    engine_version: str
    normalization_method: str
    matrix_path: str
    matrix_format: MatrixFormat = "tsv"
    sample_ids: list[str] = Field(min_length=1)
    gene_count: int
    library_size_factors: dict[str, float] = Field(default_factory=dict)
    source_count_matrix: ArtifactReference

    @field_validator("engine_name")
    @classmethod
    def _validate_engine_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine_name")

    @field_validator("engine_version", "normalization_method")
    @classmethod
    def _validate_required_text(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("matrix_path")
    @classmethod
    def _validate_matrix_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("sample_ids")
    @classmethod
    def _validate_sample_ids(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="sample_id") for item in value]

    @field_validator("gene_count")
    @classmethod
    def _validate_gene_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError("gene_count must be at least 1.")
        return value

    @field_validator("library_size_factors")
    @classmethod
    def _validate_size_factors(cls, value: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for sample_id, factor in value.items():
            cleaned_sample_id = _require_non_empty(sample_id, field_name="sample_id")
            if factor <= 0:
                raise ValueError("library_size_factors values must be positive.")
            normalized[cleaned_sample_id] = factor
        return normalized

    @model_validator(mode="after")
    def _validate_samples(self) -> "NormalizedCountMatrix":
        if len(self.sample_ids) != len(set(self.sample_ids)):
            raise ValueError("sample_ids may not define duplicate entries.")
        if set(self.library_size_factors) != set(self.sample_ids):
            raise ValueError("library_size_factors must define one entry per sample_id.")
        return self


class DifferentialExpressionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tested_gene_count: int
    significant_gene_count: int
    upregulated_gene_count: int
    downregulated_gene_count: int
    maximum_absolute_log2_fold_change: float
    top_upregulated_gene: str | None = None
    top_downregulated_gene: str | None = None

    @field_validator("tested_gene_count", "significant_gene_count", "upregulated_gene_count", "downregulated_gene_count")
    @classmethod
    def _validate_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value

    @field_validator("maximum_absolute_log2_fold_change")
    @classmethod
    def _validate_max_log2fc(cls, value: float) -> float:
        if value < 0:
            raise ValueError("maximum_absolute_log2_fold_change must be non-negative.")
        return value

    @field_validator("top_upregulated_gene", "top_downregulated_gene")
    @classmethod
    def _validate_optional_gene(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)


class DifferentialExpressionResults(ArtifactDocument):
    artifact_type: Literal["differential_expression_results"] = "differential_expression_results"
    engine_name: str
    engine_version: str
    design: DifferentialExpressionDesign
    contrast: DifferentialExpressionContrast
    source_count_matrix: ArtifactReference
    normalized_count_matrix: ArtifactReference | None = None
    results_path: str
    result_format: MatrixFormat = "tsv"
    tested_gene_count: int
    significant_gene_count: int
    significance_threshold: float
    diagnostic_plots: list[ArtifactReference] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("engine_name")
    @classmethod
    def _validate_engine_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine_name")

    @field_validator("engine_version")
    @classmethod
    def _validate_engine_version(cls, value: str) -> str:
        return _require_non_empty(value, field_name="engine_version")

    @field_validator("results_path")
    @classmethod
    def _validate_results_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("tested_gene_count", "significant_gene_count")
    @classmethod
    def _validate_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value

    @field_validator("significance_threshold")
    @classmethod
    def _validate_significance_threshold(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("significance_threshold must be between 0 and 1.")
        return value

    @field_validator("warnings")
    @classmethod
    def _validate_warnings(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="warning") for item in value]

    @model_validator(mode="after")
    def _validate_plots(self) -> "DifferentialExpressionResults":
        plot_paths = [item.path for item in self.diagnostic_plots]
        if len(plot_paths) != len(set(plot_paths)):
            raise ValueError("diagnostic_plots may not define duplicate paths.")
        return self


class DifferentialExpressionRun(ArtifactDocument):
    artifact_type: Literal["differential_expression_run"] = "differential_expression_run"
    engine_name: str
    engine_version: str
    design: DifferentialExpressionDesign
    contrast: DifferentialExpressionContrast
    parameters: dict[str, Any] = Field(default_factory=dict)
    batch_adjustment_method: str | None = None
    source_count_matrix: ArtifactReference
    normalized_count_matrix: ArtifactReference | None = None
    results_artifact: ArtifactReference | None = None
    diagnostic_plots: list[ArtifactReference] = Field(min_length=1)
    summary: DifferentialExpressionSummary
    warnings: list[str] = Field(default_factory=list)

    @field_validator("engine_name")
    @classmethod
    def _validate_engine_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine_name")

    @field_validator("engine_version", "batch_adjustment_method")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("warnings")
    @classmethod
    def _validate_warnings(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="warning") for item in value]

    @model_validator(mode="after")
    def _validate_plot_uniqueness(self) -> "DifferentialExpressionRun":
        plot_paths = [item.path for item in self.diagnostic_plots]
        if len(plot_paths) != len(set(plot_paths)):
            raise ValueError("diagnostic_plots may not define duplicate paths.")
        return self


class WorkflowIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="slug")


class WorkflowEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conda_env: str | None = None
    container_image: str | None = None
    platform: str | None = None
    python_version: str | None = None
    hostname: str | None = None


class WorkflowIssueDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    field_path: str | None = None
    path: str | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="code")

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        return _require_non_empty(value, field_name="message")

    @field_validator("field_path", "path")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)


class WorkflowSummaryMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    metric_name: str
    value: Any
    source_artifact: ArtifactReference | None = None

    @field_validator("stage")
    @classmethod
    def _validate_stage(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="stage")

    @field_validator("metric_name")
    @classmethod
    def _validate_metric_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="metric_name")


class WorkflowStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    status: WorkflowLifecycleStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    inputs_resolved: list[ArtifactReference] = Field(default_factory=list)
    outputs_produced: list[ArtifactReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    warning_details: list[WorkflowIssueDetail] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    error_details: list[WorkflowIssueDetail] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")

    @field_validator("start_time", "end_time")
    @classmethod
    def _validate_times(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _normalize_timestamp(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_time_order(self) -> "WorkflowStepRecord":
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("Workflow step end_time must be on or after start_time.")
        return self


class WorkflowRun(ArtifactDocument):
    artifact_type: Literal["workflow_run"] = "workflow_run"
    workflow: WorkflowIdentity
    lifecycle_status: WorkflowLifecycleStatus
    qc_status: WorkflowQCStatus
    engine: str
    parameters: dict[str, Any]
    environment: WorkflowEnvironment
    inputs: list[ArtifactReference]
    outputs: list[ArtifactReference]
    steps: list[WorkflowStepRecord] = Field(default_factory=list)
    provenance_exports: list[str] = Field(default_factory=list)
    biocompute_exports: list[str] = Field(default_factory=list)
    qc_policies: list[QCPolicyDefinition] = Field(default_factory=list)
    qc_policy_results: list[QCPolicyEvaluation] = Field(default_factory=list)
    qc_summary: str | None = None
    summary_metrics: list[WorkflowSummaryMetric] = Field(default_factory=list)
    deviations: list["DeviationRecord"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    warning_details: list[WorkflowIssueDetail] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _backfill_legacy_deviations(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        raw_run_id = value.get("run_id")
        raw_deviations = value.get("deviations")
        if not isinstance(raw_run_id, str) or not isinstance(raw_deviations, list):
            return value
        value = dict(value)
        value["deviations"] = [
            _normalize_legacy_deviation_payload(item, parent_run_id=raw_run_id)
            for item in raw_deviations
        ]
        return value

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine")

    @field_validator("provenance_exports")
    @classmethod
    def _validate_provenance_exports(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]

    @field_validator("biocompute_exports")
    @classmethod
    def _validate_biocompute_exports(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]

    @field_validator("qc_summary")
    @classmethod
    def _validate_qc_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="qc_summary")

    @model_validator(mode="after")
    def _validate_deviation_refs(self) -> "WorkflowRun":
        step_ids = {step.id for step in self.steps}
        for deviation in self.deviations:
            if deviation.run_id != self.run_id:
                raise ValueError("Workflow deviations must use the parent workflow run_id.")
            if deviation.step_id not in step_ids:
                raise ValueError("Workflow deviations must reference an existing workflow step_id.")
        return self


class ProvenanceHashRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: str
    digest: str

    @field_validator("algorithm", "digest")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class ProvenanceBundleFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_package: str
    ro_crate_version: str
    lineage_model: str

    @field_validator("primary_package", "ro_crate_version", "lineage_model")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class ProvenanceWorkflowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    name: str
    slug: str
    version: str | None = None
    engine: str
    run_record_path: str
    lifecycle_status: WorkflowLifecycleStatus
    qc_status: WorkflowQCStatus

    @field_validator("workflow_id", "slug", "engine")
    @classmethod
    def _validate_normalized_fields(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="version")

    @field_validator("run_record_path")
    @classmethod
    def _validate_run_record_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class ProvenanceTerminalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_status: WorkflowLifecycleStatus
    representation: str
    is_partial: bool

    @field_validator("representation")
    @classmethod
    def _validate_representation(cls, value: str) -> str:
        return _require_non_empty(value, field_name="representation")


class ProvenanceExportPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance_path: str
    ro_crate_metadata_path: str
    exported_at: datetime

    @field_validator("provenance_path", "ro_crate_metadata_path")
    @classmethod
    def _validate_paths(cls, value: str, info) -> str:
        return _normalize_relative_path(value)

    @field_validator("exported_at")
    @classmethod
    def _validate_exported_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value, field_name="exported_at")


class ProvenanceEntityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    path: str
    artifact_id: str | None = None
    run_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    hash: ProvenanceHashRecord | None = None
    source_workflow: str | None = None
    source_tool: str | None = None
    source_agent: str | None = None

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="artifact_type")

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("artifact_id")
    @classmethod
    def _validate_artifact_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="artifact_id")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not is_valid_run_id(value):
            raise ValueError(f"Invalid run_id format: {value!r}")
        return value

    @field_validator("roles")
    @classmethod
    def _validate_roles(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="roles") for item in value]

    @field_validator("source_workflow")
    @classmethod
    def _validate_source_workflow(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="source_workflow")

    @field_validator("source_tool", "source_agent")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)


class ProvenanceActivityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    workflow_id: str | None = None
    workflow_name: str | None = None
    workflow_slug: str | None = None
    workflow_version: str | None = None
    step_id: str | None = None
    name: str | None = None
    status: WorkflowLifecycleStatus
    started_at: datetime
    ended_at: datetime
    used_entities: list[str] = Field(default_factory=list)
    generated_entities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="type")

    @field_validator("workflow_id", "workflow_slug", "step_id")
    @classmethod
    def _validate_optional_identifiers(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("workflow_name", "workflow_version", "name")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("started_at", "ended_at")
    @classmethod
    def _validate_times(cls, value: datetime, info) -> datetime:
        return _normalize_timestamp(value, field_name=info.field_name)

    @field_validator("used_entities", "generated_entities")
    @classmethod
    def _validate_entity_ids(cls, value: list[str], info) -> list[str]:
        return [_require_normalized_identifier(item, field_name=info.field_name) for item in value]

    @field_validator("warnings", "errors")
    @classmethod
    def _validate_messages(cls, value: list[str], info) -> list[str]:
        return [_require_non_empty(item, field_name=info.field_name) for item in value]

    @model_validator(mode="after")
    def _validate_time_order(self) -> "ProvenanceActivityRecord":
        if self.ended_at < self.started_at:
            raise ValueError("Provenance activity ended_at must be on or after started_at.")
        return self


class ProvenanceAgentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    name: str
    version: str | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="type")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="version")


class ProvenanceToolVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None
    agent_id: str
    source_artifact_path: str

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="version")

    @field_validator("agent_id")
    @classmethod
    def _validate_agent_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="agent_id")

    @field_validator("source_artifact_path")
    @classmethod
    def _validate_source_artifact_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class ProvenanceUsedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity: str
    entity: str

    @field_validator("activity", "entity")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)


class ProvenanceGenerationRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    activity: str

    @field_validator("entity", "activity")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)


class ProvenanceAssociationRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity: str
    agent: str
    role: str

    @field_validator("activity", "agent", "role")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)


class ProvenanceConformance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ro_crate: str
    prov: str

    @field_validator("ro_crate", "prov")
    @classmethod
    def _validate_urls(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class ProvenanceArtifact(ArtifactDocument):
    artifact_type: Literal["provenance"] = "provenance"
    bundle_format: ProvenanceBundleFormat
    workflow: ProvenanceWorkflowSummary
    terminal_state: ProvenanceTerminalState
    environment: WorkflowEnvironment
    tool_versions: list[ProvenanceToolVersion] = Field(default_factory=list)
    exports: ProvenanceExportPaths
    entity: dict[str, ProvenanceEntityRecord] = Field(default_factory=dict)
    activity: dict[str, ProvenanceActivityRecord] = Field(default_factory=dict)
    agent: dict[str, ProvenanceAgentRecord] = Field(default_factory=dict)
    used: list[ProvenanceUsedRelation] = Field(default_factory=list)
    wasGeneratedBy: list[ProvenanceGenerationRelation] = Field(default_factory=list)
    wasAssociatedWith: list[ProvenanceAssociationRelation] = Field(default_factory=list)
    conforms_to: ProvenanceConformance


BioComputeExportStatus = Literal["full", "partial"]


class BioComputeUri(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: str
    filename: str | None = None
    access_time: datetime | None = None

    @field_validator("uri")
    @classmethod
    def _validate_uri(cls, value: str) -> str:
        return _require_non_empty(value, field_name="uri")

    @field_validator("filename")
    @classmethod
    def _validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="filename")

    @field_validator("access_time")
    @classmethod
    def _validate_access_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _normalize_timestamp(value, field_name="access_time")


class BioComputeContributor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    contribution: list[str] = Field(min_length=1)
    affiliation: str | None = None
    email: str | None = None
    orcid: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")

    @field_validator("contribution")
    @classmethod
    def _validate_contribution(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="contribution") for item in value]

    @field_validator("affiliation", "email", "orcid")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)


class BioComputeProvenanceDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    created: datetime
    modified: datetime
    contributors: list[BioComputeContributor] = Field(min_length=1)
    license: str

    @field_validator("name", "version", "license")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("created", "modified")
    @classmethod
    def _validate_timestamps(cls, value: datetime, info) -> datetime:
        return _normalize_timestamp(value, field_name=info.field_name)


class BioComputeDescriptionXref(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    name: str
    ids: list[str] = Field(default_factory=list)
    access_time: datetime

    @field_validator("namespace", "name")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("ids")
    @classmethod
    def _validate_ids(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="ids") for item in value]

    @field_validator("access_time")
    @classmethod
    def _validate_access_time(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value, field_name="access_time")


class BioComputeNamedUri(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    uri: BioComputeUri

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")


class BioComputePipelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(ge=0)
    name: str
    description: str
    version: str
    prerequisite: list[BioComputeNamedUri] = Field(default_factory=list)
    input_list: list[BioComputeUri] = Field(default_factory=list)
    output_list: list[BioComputeUri] = Field(default_factory=list)

    @field_validator("name", "description", "version")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class BioComputeDescriptionDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1)
    xref: list[BioComputeDescriptionXref] = Field(default_factory=list)
    platform: list[str] = Field(default_factory=list)
    pipeline_steps: list[BioComputePipelineStep] = Field(min_length=1)

    @field_validator("keywords", "platform")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info) -> list[str]:
        return [_require_non_empty(item, field_name=info.field_name) for item in value]


class BioComputeExecutionScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: BioComputeUri


class BioComputeExternalDataEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str

    @field_validator("name", "url")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class BioComputeSoftwarePrerequisite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    uri: BioComputeUri

    @field_validator("name", "version")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class BioComputeExecutionDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: list[BioComputeExecutionScript] = Field(default_factory=list)
    script_driver: str
    software_prerequisites: list[BioComputeSoftwarePrerequisite] = Field(default_factory=list)
    external_data_endpoints: list[BioComputeExternalDataEndpoint] = Field(default_factory=list)
    environment_variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("script_driver")
    @classmethod
    def _validate_script_driver(cls, value: str) -> str:
        return _require_non_empty(value, field_name="script_driver")

    @field_validator("environment_variables")
    @classmethod
    def _validate_environment_variables(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, item in value.items():
            normalized[_require_non_empty(str(key), field_name="environment_variable")] = _require_non_empty(
                str(item),
                field_name="environment_variable_value",
            )
        return normalized


class BioComputeParametricEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    param: str
    value: str
    step: str | None = None

    @field_validator("param")
    @classmethod
    def _validate_param(cls, value: str) -> str:
        return _require_non_empty(value, field_name="param")

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: str) -> str:
        return _require_non_empty(value, field_name="value")

    @field_validator("step")
    @classmethod
    def _validate_step(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="step")


class BioComputeInputSubdomainItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uri: BioComputeUri


class BioComputeOutputSubdomainItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mediatype: str
    uri: BioComputeUri

    @field_validator("mediatype")
    @classmethod
    def _validate_mediatype(cls, value: str) -> str:
        return _require_non_empty(value, field_name="mediatype")


class BioComputeIODomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_subdomain: list[BioComputeInputSubdomainItem] = Field(default_factory=list)
    output_subdomain: list[BioComputeOutputSubdomainItem] = Field(default_factory=list)


class BioComputeErrorEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    observed: Any | None = None
    expected: Any | None = None
    severity: Literal["info", "warning", "error"] | None = None
    messages: list[str] = Field(default_factory=list)

    @field_validator("title", "description")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="message") for item in value]


class BioComputeErrorDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    empirical_error: dict[str, BioComputeErrorEntry] = Field(min_length=1)
    algorithmic_error: dict[str, BioComputeErrorEntry] = Field(min_length=1)

    @field_validator("empirical_error", "algorithmic_error")
    @classmethod
    def _validate_error_maps(cls, value: dict[str, BioComputeErrorEntry], info) -> dict[str, BioComputeErrorEntry]:
        normalized: dict[str, BioComputeErrorEntry] = {}
        for key, item in value.items():
            cleaned = _require_non_empty(key, field_name=info.field_name.rstrip("s"))
            if not (cleaned.startswith("urn:") or "://" in cleaned):
                raise ValueError(
                    f"{info.field_name} keys must be full URIs or URNs so the BioCompute error metric is namespaced."
                )
            normalized[cleaned] = item
        return normalized


class BioComputeExtensionDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_status: BioComputeExportStatus
    export_warnings: list[str] = Field(default_factory=list)
    workflow_run: ArtifactReference
    provenance_exports: list[str] = Field(default_factory=list)
    provenance_artifact: ArtifactReference | None = None
    internal_references: list[ArtifactReference] = Field(default_factory=list)

    @field_validator("export_warnings")
    @classmethod
    def _validate_export_warnings(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="export_warning") for item in value]

    @field_validator("provenance_exports")
    @classmethod
    def _validate_provenance_exports(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]


class BioComputeExtensionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extension_schema: str
    bioapex_extension: BioComputeExtensionDomain

    @field_validator("extension_schema")
    @classmethod
    def _validate_extension_schema(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="extension_schema")
        if "://" not in cleaned:
            raise ValueError("extension_schema must be an absolute URL.")
        return cleaned


class BioComputeArtifact(ArtifactDocument):
    artifact_type: Literal["biocompute"] = "biocompute"
    spec_version: str
    object_id: str
    type: str
    etag: str
    provenance_domain: BioComputeProvenanceDomain
    usability_domain: list[str] = Field(min_length=1)
    description_domain: BioComputeDescriptionDomain
    execution_domain: BioComputeExecutionDomain
    parametric_domain: list[BioComputeParametricEntry] = Field(default_factory=list)
    io_domain: BioComputeIODomain
    error_domain: BioComputeErrorDomain
    extension_domain: list[BioComputeExtensionEntry] = Field(min_length=1)

    @field_validator("spec_version", "object_id")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="type")

    @field_validator("etag")
    @classmethod
    def _validate_etag(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="etag").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", cleaned):
            raise ValueError("etag must be a 64-character lowercase hexadecimal digest.")
        return cleaned

    @field_validator("usability_domain")
    @classmethod
    def _validate_usability_domain(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="usability_domain") for item in value]


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    statement: str
    confidence: ConfidenceLevel

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        return _require_non_empty(value, field_name="statement")


class EntityTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    entity_type: str
    identifier: str | None = None

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="label")

    @field_validator("entity_type")
    @classmethod
    def _validate_entity_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="entity_type")


class GroundedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: GroundedEntityType
    source_database: GroundedEntitySourceDatabase
    stable_identifier: str
    identifier_version: str | None = None
    preferred_label: str
    aliases: list[str] = Field(default_factory=list)
    species: str | None = None
    taxon_id: str | None = None

    @field_validator("stable_identifier")
    @classmethod
    def _validate_stable_identifier(cls, value: str) -> str:
        return _require_prefixed_identifier(value, field_name="stable_identifier")

    @field_validator("identifier_version")
    @classmethod
    def _validate_identifier_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="identifier_version")

    @field_validator("preferred_label")
    @classmethod
    def _validate_preferred_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="preferred_label")

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, value: list[str]) -> list[str]:
        return _clean_unique_text_list(value, field_name="alias")

    @field_validator("species")
    @classmethod
    def _validate_species(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="species")

    @field_validator("taxon_id")
    @classmethod
    def _validate_taxon_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_prefixed_identifier(value, field_name="taxon_id")


class EntityGroundingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_mention: str
    requested_entity_types: list[GroundedEntityType] = Field(min_length=1)
    status: GroundingResultStatus
    requires_clarification: bool = False
    grounded_entity: GroundedEntity | None = None
    candidate_entities: list[GroundedEntity] = Field(default_factory=list)
    note: str | None = None
    cached_source_payload_paths: list[str] = Field(default_factory=list)

    @field_validator("input_mention")
    @classmethod
    def _validate_input_mention(cls, value: str) -> str:
        return _require_non_empty(value, field_name="input_mention")

    @field_validator("requested_entity_types")
    @classmethod
    def _validate_requested_entity_types(
        cls, value: list[GroundedEntityType]
    ) -> list[GroundedEntityType]:
        return list(dict.fromkeys(value))

    @field_validator("note")
    @classmethod
    def _validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="note")

    @field_validator("cached_source_payload_paths")
    @classmethod
    def _validate_cached_source_payload_paths(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]

    @model_validator(mode="after")
    def _validate_resolution_state(self) -> "EntityGroundingResult":
        if self.status == "resolved":
            if self.grounded_entity is None:
                raise ValueError("Resolved grounding results require grounded_entity.")
            if self.requires_clarification:
                raise ValueError("Resolved grounding results cannot require clarification.")
        elif self.grounded_entity is not None:
            raise ValueError("Only resolved grounding results may include grounded_entity.")

        if self.status == "ambiguous":
            if not self.candidate_entities:
                raise ValueError("Ambiguous grounding results require candidate_entities.")
            if not self.requires_clarification:
                raise ValueError("Ambiguous grounding results must require clarification.")
        elif self.requires_clarification and self.status != "ambiguous":
            raise ValueError("Only ambiguous grounding results may require clarification.")

        return self


class EvidenceCard(ArtifactDocument):
    artifact_type: Literal["evidence_card"] = "evidence_card"
    source_database: EvidenceSourceDatabase
    stable_identifier: str
    title: str
    study_type: str | None = None
    claims: list[ExtractedClaim] = Field(min_length=1)
    confidence: ConfidenceLevel
    limitations: list[str] = Field(min_length=1)
    entity_tags: list[EntityTag] = Field(default_factory=list)
    grounded_entities: list[GroundedEntity] = Field(default_factory=list)
    grounding_results: list[EntityGroundingResult] = Field(default_factory=list)
    grounding_requires_clarification: bool = False
    cached_raw_payload_path: str

    @field_validator("stable_identifier")
    @classmethod
    def _validate_stable_identifier(cls, value: str) -> str:
        return _require_prefixed_identifier(value, field_name="stable_identifier")

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _require_non_empty(value, field_name="title")

    @field_validator("study_type")
    @classmethod
    def _validate_study_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="study_type")

    @field_validator("cached_raw_payload_path")
    @classmethod
    def _validate_cached_raw_payload_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @model_validator(mode="after")
    def _validate_grounding_state(self) -> "EvidenceCard":
        observed_requires_clarification = any(
            result.requires_clarification for result in self.grounding_results
        )
        if self.grounding_requires_clarification != observed_requires_clarification:
            raise ValueError(
                "grounding_requires_clarification must match the grounding_results clarification state."
            )
        return self


class ExcludedEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    artifact: ArtifactReference | None = None
    reason: str

    @field_validator("evidence_id")
    @classmethod
    def _validate_evidence_id(cls, value: str) -> str:
        return _require_non_empty(value, field_name="evidence_id")

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _require_non_empty(value, field_name="reason")


class EvidenceReviewSourceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    claim_id: str
    stable_identifier: str
    evidence: ArtifactReference
    confidence: ConfidenceLevel

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        return _require_non_empty(value, field_name="statement")

    @field_validator("claim_id")
    @classmethod
    def _validate_claim_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="claim_id")

    @field_validator("stable_identifier")
    @classmethod
    def _validate_stable_identifier(cls, value: str) -> str:
        return _require_prefixed_identifier(value, field_name="stable_identifier")


class EvidenceReviewConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    support_status: EvidenceReviewStatus
    confidence: ConfidenceLevel
    supporting_evidence: list[ArtifactReference] = Field(default_factory=list)
    limitation_notes: list[str] = Field(default_factory=list)
    conflict_notes: list[str] = Field(default_factory=list)

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        return _require_non_empty(value, field_name="statement")

    @field_validator("limitation_notes", "conflict_notes")
    @classmethod
    def _validate_note_lists(cls, value: list[str], info) -> list[str]:
        return _clean_unique_text_list(value, field_name=info.field_name)


class EvidenceReviewArtifact(ArtifactDocument):
    artifact_type: Literal["evidence_review"] = "evidence_review"
    review_question: str
    review_status: EvidenceReviewStatus
    confidence: ConfidenceLevel
    evidence_included: list[ArtifactReference] = Field(default_factory=list)
    evidence_excluded: list[ExcludedEvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(min_length=1)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    source_facts: list[EvidenceReviewSourceFact] = Field(default_factory=list)
    synthesized_conclusions: list[EvidenceReviewConclusion] = Field(min_length=1)
    unsupported_claims_present: bool = False

    @field_validator("review_question")
    @classmethod
    def _validate_review_question(cls, value: str) -> str:
        return _require_non_empty(value, field_name="review_question")

    @field_validator("limitations", "unresolved_conflicts")
    @classmethod
    def _validate_text_lists(cls, value: list[str], info) -> list[str]:
        return _clean_unique_text_list(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_review_state(self) -> "EvidenceReviewArtifact":
        if self.review_status == "supported" and not self.evidence_included:
            raise ValueError("Supported evidence reviews must include at least one evidence artifact.")
        expected_unsupported = self.review_status != "supported"
        if self.unsupported_claims_present != expected_unsupported:
            raise ValueError(
                "unsupported_claims_present must be true when review_status is not 'supported'."
            )
        if self.evidence_included and not self.source_facts:
            raise ValueError("Evidence reviews with included evidence must record source_facts.")
        return self


class EntityGroundingArtifact(ArtifactDocument):
    artifact_type: Literal["entity_grounding"] = "entity_grounding"
    input_mentions: list[str] = Field(min_length=1)
    requested_species: str | None = None
    requested_entity_types: list[GroundedEntityType] = Field(min_length=1)
    requires_clarification: bool = False
    results: list[EntityGroundingResult] = Field(min_length=1)

    @field_validator("input_mentions")
    @classmethod
    def _validate_input_mentions(cls, value: list[str]) -> list[str]:
        return _clean_unique_text_list(value, field_name="input_mention")

    @field_validator("requested_species")
    @classmethod
    def _validate_requested_species(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="requested_species")

    @field_validator("requested_entity_types")
    @classmethod
    def _validate_requested_entity_types(
        cls, value: list[GroundedEntityType]
    ) -> list[GroundedEntityType]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_result_alignment(self) -> "EntityGroundingArtifact":
        expected_mentions = {mention.casefold() for mention in self.input_mentions}
        observed_mentions = {result.input_mention.casefold() for result in self.results}
        if expected_mentions != observed_mentions:
            raise ValueError("Entity grounding results must correspond to the declared input_mentions.")
        observed_requires_clarification = any(
            result.requires_clarification for result in self.results
        )
        if self.requires_clarification != observed_requires_clarification:
            raise ValueError(
                "requires_clarification must match the per-result clarification state."
            )
        return self


class ClaimGraphClaimProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: ClaimGraphProvenanceSource
    artifact: ArtifactReference
    source_identifier: str | None = None
    note: str | None = None

    @field_validator("source_identifier")
    @classmethod
    def _validate_source_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="source_identifier")

    @field_validator("note")
    @classmethod
    def _validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="note")


class ClaimGraphClaimNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["claim"] = "claim"
    statement: str
    confidence: ConfidenceLevel
    status: ClaimGraphClaimStatus
    provenance: list[ClaimGraphClaimProvenance] = Field(min_length=1)

    @field_validator("node_id")
    @classmethod
    def _validate_node_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="node_id")

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, value: str) -> str:
        return _require_non_empty(value, field_name="statement")


class ClaimGraphEvidenceCardNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["evidence_card"] = "evidence_card"
    artifact: ArtifactReference
    stable_identifier: str
    source_database: EvidenceSourceDatabase
    title: str
    confidence: ConfidenceLevel

    @field_validator("node_id")
    @classmethod
    def _validate_node_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="node_id")

    @field_validator("stable_identifier")
    @classmethod
    def _validate_stable_identifier(cls, value: str) -> str:
        return _require_prefixed_identifier(value, field_name="stable_identifier")

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _require_non_empty(value, field_name="title")


class ClaimGraphEntityNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["entity"] = "entity"
    entity_type: GroundedEntityType
    source_database: GroundedEntitySourceDatabase
    stable_identifier: str
    preferred_label: str
    aliases: list[str] = Field(default_factory=list)
    species: str | None = None
    taxon_id: str | None = None

    @field_validator("node_id")
    @classmethod
    def _validate_node_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="node_id")

    @field_validator("stable_identifier")
    @classmethod
    def _validate_stable_identifier(cls, value: str) -> str:
        return _require_prefixed_identifier(value, field_name="stable_identifier")

    @field_validator("preferred_label")
    @classmethod
    def _validate_preferred_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="preferred_label")

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, value: list[str]) -> list[str]:
        return _clean_unique_text_list(value, field_name="alias")

    @field_validator("species")
    @classmethod
    def _validate_species(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="species")

    @field_validator("taxon_id")
    @classmethod
    def _validate_taxon_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_prefixed_identifier(value, field_name="taxon_id")


class ClaimGraphWorkflowResultNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["workflow_result"] = "workflow_result"
    artifact: ArtifactReference
    artifact_type: WorkflowResultArtifactType
    label: str
    workflow_name: str | None = None
    workflow_slug: str | None = None
    result_status: str | None = None
    confidence: ConfidenceLevel | None = None

    @field_validator("node_id")
    @classmethod
    def _validate_node_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="node_id")

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="label")

    @field_validator("workflow_name")
    @classmethod
    def _validate_workflow_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="workflow_name")

    @field_validator("workflow_slug", "result_status")
    @classmethod
    def _validate_optional_identifiers(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name=info.field_name)


class ClaimGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    edge_type: ClaimGraphEdgeType
    source_node_id: str
    source_node_type: ClaimGraphNodeType
    target_node_id: str
    target_node_type: ClaimGraphNodeType
    provenance_artifact: ArtifactReference | None = None
    rationale: str | None = None

    @field_validator("id", "source_node_id", "target_node_id")
    @classmethod
    def _validate_ids(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="rationale")


class ClaimGraphSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_count: int
    evidence_card_count: int
    entity_count: int
    workflow_result_count: int
    edge_count: int
    contradiction_count: int
    source_artifact_count: int

    @field_validator(
        "claim_count",
        "evidence_card_count",
        "entity_count",
        "workflow_result_count",
        "edge_count",
        "contradiction_count",
        "source_artifact_count",
    )
    @classmethod
    def _validate_non_negative_counts(cls, value: int, info) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be non-negative.")
        return value


class ClaimGraphArtifact(ArtifactDocument):
    artifact_type: Literal["claim_graph"] = "claim_graph"
    source_artifacts: list[ArtifactReference] = Field(min_length=1)
    contradiction_rule_set: str
    claim_nodes: list[ClaimGraphClaimNode] = Field(min_length=1)
    evidence_card_nodes: list[ClaimGraphEvidenceCardNode] = Field(default_factory=list)
    entity_nodes: list[ClaimGraphEntityNode] = Field(default_factory=list)
    workflow_result_nodes: list[ClaimGraphWorkflowResultNode] = Field(default_factory=list)
    edges: list[ClaimGraphEdge] = Field(default_factory=list)
    summary: ClaimGraphSummary

    @field_validator("contradiction_rule_set")
    @classmethod
    def _validate_contradiction_rule_set(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="contradiction_rule_set")

    @model_validator(mode="after")
    def _validate_graph(self) -> "ClaimGraphArtifact":
        node_ids = [
            node.node_id
            for node in [
                *self.claim_nodes,
                *self.evidence_card_nodes,
                *self.entity_nodes,
                *self.workflow_result_nodes,
            ]
        ]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Claim graph nodes must not reuse node_id values.")

        known_nodes = set(node_ids)
        contradiction_count = 0
        edge_ids: set[str] = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                raise ValueError("Claim graph edges must not reuse id values.")
            edge_ids.add(edge.id)
            if edge.source_node_id not in known_nodes or edge.target_node_id not in known_nodes:
                raise ValueError("Claim graph edges must reference known nodes.")
            if edge.edge_type == "contradicts":
                contradiction_count += 1

        if self.summary.claim_count != len(self.claim_nodes):
            raise ValueError("Claim graph summary.claim_count must match claim_nodes.")
        if self.summary.evidence_card_count != len(self.evidence_card_nodes):
            raise ValueError(
                "Claim graph summary.evidence_card_count must match evidence_card_nodes."
            )
        if self.summary.entity_count != len(self.entity_nodes):
            raise ValueError("Claim graph summary.entity_count must match entity_nodes.")
        if self.summary.workflow_result_count != len(self.workflow_result_nodes):
            raise ValueError(
                "Claim graph summary.workflow_result_count must match workflow_result_nodes."
            )
        if self.summary.edge_count != len(self.edges):
            raise ValueError("Claim graph summary.edge_count must match edges.")
        if self.summary.contradiction_count != contradiction_count:
            raise ValueError(
                "Claim graph summary.contradiction_count must match contradicts edges."
            )
        if self.summary.source_artifact_count != len(self.source_artifacts):
            raise ValueError(
                "Claim graph summary.source_artifact_count must match source_artifacts."
            )
        return self


class ComplianceRuleHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    category: RiskCategory
    trigger_text: str
    severity: ComplianceSeverity
    recommended_action: ComplianceDisposition

    @field_validator("rule_id")
    @classmethod
    def _validate_rule_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="rule_id")

    @field_validator("trigger_text")
    @classmethod
    def _validate_trigger_text(cls, value: str) -> str:
        return _require_non_empty(value, field_name="trigger_text")


class ComplianceRequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    attached_identifiers: list[str] = Field(default_factory=list)
    selected_workflow: str | None = None
    session_id: str | None = None

    @field_validator("user_message")
    @classmethod
    def _validate_user_message(cls, value: str) -> str:
        return _require_non_empty(value, field_name="user_message")

    @field_validator("attached_identifiers")
    @classmethod
    def _validate_attached_identifiers(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="attached_identifier") for item in value]

    @field_validator("selected_workflow", "session_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)


class ComplianceApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str
    approval_scope: ComplianceApprovalScope
    approved_at: datetime
    override_for_disposition: ComplianceDisposition
    rationale: str | None = None

    @field_validator("approved_by")
    @classmethod
    def _validate_approved_by(cls, value: str) -> str:
        return _require_non_empty(value, field_name="approved_by")

    @field_validator("approved_at")
    @classmethod
    def _validate_approved_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value, field_name="approved_at")

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="rationale")


class ComplianceReport(ArtifactDocument):
    artifact_type: Literal["compliance_report"] = "compliance_report"
    request_context: ComplianceRequestContext
    risk_category: RiskCategory
    triggered_rules: list[ComplianceRuleHit]
    runtime_state: ComplianceRuntimeState
    decision_source: ComplianceDecisionSource
    preflight_disposition: ComplianceDisposition
    block_status: ComplianceBlockStatus
    human_approval_required: bool
    approval_scope: ComplianceApprovalScope | None = None
    approval: ComplianceApprovalRecord | None = None
    final_disposition: ComplianceDisposition

    @model_validator(mode="after")
    def _validate_consistency(self) -> "ComplianceReport":
        if self.risk_category == "none" and self.triggered_rules:
            raise ValueError("risk_category 'none' cannot include triggered_rules.")
        if self.risk_category != "none" and not self.triggered_rules:
            raise ValueError("Triggered rules are required when risk_category is not 'none'.")
        if self.runtime_state == "preflight_pending":
            raise ValueError("Persisted compliance reports must use a terminal runtime_state.")
        if self.final_disposition == "block" and self.block_status != "blocked":
            raise ValueError("Blocked reports must set block_status to 'blocked'.")
        if self.final_disposition != "block" and self.block_status == "blocked":
            raise ValueError("Only blocked reports may use block_status 'blocked'.")
        if self.final_disposition == "require_approval" and not self.human_approval_required:
            raise ValueError("require_approval reports must set human_approval_required to true.")
        if self.human_approval_required and self.preflight_disposition != "require_approval":
            raise ValueError(
                "human_approval_required may only be true when preflight_disposition is require_approval."
            )
        if self.human_approval_required and self.approval_scope is None:
            raise ValueError("Reports that require approval must record an approval_scope.")
        if not self.human_approval_required and self.approval_scope is not None:
            raise ValueError("approval_scope may only be set when human_approval_required is true.")
        if self.approval is not None and self.approval.approval_scope != self.approval_scope:
            raise ValueError("approval.approval_scope must match approval_scope.")
        if self.runtime_state == "allowed" and self.final_disposition != "allow":
            raise ValueError("allowed runtime_state must end with final_disposition 'allow'.")
        if self.runtime_state == "warning_issued" and self.final_disposition != "allow_with_warning":
            raise ValueError(
                "warning_issued runtime_state must end with final_disposition 'allow_with_warning'."
            )
        if self.runtime_state == "blocked" and self.final_disposition != "block":
            raise ValueError("blocked runtime_state must end with final_disposition 'block'.")
        if self.runtime_state == "approval_required" and self.final_disposition != "require_approval":
            raise ValueError(
                "approval_required runtime_state must end with final_disposition 'require_approval'."
            )
        if self.runtime_state == "approved_override":
            if self.approval is None:
                raise ValueError("approved_override runtime_state requires an approval record.")
            if self.preflight_disposition != "require_approval":
                raise ValueError(
                    "approved_override runtime_state requires preflight_disposition 'require_approval'."
                )
            if self.final_disposition not in {"allow", "allow_with_warning"}:
                raise ValueError(
                    "approved_override runtime_state must resolve to allow or allow_with_warning."
                )
            if self.decision_source != "human_override":
                raise ValueError(
                    "approved_override runtime_state must use decision_source 'human_override'."
                )
        elif self.approval is not None:
            raise ValueError("approval records are only valid for approved_override runtime_state.")
        if self.decision_source == "safe_fallback" and self.preflight_disposition != "require_approval":
            raise ValueError(
                "safe_fallback decision_source must resolve to preflight_disposition 'require_approval'."
            )
        return self


class MaterialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    quantity: str | None = None
    unit: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")


class ReagentLotRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reagent_name: str
    lot_id: str
    vendor: str | None = None
    expiry_date: str | None = None

    @field_validator("reagent_name", "lot_id")
    @classmethod
    def _validate_required_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class EquipmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    asset_id: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_non_empty(value, field_name="name")


class DeviationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    step_id: str
    severity: DeviationSeverity
    origin: DeviationOrigin = "manual"
    logged_at: datetime
    original_expected_behavior: str
    actual_behavior: str
    reason: str
    impact_assessment: str
    author_or_agent: str

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_payload(cls, value: Any) -> Any:
        return _normalize_legacy_deviation_payload(value)

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str) -> str:
        if not is_valid_run_id(value):
            raise ValueError(f"Invalid run_id format: {value!r}")
        return value

    @field_validator("step_id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="step_id")

    @field_validator(
        "original_expected_behavior",
        "actual_behavior",
        "reason",
        "impact_assessment",
        "author_or_agent",
    )
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("logged_at")
    @classmethod
    def _validate_logged_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value, field_name="logged_at")


class ProtocolStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    sequence_number: int
    title: str
    instruction: str
    status: ProtocolStepStatus
    notes: list[str] = Field(default_factory=list)

    @field_validator("step_id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="step_id")

    @field_validator("sequence_number")
    @classmethod
    def _validate_sequence_number(cls, value: int) -> int:
        if value < 1:
            raise ValueError("sequence_number must be at least 1.")
        return value

    @field_validator("title", "instruction")
    @classmethod
    def _validate_text_fields(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: list[str]) -> list[str]:
        return _clean_unique_text_list(value, field_name="notes")


class ProtocolRun(ArtifactDocument):
    artifact_type: Literal["protocol_run"] = "protocol_run"
    protocol_source: ArtifactReference
    operator: str
    sample_ids: list[str] = Field(default_factory=list)
    materials: list[MaterialRecord] = Field(default_factory=list)
    reagent_lots: list[ReagentLotRecord] = Field(default_factory=list)
    equipment: list[EquipmentRecord] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    completion_state: ProtocolCompletionState
    steps: list[ProtocolStepRecord] = Field(default_factory=list)
    deviations: list[DeviationRecord] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _backfill_legacy_deviations(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        raw_run_id = value.get("run_id")
        raw_deviations = value.get("deviations")
        if not isinstance(raw_run_id, str) or not isinstance(raw_deviations, list):
            return value
        value = dict(value)
        value["deviations"] = [
            _normalize_legacy_deviation_payload(item, parent_run_id=raw_run_id)
            for item in raw_deviations
        ]
        return value

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, value: str) -> str:
        return _require_non_empty(value, field_name="operator")

    @field_validator("sample_ids")
    @classmethod
    def _validate_sample_ids(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="sample_id") for item in value]

    @field_validator("assumptions")
    @classmethod
    def _validate_assumptions(cls, value: list[str]) -> list[str]:
        return _clean_unique_text_list(value, field_name="assumptions")

    @field_validator("started_at", "completed_at")
    @classmethod
    def _validate_times(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _normalize_timestamp(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_completion_state(self) -> "ProtocolRun":
        if self.completion_state == "completed" and self.completed_at is None:
            raise ValueError("Completed protocol runs must include completed_at.")
        if self.completion_state in {"in_progress", "completed"} and not self.steps:
            raise ValueError("Active protocol runs must include at least one explicit step.")
        if self.completion_state == "completed" and self.operator == "not_provided":
            raise ValueError("Completed protocol runs must record a real operator.")
        if self.completion_state == "completed" and not self.sample_ids:
            raise ValueError("Completed protocol runs must include at least one sample_id.")
        if self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at must be on or after started_at.")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Protocol steps must not reuse step_id values.")
        sequence_numbers = [step.sequence_number for step in self.steps]
        if len(sequence_numbers) != len(set(sequence_numbers)):
            raise ValueError("Protocol steps must not reuse sequence_number values.")
        for deviation in self.deviations:
            if deviation.run_id != self.run_id:
                raise ValueError("Protocol deviations must use the parent protocol run_id.")
            if deviation.step_id not in step_ids:
                raise ValueError("Protocol deviations must reference an existing protocol step_id.")
        return self


class QACheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    severity: QACheckSeverity
    artifact_type: str | None = None
    remediation: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_non_empty(value, field_name="description")

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="artifact_type")


class MissingArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    expected_path: str | None = None
    rationale: str | None = None

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="artifact_type")

    @field_validator("expected_path")
    @classmethod
    def _validate_expected_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value)

    @model_validator(mode="after")
    def _validate_pointer(self) -> "MissingArtifact":
        if self.expected_path is None and not self.rationale:
            raise ValueError("Missing artifacts must include expected_path or rationale.")
        return self


class QAReport(ArtifactDocument):
    artifact_type: Literal["qa_report"] = "qa_report"
    overall_status: QAOverallStatus
    failed_checks: list[QACheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_artifacts: list[MissingArtifact] = Field(default_factory=list)
    recommended_remediation: list[str] = Field(default_factory=list)
    checklist_artifacts: list[ArtifactReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_failure_context(self) -> "QAReport":
        if self.overall_status in {"failed", "blocked"} and not (
            self.failed_checks or self.missing_artifacts
        ):
            raise ValueError("Failed or blocked QA reports must include failed_checks or missing_artifacts.")
        return self


ArtifactModel = (
    DatasetManifest
    | FastQCRun
    | FastQCMetrics
    | MultiQCRun
    | MultiQCMetrics
    | CountMatrix
    | NormalizedCountMatrix
    | DifferentialExpressionResults
    | DifferentialExpressionRun
    | WorkflowRun
    | ProvenanceArtifact
    | BioComputeArtifact
    | EvidenceCard
    | EvidenceReviewArtifact
    | ClaimGraphArtifact
    | EntityGroundingArtifact
    | ComplianceReport
    | ProtocolRun
    | QAReport
)

_ARTIFACT_MODELS: dict[str, type[ArtifactDocument]] = {
    "dataset_manifest": DatasetManifest,
    "fastqc_run": FastQCRun,
    "fastqc_metrics": FastQCMetrics,
    "multiqc_run": MultiQCRun,
    "multiqc_metrics": MultiQCMetrics,
    "count_matrix": CountMatrix,
    "normalized_count_matrix": NormalizedCountMatrix,
    "differential_expression_results": DifferentialExpressionResults,
    "differential_expression_run": DifferentialExpressionRun,
    "workflow_run": WorkflowRun,
    "provenance": ProvenanceArtifact,
    "biocompute": BioComputeArtifact,
    "evidence_card": EvidenceCard,
    "evidence_review": EvidenceReviewArtifact,
    "claim_graph": ClaimGraphArtifact,
    "entity_grounding": EntityGroundingArtifact,
    "compliance_report": ComplianceReport,
    "protocol_run": ProtocolRun,
    "qa_report": QAReport,
}


def artifact_model_for_type(artifact_type: str) -> type[ArtifactDocument]:
    normalized = _require_normalized_identifier(artifact_type, field_name="artifact_type")
    try:
        return _ARTIFACT_MODELS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported artifact type: {artifact_type!r}") from exc


def schema_format_for_artifact(artifact_type: str) -> ArtifactFormat:
    normalized = _require_normalized_identifier(artifact_type, field_name="artifact_type")
    try:
        return ARTIFACT_FORMATS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported artifact type: {artifact_type!r}") from exc


def validate_artifact_payload(payload: dict[str, Any]) -> ArtifactModel:
    raw_artifact_type = payload.get("artifact_type")
    if not isinstance(raw_artifact_type, str):
        raise ValueError("Artifact payload must include string field 'artifact_type'.")
    model = artifact_model_for_type(raw_artifact_type)
    return model.model_validate(payload)


def load_artifact_document(path: str | Path) -> ArtifactModel:
    artifact_path = Path(path)
    raw_text = artifact_path.read_text(encoding="utf-8")
    if artifact_path.suffix == ".json":
        payload = json.loads(raw_text)
        actual_format: ArtifactFormat = "json"
    elif artifact_path.suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_text)
        actual_format = "yaml"
    else:
        raise ValueError(f"Unsupported artifact file extension: {artifact_path.suffix!r}")

    if not isinstance(payload, dict):
        raise ValueError("Artifact documents must deserialize to a mapping.")

    artifact = validate_artifact_payload(payload)
    expected_format = schema_format_for_artifact(artifact.artifact_type)
    if actual_format != expected_format:
        raise ValueError(
            f"{artifact.artifact_type} expects {expected_format!r} documents, got {actual_format!r}."
        )
    return artifact
