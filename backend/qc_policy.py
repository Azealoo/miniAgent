"""Typed QC policy models and evaluation helpers."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QCCheckStatus = Literal["pass", "warn", "fail"]
QCCheckCategory = Literal["technical", "batch_effect", "experimental_design"]
QCThresholdDirection = Literal["minimum", "maximum"]

_NORMALIZED_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:[._:-][a-z0-9]+)*$")
_NORMALIZE_IDENTIFIER_CHARS_RE = re.compile(r"[^a-z0-9._:-]+")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _require_non_empty(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def normalize_qc_identifier(value: str, *, field_name: str) -> str:
    candidate = _require_non_empty(value, field_name=field_name).lower()
    candidate = candidate.replace("/", "-").replace(" ", "-")
    candidate = _NORMALIZE_IDENTIFIER_CHARS_RE.sub("-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("._:-")
    if not candidate or not _NORMALIZED_IDENTIFIER_RE.fullmatch(candidate):
        raise ValueError(
            f"{field_name} must use lowercase letters, digits, and separators . _ : - only."
        )
    return candidate


def _require_normalized_identifier(value: str, *, field_name: str) -> str:
    cleaned = _require_non_empty(value, field_name=field_name)
    normalized = normalize_qc_identifier(cleaned, field_name=field_name)
    if cleaned != normalized:
        raise ValueError(f"{field_name} must already be normalized as {normalized!r}.")
    return normalized


def _normalize_relative_path(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("path must not be empty.")
    if raw.startswith("/"):
        raise ValueError("path must be relative, not absolute.")
    if "\\" in raw:
        raise ValueError("path must use forward slashes.")
    if raw == "." or "/../" in f"/{raw}/" or raw.startswith("../") or raw.endswith("/.."):
        raise ValueError("path must not contain '..'.")
    return raw


class QCSourceArtifact(BaseModel):
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
        return _require_non_empty(value, field_name="run_id")


class QCObservedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str
    observed_value: Any
    source_artifact: QCSourceArtifact | None = None

    @field_validator("metric_name")
    @classmethod
    def _validate_metric_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="metric_name")


class QCEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream_tools: list[str] = Field(default_factory=list)
    metrics: list[QCObservedMetric] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("upstream_tools")
    @classmethod
    def _validate_upstream_tools(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="upstream_tool") for item in value]

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="notes")

    @model_validator(mode="after")
    def _validate_unique_metrics(self) -> "QCEvidence":
        metric_names = [item.metric_name for item in self.metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("metrics may not define duplicate metric_name entries.")
        return self


class QCMetricExpectationOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    pass_threshold: float | None = None
    warn_threshold: float | None = None

    @field_validator("check_id")
    @classmethod
    def _validate_check_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="check_id")

    @model_validator(mode="after")
    def _validate_override(self) -> "QCMetricExpectationOverride":
        if self.pass_threshold is None and self.warn_threshold is None:
            raise ValueError("QC metric overrides must set pass_threshold or warn_threshold.")
        return self


class QCAssayOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assay_type: str
    check_overrides: list[QCMetricExpectationOverride] = Field(min_length=1)

    @field_validator("assay_type")
    @classmethod
    def _validate_assay_type(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="assay_type")

    @model_validator(mode="after")
    def _validate_unique_override_targets(self) -> "QCAssayOverride":
        check_ids = [item.check_id for item in self.check_overrides]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("Assay overrides may not define duplicate check_id entries.")
        return self


class QCMetricExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    metric_name: str
    category: QCCheckCategory
    comparison: QCThresholdDirection
    pass_threshold: float
    warn_threshold: float | None = None
    description: str | None = None

    @field_validator("id", "metric_name")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="label")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="description")

    @model_validator(mode="after")
    def _validate_threshold_order(self) -> "QCMetricExpectation":
        if self.warn_threshold is None:
            return self
        if self.comparison == "minimum" and self.warn_threshold > self.pass_threshold:
            raise ValueError("minimum comparisons require warn_threshold <= pass_threshold.")
        if self.comparison == "maximum" and self.warn_threshold < self.pass_threshold:
            raise ValueError("maximum comparisons require warn_threshold >= pass_threshold.")
        return self


class QCPolicyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    label: str
    version: str
    assay_type: str | None = None
    required_upstream_tools: list[str] = Field(default_factory=list)
    checks: list[QCMetricExpectation] = Field(min_length=1)
    assay_overrides: list[QCAssayOverride] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("policy_id")
    @classmethod
    def _validate_policy_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="policy_id")

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="label")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="version")
        if not _SEMVER_RE.fullmatch(cleaned):
            raise ValueError("version must use semantic version format 'x.y.z'.")
        return cleaned

    @field_validator("assay_type")
    @classmethod
    def _validate_assay_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="assay_type")

    @field_validator("required_upstream_tools")
    @classmethod
    def _validate_required_upstream_tools(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="required_upstream_tool") for item in value]

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="notes")

    @model_validator(mode="after")
    def _validate_uniqueness(self) -> "QCPolicyDefinition":
        check_ids = [item.id for item in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("QC policies may not define duplicate check ids.")
        if len(self.required_upstream_tools) != len(set(self.required_upstream_tools)):
            raise ValueError("QC policies may not define duplicate required_upstream_tools.")

        known_checks = {item.id for item in self.checks}
        assay_types = [item.assay_type for item in self.assay_overrides]
        if len(assay_types) != len(set(assay_types)):
            raise ValueError("QC policies may not define duplicate assay_overrides for the same assay_type.")
        for override in self.assay_overrides:
            unknown = sorted(item.check_id for item in override.check_overrides if item.check_id not in known_checks)
            if unknown:
                raise ValueError(
                    "QC assay overrides must reference known checks: " + ", ".join(unknown) + "."
                )
        return self


class QCCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    label: str
    metric_name: str
    category: QCCheckCategory
    status: QCCheckStatus
    observed_value: Any = None
    threshold: str
    source_artifact: QCSourceArtifact | None = None
    message: str

    @field_validator("check_id", "metric_name")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("label", "threshold", "message")
    @classmethod
    def _validate_text(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)


class QCPolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    label: str
    version: str
    assay_type: str | None = None
    applied_assay_override: str | None = None
    gate_id: str | None = None
    stage: str | None = None
    required_upstream_tools: list[str] = Field(default_factory=list)
    missing_upstream_tools: list[str] = Field(default_factory=list)
    overall_status: QCCheckStatus
    checks: list[QCCheckResult] = Field(default_factory=list)
    summary: str

    @field_validator("policy_id")
    @classmethod
    def _validate_policy_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="policy_id")

    @field_validator("label", "version", "summary")
    @classmethod
    def _validate_text(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("assay_type", "applied_assay_override", "gate_id", "stage")
    @classmethod
    def _validate_optional_identifiers(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("required_upstream_tools", "missing_upstream_tools")
    @classmethod
    def _validate_tool_lists(cls, value: list[str], info) -> list[str]:
        return [_require_normalized_identifier(item, field_name=info.field_name.rstrip("s")) for item in value]


def _format_threshold(expectation: QCMetricExpectation) -> str:
    pass_value = f"{expectation.pass_threshold:g}"
    if expectation.warn_threshold is None:
        comparator = ">=" if expectation.comparison == "minimum" else "<="
        return f"{comparator} {pass_value}"

    warn_value = f"{expectation.warn_threshold:g}"
    if expectation.comparison == "minimum":
        return f">= {pass_value} pass; >= {warn_value} warn"
    return f"<= {pass_value} pass; <= {warn_value} warn"


def _coerce_numeric_metric(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Observed metric value must be numeric.")
    return float(value)


def _apply_assay_override(
    policy: QCPolicyDefinition,
    assay_type: str | None,
) -> tuple[QCPolicyDefinition, str | None]:
    if assay_type is None:
        return policy, None
    normalized_assay_type = _require_normalized_identifier(assay_type, field_name="assay_type")
    for override in policy.assay_overrides:
        if override.assay_type != normalized_assay_type:
            continue
        updated_checks: list[QCMetricExpectation] = []
        overrides_by_check = {item.check_id: item for item in override.check_overrides}
        for check in policy.checks:
            check_override = overrides_by_check.get(check.id)
            if check_override is None:
                updated_checks.append(check)
                continue
            updated_checks.append(
                check.model_copy(
                    update={
                        "pass_threshold": (
                            check_override.pass_threshold
                            if check_override.pass_threshold is not None
                            else check.pass_threshold
                        ),
                        "warn_threshold": (
                            check_override.warn_threshold
                            if check_override.warn_threshold is not None
                            else check.warn_threshold
                        ),
                    }
                )
            )
        return policy.model_copy(update={"checks": updated_checks}), normalized_assay_type
    return policy, None


def summarize_qc_policy_evaluation(evaluation: QCPolicyEvaluation) -> str:
    failing_technical = [
        item for item in evaluation.checks if item.category == "technical" and item.status == "fail"
    ]
    warning_technical = [
        item for item in evaluation.checks if item.category == "technical" and item.status == "warn"
    ]
    batch_failures = [
        item for item in evaluation.checks if item.category == "batch_effect" and item.status == "fail"
    ]
    batch_warnings = [
        item for item in evaluation.checks if item.category == "batch_effect" and item.status == "warn"
    ]
    design_failures = [
        item for item in evaluation.checks if item.category == "experimental_design" and item.status == "fail"
    ]
    design_warnings = [
        item for item in evaluation.checks if item.category == "experimental_design" and item.status == "warn"
    ]

    parts = [f"{evaluation.label} [{evaluation.overall_status}]"]
    if failing_technical:
        parts.append(
            "Technical failures: " + "; ".join(item.message for item in failing_technical)
        )
    if warning_technical:
        parts.append(
            "Technical warnings: " + "; ".join(item.message for item in warning_technical)
        )
    if batch_failures:
        parts.append(
            "Batch-effect failures: " + "; ".join(item.message for item in batch_failures)
        )
    if batch_warnings:
        parts.append(
            "Batch-effect warnings: " + "; ".join(item.message for item in batch_warnings)
        )
    if design_failures:
        parts.append(
            "Experimental-design failures: " + "; ".join(item.message for item in design_failures)
        )
    if design_warnings:
        parts.append(
            "Experimental-design warnings: " + "; ".join(item.message for item in design_warnings)
        )
    if not evaluation.checks:
        parts.append("No QC checks were evaluated.")
    return " ".join(parts)


def evaluate_qc_policy(
    policy: QCPolicyDefinition,
    evidence: QCEvidence | dict[str, Any],
    *,
    assay_type: str | None = None,
    gate_id: str | None = None,
    stage: str | None = None,
) -> QCPolicyEvaluation:
    parsed_evidence = evidence if isinstance(evidence, QCEvidence) else QCEvidence.model_validate(evidence)
    resolved_policy, applied_override = _apply_assay_override(policy, assay_type)
    observed_by_metric = {item.metric_name: item for item in parsed_evidence.metrics}
    checks: list[QCCheckResult] = []

    for tool_name in resolved_policy.required_upstream_tools:
        if tool_name in parsed_evidence.upstream_tools:
            continue
        checks.append(
            QCCheckResult(
                check_id=f"required-tool-{tool_name}",
                label=f"Required upstream tool {tool_name}",
                metric_name=f"required_tool:{tool_name}",
                category="technical",
                status="fail",
                observed_value="missing",
                threshold="required",
                source_artifact=None,
                message=f"Required upstream QC tool {tool_name} was not provided.",
            )
        )

    for expectation in resolved_policy.checks:
        threshold = _format_threshold(expectation)
        observed = observed_by_metric.get(expectation.metric_name)
        if observed is None:
            checks.append(
                QCCheckResult(
                    check_id=expectation.id,
                    label=expectation.label,
                    metric_name=expectation.metric_name,
                    category=expectation.category,
                    status="fail",
                    observed_value=None,
                    threshold=threshold,
                    source_artifact=None,
                    message=f"Expected metric {expectation.metric_name} was not observed.",
                )
            )
            continue

        try:
            numeric_value = _coerce_numeric_metric(observed.observed_value)
        except ValueError as exc:
            checks.append(
                QCCheckResult(
                    check_id=expectation.id,
                    label=expectation.label,
                    metric_name=expectation.metric_name,
                    category=expectation.category,
                    status="fail",
                    observed_value=observed.observed_value,
                    threshold=threshold,
                    source_artifact=observed.source_artifact,
                    message=f"{expectation.metric_name} could not be evaluated: {exc}",
                )
            )
            continue

        if expectation.comparison == "minimum":
            if numeric_value >= expectation.pass_threshold:
                status: QCCheckStatus = "pass"
            elif expectation.warn_threshold is not None and numeric_value >= expectation.warn_threshold:
                status = "warn"
            else:
                status = "fail"
        else:
            if numeric_value <= expectation.pass_threshold:
                status = "pass"
            elif expectation.warn_threshold is not None and numeric_value <= expectation.warn_threshold:
                status = "warn"
            else:
                status = "fail"

        comparator = ">=" if expectation.comparison == "minimum" else "<="
        checks.append(
            QCCheckResult(
                check_id=expectation.id,
                label=expectation.label,
                metric_name=expectation.metric_name,
                category=expectation.category,
                status=status,
                observed_value=observed.observed_value,
                threshold=threshold,
                source_artifact=observed.source_artifact,
                message=(
                    f"{expectation.metric_name}={numeric_value:g} "
                    f"{'met' if status == 'pass' else 'did not meet'} {comparator} {expectation.pass_threshold:g}."
                ),
            )
        )

    overall_status: QCCheckStatus
    if any(item.status == "fail" for item in checks):
        overall_status = "fail"
    elif any(item.status == "warn" for item in checks):
        overall_status = "warn"
    else:
        overall_status = "pass"

    evaluation = QCPolicyEvaluation(
        policy_id=resolved_policy.policy_id,
        label=resolved_policy.label,
        version=resolved_policy.version,
        assay_type=assay_type or resolved_policy.assay_type,
        applied_assay_override=applied_override,
        gate_id=gate_id,
        stage=stage,
        required_upstream_tools=list(resolved_policy.required_upstream_tools),
        missing_upstream_tools=[
            tool_name
            for tool_name in resolved_policy.required_upstream_tools
            if tool_name not in parsed_evidence.upstream_tools
        ],
        overall_status=overall_status,
        checks=checks,
        summary="pending",
    )
    evaluation.summary = summarize_qc_policy_evaluation(evaluation)
    return evaluation


__all__ = [
    "QCAssayOverride",
    "QCCheckCategory",
    "QCCheckResult",
    "QCCheckStatus",
    "QCEvidence",
    "QCMetricExpectation",
    "QCMetricExpectationOverride",
    "QCObservedMetric",
    "QCPolicyDefinition",
    "QCPolicyEvaluation",
    "QCSourceArtifact",
    "evaluate_qc_policy",
    "normalize_qc_identifier",
    "summarize_qc_policy_evaluation",
]
