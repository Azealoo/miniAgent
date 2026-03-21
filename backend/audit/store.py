"""Shared append-only audit log helpers for operational events."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

AUDIT_EVENT_CONTRACT_VERSION = "audit_event.v1"
AUDIT_LOG_DIR = Path("storage") / "audit"
AUDIT_LOG_PREFIX = "events"
AUDIT_RETENTION_EXPECTATION_DAYS = 90
AUDIT_ROTATION_STRATEGY = "daily_jsonl"
AUDIT_REDACTION_POLICY = "audit_redaction.v1"
_MAX_SUMMARY_CHARS = 240
_MAX_STRING_CHARS = 500
_MAX_DETAILS_JSON_CHARS = 12_000

logger = logging.getLogger(__name__)

AuditEventType = Literal[
    "chat_request_received",
    "compliance_decision",
    "workflow_started",
    "workflow_finished",
    "tool_invoked",
    "file_written",
    "job_submitted",
    "export_generated",
]


class AuditEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = AUDIT_EVENT_CONTRACT_VERSION
    event_id: str
    event_type: AuditEventType
    recorded_at: datetime
    summary: str
    outcome: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    job_id: str | None = None
    workflow_id: str | None = None
    tool_name: str | None = None
    actor: str = "system"
    artifact_paths: list[str] = Field(default_factory=list)
    external_systems: list[str] = Field(default_factory=list)
    redaction_policy: str = AUDIT_REDACTION_POLICY
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("recorded_at")
    @classmethod
    def _normalize_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0)

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        cleaned = _clean_optional_text(value, max_chars=_MAX_SUMMARY_CHARS)
        if cleaned is None:
            raise ValueError("summary must not be empty.")
        return cleaned


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_summary(
    *,
    message: str,
    attached_identifiers: list[str],
    selected_workflow: str | None,
) -> dict[str, Any]:
    normalized_attachments = [item.strip() for item in attached_identifiers if item.strip()]
    return {
        "message_sha256": hash_text(message.strip()),
        "message_chars": len(message),
        "attached_identifier_count": len(normalized_attachments),
        "attached_identifier_sha256": [hash_text(item) for item in normalized_attachments],
        "selected_workflow": _clean_optional_text(selected_workflow),
    }


def append_audit_event(
    base_dir: Path | str,
    *,
    event_type: AuditEventType,
    summary: str,
    outcome: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    job_id: str | None = None,
    workflow_id: str | None = None,
    tool_name: str | None = None,
    actor: str = "system",
    artifact_paths: list[str] | None = None,
    external_systems: list[str] | None = None,
    details: Mapping[str, Any] | None = None,
    recorded_at: datetime | None = None,
) -> Path | None:
    base_path = Path(base_dir).resolve()
    try:
        record = AuditEventRecord(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            recorded_at=recorded_at or _utcnow(),
            summary=summary,
            outcome=_clean_optional_text(outcome),
            session_id=_clean_optional_text(session_id),
            run_id=_clean_optional_text(run_id),
            step_id=_clean_optional_text(step_id),
            job_id=_clean_optional_text(job_id),
            workflow_id=_clean_optional_text(workflow_id),
            tool_name=_clean_optional_text(tool_name),
            actor=_clean_optional_text(actor) or "system",
            artifact_paths=_normalize_path_list(base_path, artifact_paths or []),
            external_systems=_normalize_string_list(external_systems or []),
            details=_normalize_details(details or {}),
        )
        log_path = audit_log_path(base_path, recorded_at=record.recorded_at)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
    except Exception:
        logger.warning(
            "Non-fatal audit append failure for event_type=%s outcome=%s session_id=%s run_id=%s "
            "step_id=%s job_id=%s workflow_id=%s tool_name=%s",
            event_type,
            _clean_optional_text(outcome),
            _clean_optional_text(session_id),
            _clean_optional_text(run_id),
            _clean_optional_text(step_id),
            _clean_optional_text(job_id),
            _clean_optional_text(workflow_id),
            _clean_optional_text(tool_name),
            exc_info=True,
        )
        return None
    return log_path


def audit_log_path(base_dir: Path | str, *, recorded_at: datetime | None = None) -> Path:
    base_path = Path(base_dir).resolve()
    timestamp = recorded_at or _utcnow()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    date_key = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return base_path / AUDIT_LOG_DIR / f"{AUDIT_LOG_PREFIX}-{date_key}.jsonl"


def audit_retention_policy() -> dict[str, Any]:
    return {
        "rotation_strategy": AUDIT_ROTATION_STRATEGY,
        "retention_expectation_days": AUDIT_RETENTION_EXPECTATION_DAYS,
        "automatic_deletion": False,
    }


def query_audit_events(
    base_dir: Path | str,
    *,
    event_type: AuditEventType | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    job_id: str | None = None,
    workflow_id: str | None = None,
    tool_name: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
) -> list[AuditEventRecord]:
    base_path = Path(base_dir).resolve()
    if limit < 1:
        raise ValueError("limit must be at least 1.")

    audit_dir = base_path / AUDIT_LOG_DIR
    if not audit_dir.exists():
        return []

    normalized_filters = {
        "event_type": event_type,
        "session_id": _clean_optional_text(session_id),
        "run_id": _clean_optional_text(run_id),
        "step_id": _clean_optional_text(step_id),
        "job_id": _clean_optional_text(job_id),
        "workflow_id": _clean_optional_text(workflow_id),
        "tool_name": _clean_optional_text(tool_name),
        "outcome": _clean_optional_text(outcome),
    }

    events: list[AuditEventRecord] = []
    for path in sorted(audit_dir.glob(f"{AUDIT_LOG_PREFIX}-*.jsonl"), reverse=True):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            logger.warning("Skipping unreadable audit log %s", path, exc_info=True)
            continue
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = AuditEventRecord.model_validate_json(stripped)
            except Exception:
                continue
            if not _matches_filters(record, normalized_filters):
                continue
            events.append(record)
            if len(events) >= limit:
                return events
    return events


def append_chat_request_event(
    base_dir: Path | str,
    *,
    session_id: str,
    message: str,
    attached_identifiers: list[str],
    selected_workflow: str | None,
) -> Path:
    return append_audit_event(
        base_dir,
        event_type="chat_request_received",
        summary=f"Received chat request for session {session_id}.",
        outcome="received",
        session_id=session_id,
        workflow_id=selected_workflow,
        details={
            "request_summary": request_summary(
                message=message,
                attached_identifiers=attached_identifiers,
                selected_workflow=selected_workflow,
            )
        },
    )


def append_tool_invocation_event(
    base_dir: Path | str,
    *,
    session_id: str | None,
    workflow_id: str | None,
    tool_name: str,
    tool_run_id: str | None,
    tool_input: str | None,
    result: Mapping[str, Any] | None,
) -> Path:
    result_payload = dict(result or {})
    artifact_paths = _tool_artifact_paths(base_dir, result_payload)
    warnings = [str(item) for item in result_payload.get("warnings", []) if str(item).strip()]
    error_payload = result_payload.get("error")
    error_code = error_payload.get("code") if isinstance(error_payload, Mapping) else None
    metadata = result_payload.get("metadata")
    normalized_metadata = metadata if isinstance(metadata, Mapping) else {}
    resolved_outcome = _clean_optional_text(
        result_payload.get("outcome") or result_payload.get("status") or "completed"
    )

    return append_audit_event(
        base_dir,
        event_type="tool_invoked",
        summary=f"Tool {tool_name} completed with outcome {resolved_outcome or 'completed'}.",
        outcome=resolved_outcome,
        session_id=session_id,
        workflow_id=workflow_id,
        tool_name=tool_name,
        artifact_paths=artifact_paths,
        external_systems=_external_systems_for_tool(tool_name),
        details={
            "tool_run_id": _clean_optional_text(tool_run_id),
            "input_sha256": hash_text(tool_input) if tool_input else None,
            "input_chars": len(tool_input) if tool_input else 0,
            "status": result_payload.get("status"),
            "warning_count": len(warnings),
            "warnings": warnings,
            "error_code": error_code,
            "artifact_count": len(artifact_paths),
            "metadata": normalized_metadata,
        },
    )


def append_workflow_started_event(
    base_dir: Path | str,
    *,
    run_id: str,
    workflow_id: str,
    workflow_name: str,
    run_record_path: str,
    lifecycle_status: str,
    resumed: bool,
    session_id: str | None = None,
) -> Path:
    return append_audit_event(
        base_dir,
        event_type="workflow_started",
        summary=f"Workflow {workflow_id} started.",
        outcome="started",
        session_id=session_id,
        run_id=run_id,
        workflow_id=workflow_id,
        artifact_paths=[run_record_path],
        details={
            "workflow_name": workflow_name,
            "run_record_path": run_record_path,
            "lifecycle_status": lifecycle_status,
            "resumed": resumed,
        },
    )


def append_workflow_finished_event(
    base_dir: Path | str,
    *,
    run_id: str,
    workflow_id: str,
    workflow_name: str,
    run_record_path: str,
    lifecycle_status: str,
    completed_steps: int,
    total_steps: int,
    warning_count: int,
    output_artifact_paths: list[str] | None = None,
    provenance_exports: list[str] | None = None,
    biocompute_exports: list[str] | None = None,
    session_id: str | None = None,
) -> Path:
    artifact_paths = [
        run_record_path,
        *(output_artifact_paths or []),
        *(provenance_exports or []),
        *(biocompute_exports or []),
    ]
    return append_audit_event(
        base_dir,
        event_type="workflow_finished",
        summary=f"Workflow {workflow_id} finished with status {lifecycle_status}.",
        outcome=lifecycle_status,
        session_id=session_id,
        run_id=run_id,
        workflow_id=workflow_id,
        artifact_paths=artifact_paths,
        details={
            "workflow_name": workflow_name,
            "run_record_path": run_record_path,
            "completed_steps": completed_steps,
            "total_steps": total_steps,
            "warning_count": warning_count,
            "output_artifact_paths": output_artifact_paths or [],
            "provenance_exports": provenance_exports or [],
            "biocompute_exports": biocompute_exports or [],
        },
    )


def append_file_written_event(
    base_dir: Path | str,
    *,
    path: str,
    source: str,
    outcome: str,
    byte_count: int | None = None,
    session_id: str | None = None,
    tool_name: str | None = None,
    reason: str | None = None,
) -> Path:
    cleaned_path = _clean_optional_text(path) or path
    summary = (
        f"Wrote file {cleaned_path}."
        if outcome == "written"
        else f"File write for {cleaned_path} ended with outcome {outcome}."
    )
    return append_audit_event(
        base_dir,
        event_type="file_written",
        summary=summary,
        outcome=outcome,
        session_id=session_id,
        tool_name=tool_name,
        artifact_paths=[cleaned_path],
        details={
            "path": cleaned_path,
            "source": source,
            "byte_count": byte_count,
            "reason": _clean_optional_text(reason),
        },
    )


def append_job_submitted_event(
    base_dir: Path | str,
    *,
    session_id: str | None = None,
    run_id: str,
    job_id: str,
    script_path: str,
    working_directory: str | None,
    resource_request: Mapping[str, Any] | None,
    stdout_path: str | None,
    stderr_path: str | None,
    workflow_id: str | None = None,
    step_id: str | None = None,
    tool_name: str | None = None,
) -> Path:
    return append_audit_event(
        base_dir,
        event_type="job_submitted",
        summary=f"Submitted Slurm job {job_id}.",
        outcome="submitted",
        session_id=session_id,
        run_id=run_id,
        step_id=step_id,
        job_id=job_id,
        workflow_id=workflow_id,
        tool_name=tool_name,
        artifact_paths=[script_path, stdout_path or "", stderr_path or ""],
        external_systems=["slurm"],
        details={
            "script_path": script_path,
            "working_directory": working_directory,
            "resource_request": resource_request or {},
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
        },
    )


def append_export_generated_event(
    base_dir: Path | str,
    *,
    export_type: str,
    session_id: str | None = None,
    run_id: str,
    workflow_id: str | None,
    artifact_paths: list[str],
    lifecycle_status: str,
) -> Path:
    return append_audit_event(
        base_dir,
        event_type="export_generated",
        summary=f"Generated {export_type} export for run {run_id}.",
        outcome="generated",
        session_id=session_id,
        run_id=run_id,
        workflow_id=workflow_id,
        artifact_paths=artifact_paths,
        details={
            "export_type": export_type,
            "artifact_count": len([path for path in artifact_paths if path]),
            "lifecycle_status": lifecycle_status,
        },
    )


def _matches_filters(record: AuditEventRecord, filters: dict[str, str | None]) -> bool:
    for field_name, expected in filters.items():
        if expected is None:
            continue
        if getattr(record, field_name) != expected:
            return False
    return True


def _normalize_details(details: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        str(key): _normalize_jsonlike(value)
        for key, value in details.items()
        if value is not None
    }
    rendered = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    if len(rendered) <= _MAX_DETAILS_JSON_CHARS:
        return normalized
    return {
        "truncated": True,
        "preview": _truncate_text(rendered, max_chars=_MAX_DETAILS_JSON_CHARS),
    }


def _normalize_jsonlike(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return _truncate_text(str(value))
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _normalize_jsonlike(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_jsonlike(item, depth=depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _normalize_jsonlike(value.model_dump(mode="json"), depth=depth + 1)
        except Exception:
            return _truncate_text(str(value))
    return _truncate_text(str(value))


def _tool_artifact_paths(base_dir: Path | str, result: Mapping[str, Any]) -> list[str]:
    refs = result.get("artifact_refs")
    if not isinstance(refs, list):
        return []
    base_path = Path(base_dir).resolve()
    paths: list[str] = []
    for item in refs:
        if not isinstance(item, Mapping):
            continue
        raw_path = item.get("path")
        cleaned = _normalize_path(base_path, raw_path)
        if cleaned:
            paths.append(cleaned)
    return paths


def _external_systems_for_tool(tool_name: str) -> list[str]:
    mapping = {
        "slurm_tool": ["slurm"],
        "ncbi_eutils": ["ncbi_eutils"],
        "uniprot_api": ["uniprot_api"],
        "ensembl_api": ["ensembl_api"],
        "fetch_url": ["http"],
        "http_json": ["http"],
    }
    return list(mapping.get(tool_name, []))


def _normalize_path_list(base_dir: Path, values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        cleaned = _normalize_path(base_dir, value)
        if cleaned:
            normalized.append(cleaned)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in normalized:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _normalize_path(base_dir: Path, value: Any) -> str | None:
    raw = _clean_optional_text(value)
    if raw is None:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()
    return raw


def _normalize_string_list(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        normalized = _clean_optional_text(value)
        if normalized is not None:
            cleaned.append(normalized)
    return cleaned


def _clean_optional_text(value: Any, *, max_chars: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if max_chars is None:
        return cleaned
    return _truncate_text(cleaned, max_chars=max_chars)


def _truncate_text(value: str, *, max_chars: int = _MAX_STRING_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 16].rstrip() + "...[truncated]"


__all__ = [
    "AUDIT_EVENT_CONTRACT_VERSION",
    "AUDIT_LOG_DIR",
    "AUDIT_REDACTION_POLICY",
    "AUDIT_RETENTION_EXPECTATION_DAYS",
    "AUDIT_ROTATION_STRATEGY",
    "AuditEventRecord",
    "AuditEventType",
    "append_audit_event",
    "append_chat_request_event",
    "append_export_generated_event",
    "append_file_written_event",
    "append_job_submitted_event",
    "append_tool_invocation_event",
    "append_workflow_finished_event",
    "append_workflow_started_event",
    "audit_log_path",
    "audit_retention_policy",
    "hash_text",
    "query_audit_events",
    "request_summary",
]
