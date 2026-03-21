"""Structured observability storage and reporting helpers."""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

OBSERVABILITY_METRIC_CONTRACT_VERSION = "observability_metric.v1"
OBSERVABILITY_TRACE_CONTRACT_VERSION = "observability_trace.v1"
OBSERVABILITY_LOG_DIR = Path("storage") / "observability"
OBSERVABILITY_METRIC_DIR = OBSERVABILITY_LOG_DIR / "metrics"
OBSERVABILITY_TRACE_DIR = OBSERVABILITY_LOG_DIR / "traces"
OBSERVABILITY_LOG_PREFIX = "events"
OBSERVABILITY_RETENTION_EXPECTATION_DAYS = 30
OBSERVABILITY_ROTATION_STRATEGY = "daily_jsonl"
_MAX_STRING_CHARS = 500
_MAX_ATTRIBUTES_JSON_CHARS = 12_000

logger = logging.getLogger(__name__)

MetricKind = Literal["duration", "rate", "count", "gauge"]
TraceStatus = Literal["ok", "error", "blocked"]


class ObservabilityMetricRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["observability_metric.v1"] = OBSERVABILITY_METRIC_CONTRACT_VERSION
    record_id: str
    recorded_at: datetime
    metric_name: str
    metric_kind: MetricKind
    value: float
    unit: str
    request_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    job_id: str | None = None
    workflow_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("recorded_at")
    @classmethod
    def _normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0)

    @field_validator("metric_name", "unit")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            raise ValueError("Text fields must not be empty.")
        return cleaned

    @field_validator(
        "request_id",
        "session_id",
        "run_id",
        "step_id",
        "job_id",
        "workflow_id",
        "trace_id",
        "span_id",
    )
    @classmethod
    def _validate_optional_text_fields(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Observability metric values must be finite.")
        return float(value)


class ObservabilityTraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["observability_trace.v1"] = OBSERVABILITY_TRACE_CONTRACT_VERSION
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    span_name: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    status: TraceStatus
    request_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    job_id: str | None = None
    workflow_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("trace_id", "span_id", "span_name")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            raise ValueError("Text fields must not be empty.")
        return cleaned

    @field_validator("parent_span_id", "request_id", "session_id", "run_id", "step_id", "job_id", "workflow_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("started_at", "ended_at")
    @classmethod
    def _normalize_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0)

    @field_validator("duration_seconds")
    @classmethod
    def _validate_duration_seconds(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("duration_seconds must be a finite non-negative number.")
        return float(value)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _clean_optional_text(value: str | None, *, max_chars: int = _MAX_STRING_CHARS) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned[:max_chars]


def _normalize_jsonlike(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return _clean_optional_text(str(value))
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, str):
            return _clean_optional_text(value, max_chars=_MAX_STRING_CHARS) or ""
        return value
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_jsonlike(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [_normalize_jsonlike(item, depth=depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _normalize_jsonlike(value.model_dump(mode="json"), depth=depth + 1)
        except Exception:
            return _clean_optional_text(str(value))
    return _clean_optional_text(str(value))


def _normalize_attributes(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = {
        str(key): _normalize_jsonlike(value)
        for key, value in (attributes or {}).items()
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(encoded) <= _MAX_ATTRIBUTES_JSON_CHARS:
        return payload
    return {"truncated": True, "sha256_preview": encoded[:256]}


def _daily_log_path(
    base_dir: Path | str,
    *,
    recorded_at: datetime,
    category_dir: Path,
) -> Path:
    base_path = Path(base_dir).resolve()
    timestamp = recorded_at if recorded_at.tzinfo is not None else recorded_at.replace(tzinfo=timezone.utc)
    date_key = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return base_path / category_dir / f"{OBSERVABILITY_LOG_PREFIX}-{date_key}.jsonl"


def observability_retention_policy() -> dict[str, Any]:
    return {
        "rotation_strategy": OBSERVABILITY_ROTATION_STRATEGY,
        "retention_expectation_days": OBSERVABILITY_RETENTION_EXPECTATION_DAYS,
        "automatic_deletion": False,
    }


def chat_span_id(request_id: str) -> str:
    return f"chat-turn:{request_id}"


def workflow_trace_id(*, run_id: str, request_id: str | None = None) -> str:
    return request_id or run_id


def workflow_span_id(run_id: str) -> str:
    return f"workflow-run:{run_id}"


def workflow_step_span_id(run_id: str, step_id: str) -> str:
    return f"workflow-step:{run_id}:{step_id}"


def append_metric_record(
    base_dir: Path | str,
    *,
    metric_name: str,
    metric_kind: MetricKind,
    value: float,
    unit: str,
    request_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    job_id: str | None = None,
    workflow_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    recorded_at: datetime | None = None,
) -> Path | None:
    timestamp = recorded_at or _utcnow()
    try:
        record = ObservabilityMetricRecord(
            record_id=str(uuid.uuid4()),
            recorded_at=timestamp,
            metric_name=metric_name,
            metric_kind=metric_kind,
            value=value,
            unit=unit,
            request_id=request_id,
            session_id=session_id,
            run_id=run_id,
            step_id=step_id,
            job_id=job_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            span_id=span_id,
            attributes=_normalize_attributes(attributes),
        )
        path = _daily_log_path(base_dir, recorded_at=record.recorded_at, category_dir=OBSERVABILITY_METRIC_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
    except Exception:
        logger.warning(
            "Non-fatal observability metric append failure for metric_name=%s request_id=%s run_id=%s step_id=%s",
            metric_name,
            _clean_optional_text(request_id),
            _clean_optional_text(run_id),
            _clean_optional_text(step_id),
            exc_info=True,
        )
        return None
    return path


def append_trace_record(
    base_dir: Path | str,
    *,
    trace_id: str,
    span_id: str,
    span_name: str,
    started_at: datetime,
    ended_at: datetime,
    status: TraceStatus,
    parent_span_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    job_id: str | None = None,
    workflow_id: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    duration_seconds: float | None = None,
) -> Path | None:
    try:
        record = ObservabilityTraceRecord(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            span_name=span_name,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=(
                max(0.0, float(duration_seconds))
                if duration_seconds is not None
                else max(
                    0.0,
                    (
                        (ended_at if ended_at.tzinfo is not None else ended_at.replace(tzinfo=timezone.utc))
                        - (started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=timezone.utc))
                    ).total_seconds(),
                )
            ),
            status=status,
            request_id=request_id,
            session_id=session_id,
            run_id=run_id,
            step_id=step_id,
            job_id=job_id,
            workflow_id=workflow_id,
            attributes=_normalize_attributes(attributes),
        )
        path = _daily_log_path(base_dir, recorded_at=record.ended_at, category_dir=OBSERVABILITY_TRACE_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
    except Exception:
        logger.warning(
            "Non-fatal observability trace append failure for span_name=%s trace_id=%s span_id=%s",
            span_name,
            _clean_optional_text(trace_id),
            _clean_optional_text(span_id),
            exc_info=True,
        )
        return None
    return path


def _matches_filters(record: Any, filters: Mapping[str, Any]) -> bool:
    for key, expected in filters.items():
        if expected is None:
            continue
        if getattr(record, key) != expected:
            return False
    return True


def _iter_record_lines(base_dir: Path | str, *, category_dir: Path) -> list[tuple[Path, str]]:
    base_path = Path(base_dir).resolve()
    target_dir = base_path / category_dir
    if not target_dir.exists():
        return []
    lines: list[tuple[Path, str]] = []
    for path in sorted(target_dir.glob(f"{OBSERVABILITY_LOG_PREFIX}-*.jsonl"), reverse=True):
        try:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                lines.append((path, line))
        except Exception:
            logger.warning("Skipping unreadable observability log %s", path, exc_info=True)
    return lines


def query_metric_records(
    base_dir: Path | str,
    *,
    metric_name: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    job_id: str | None = None,
    workflow_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[ObservabilityMetricRecord]:
    if limit < 1:
        raise ValueError("limit must be at least 1.")
    normalized_filters = {
        "metric_name": _clean_optional_text(metric_name),
        "request_id": _clean_optional_text(request_id),
        "session_id": _clean_optional_text(session_id),
        "run_id": _clean_optional_text(run_id),
        "step_id": _clean_optional_text(step_id),
        "job_id": _clean_optional_text(job_id),
        "workflow_id": _clean_optional_text(workflow_id),
        "trace_id": _clean_optional_text(trace_id),
        "span_id": _clean_optional_text(span_id),
    }
    since_utc = None
    if since is not None:
        since_utc = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
        since_utc = since_utc.astimezone(timezone.utc).replace(microsecond=0)

    records: list[ObservabilityMetricRecord] = []
    for _, line in _iter_record_lines(base_dir, category_dir=OBSERVABILITY_METRIC_DIR):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = ObservabilityMetricRecord.model_validate_json(stripped)
        except Exception:
            continue
        if since_utc is not None and record.recorded_at < since_utc:
            continue
        if not _matches_filters(record, normalized_filters):
            continue
        records.append(record)
        if len(records) >= limit:
            return records
    return records


def query_trace_records(
    base_dir: Path | str,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    span_name: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    job_id: str | None = None,
    workflow_id: str | None = None,
    status: TraceStatus | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[ObservabilityTraceRecord]:
    if limit < 1:
        raise ValueError("limit must be at least 1.")
    normalized_filters = {
        "trace_id": _clean_optional_text(trace_id),
        "span_id": _clean_optional_text(span_id),
        "parent_span_id": _clean_optional_text(parent_span_id),
        "span_name": _clean_optional_text(span_name),
        "request_id": _clean_optional_text(request_id),
        "session_id": _clean_optional_text(session_id),
        "run_id": _clean_optional_text(run_id),
        "step_id": _clean_optional_text(step_id),
        "job_id": _clean_optional_text(job_id),
        "workflow_id": _clean_optional_text(workflow_id),
        "status": status,
    }
    since_utc = None
    if since is not None:
        since_utc = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
        since_utc = since_utc.astimezone(timezone.utc).replace(microsecond=0)

    records: list[ObservabilityTraceRecord] = []
    for _, line in _iter_record_lines(base_dir, category_dir=OBSERVABILITY_TRACE_DIR):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = ObservabilityTraceRecord.model_validate_json(stripped)
        except Exception:
            continue
        if since_utc is not None and record.ended_at < since_utc:
            continue
        if not _matches_filters(record, normalized_filters):
            continue
        records.append(record)
        if len(records) >= limit:
            return records
    return records


OBSERVABILITY_DASHBOARD_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "chat_responsiveness",
        "title": "Chat Responsiveness",
        "description": (
            "Track time-to-first-visible-response separately from full backend completion so "
            "perceived latency and total execution can be monitored independently."
        ),
        "panels": [
            {
                "title": "User-Visible Latency",
                "metric_name": "chat_latency_seconds",
                "filters": {"latency_scope": "user_visible"},
                "aggregation": "p50_p95_avg",
            },
            {
                "title": "Backend Execution Latency",
                "metric_name": "chat_latency_seconds",
                "filters": {"latency_scope": "backend_execution"},
                "aggregation": "p50_p95_avg",
            },
        ],
    },
    {
        "id": "workflow_delivery",
        "title": "Workflow Delivery",
        "description": "Monitor end-to-end workflow duration plus terminal failure and block rates.",
        "panels": [
            {"title": "Workflow Duration", "metric_name": "workflow_duration_seconds", "aggregation": "p50_p95_avg"},
            {"title": "Failure Rate", "metric_name": "failure_rate", "aggregation": "avg"},
            {"title": "Block Rate", "metric_name": "block_rate", "aggregation": "avg"},
            {"title": "Step Duration", "metric_name": "step_duration_seconds", "aggregation": "p50_p95_avg"},
        ],
    },
    {
        "id": "workflow_quality",
        "title": "Workflow Quality Signals",
        "description": "Surface QC pass rate and evidence coverage for workflows that declare literature grounding.",
        "panels": [
            {"title": "QC Pass Rate", "metric_name": "qc_pass_rate", "aggregation": "avg"},
            {"title": "Evidence Coverage Rate", "metric_name": "evidence_coverage_rate", "aggregation": "avg"},
        ],
    },
]


def dashboard_definitions() -> list[dict[str, Any]]:
    return json.loads(json.dumps(OBSERVABILITY_DASHBOARD_DEFINITIONS))


def _percentile(sorted_values: list[float], quantile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    fraction = position - lower
    return lower_value + (upper_value - lower_value) * fraction


def _duration_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "average": None, "p50": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "average": sum(ordered) / len(ordered),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _rate_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "average": None}
    return {"count": len(values), "average": sum(values) / len(values)}


def build_observability_overview(
    base_dir: Path | str,
    *,
    days: int = 7,
    workflow_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    if days < 1:
        raise ValueError("days must be at least 1.")
    since = _utcnow() - timedelta(days=days)
    metric_records = query_metric_records(
        base_dir,
        workflow_id=workflow_id,
        session_id=session_id,
        request_id=request_id,
        since=since,
        limit=limit,
    )
    trace_records = query_trace_records(
        base_dir,
        workflow_id=workflow_id,
        session_id=session_id,
        request_id=request_id,
        since=since,
        limit=limit,
    )

    def _metric_values(metric_name: str, **attribute_filters: Any) -> list[float]:
        selected: list[float] = []
        for record in metric_records:
            if record.metric_name != metric_name:
                continue
            if any(record.attributes.get(key) != value for key, value in attribute_filters.items()):
                continue
            selected.append(record.value)
        return selected

    return {
        "generated_at": _utcnow().isoformat().replace("+00:00", "Z"),
        "window_days": days,
        "filters": {
            "workflow_id": _clean_optional_text(workflow_id),
            "session_id": _clean_optional_text(session_id),
            "request_id": _clean_optional_text(request_id),
        },
        "record_counts": {
            "metric_records": len(metric_records),
            "trace_records": len(trace_records),
        },
        "chat_responsiveness": {
            "user_visible_latency_seconds": _duration_summary(
                _metric_values("chat_latency_seconds", latency_scope="user_visible")
            ),
            "backend_execution_latency_seconds": _duration_summary(
                _metric_values("chat_latency_seconds", latency_scope="backend_execution")
            ),
        },
        "workflow_delivery": {
            "workflow_duration_seconds": _duration_summary(_metric_values("workflow_duration_seconds")),
            "step_duration_seconds": _duration_summary(_metric_values("step_duration_seconds")),
            "failure_rate": _rate_summary(_metric_values("failure_rate")),
            "block_rate": _rate_summary(_metric_values("block_rate")),
        },
        "workflow_quality": {
            "qc_pass_rate": _rate_summary(_metric_values("qc_pass_rate")),
            "evidence_coverage_rate": _rate_summary(_metric_values("evidence_coverage_rate")),
        },
        "dashboards": dashboard_definitions(),
        "retention_policy": observability_retention_policy(),
    }


__all__ = [
    "OBSERVABILITY_METRIC_CONTRACT_VERSION",
    "OBSERVABILITY_TRACE_CONTRACT_VERSION",
    "ObservabilityMetricRecord",
    "ObservabilityTraceRecord",
    "append_metric_record",
    "append_trace_record",
    "build_observability_overview",
    "chat_span_id",
    "dashboard_definitions",
    "observability_retention_policy",
    "query_metric_records",
    "query_trace_records",
    "workflow_span_id",
    "workflow_step_span_id",
    "workflow_trace_id",
]
