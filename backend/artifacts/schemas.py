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
    "workflow_run": "json",
    "evidence_card": "yaml",
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
DeviationSeverity = Literal["minor", "major", "critical"]
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
FastQCSequencingLayout = Literal["single_end", "paired_end"]
FastQCReadLabel = Literal["single", "read1", "read2"]
FastQCModuleStatus = Literal["pass", "warn", "fail"]


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


def _normalize_timestamp(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must include timezone information.")
    return value.astimezone(timezone.utc).replace(microsecond=0)


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
    qc_policies: list[QCPolicyDefinition] = Field(default_factory=list)
    qc_policy_results: list[QCPolicyEvaluation] = Field(default_factory=list)
    qc_summary: str | None = None
    summary_metrics: list[WorkflowSummaryMetric] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    warning_details: list[WorkflowIssueDetail] = Field(default_factory=list)

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine")

    @field_validator("provenance_exports")
    @classmethod
    def _validate_provenance_exports(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item) for item in value]

    @field_validator("qc_summary")
    @classmethod
    def _validate_qc_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="qc_summary")


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

    step_id: str
    severity: DeviationSeverity
    description: str
    logged_at: datetime

    @field_validator("step_id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="step_id")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_non_empty(value, field_name="description")

    @field_validator("logged_at")
    @classmethod
    def _validate_logged_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value, field_name="logged_at")


class ProtocolRun(ArtifactDocument):
    artifact_type: Literal["protocol_run"] = "protocol_run"
    protocol_source: ArtifactReference
    operator: str
    sample_ids: list[str] = Field(min_length=1)
    materials: list[MaterialRecord] = Field(default_factory=list)
    reagent_lots: list[ReagentLotRecord] = Field(default_factory=list)
    equipment: list[EquipmentRecord] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
    completion_state: ProtocolCompletionState
    deviations: list[DeviationRecord] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, value: str) -> str:
        return _require_non_empty(value, field_name="operator")

    @field_validator("sample_ids")
    @classmethod
    def _validate_sample_ids(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="sample_id") for item in value]

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
        if self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at must be on or after started_at.")
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
    | WorkflowRun
    | EvidenceCard
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
    "workflow_run": WorkflowRun,
    "evidence_card": EvidenceCard,
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
