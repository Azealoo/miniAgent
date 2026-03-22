"""Session-derived workflow workspace summaries for the Flows browser."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal, Mapping

from graph.session_manager import SessionManager

WorkflowWorkspaceStatus = Literal["active", "idle", "blocked", "failed"]

_TOOL_CONCEPTS = {"compliance_preflight", "evidence_review"}
_ERROR_OUTCOMES = {
    "execution_failure",
    "invalid_input",
    "retriable_failure",
}


@dataclass(frozen=True)
class WorkflowWorkspaceSummary:
    id: str
    run_count: int
    last_activity_at: float | None
    status: WorkflowWorkspaceStatus


@dataclass
class _ObservedRun:
    concept_id: str
    run_key: str
    last_activity_at: float | None
    status: WorkflowWorkspaceStatus
    tie_breaker: tuple[int, int]


def list_workflow_workspace_summaries(
    session_manager: SessionManager,
) -> list[dict[str, Any]]:
    workflow_runs: dict[tuple[str, str], _ObservedRun] = {}
    tool_runs: dict[tuple[str, str], _ObservedRun] = {}

    for session_meta in session_manager.list_sessions():
        session_id = _clean_text(session_meta.get("id"))
        if session_id is None:
            continue

        session_updated_at = _coerce_timestamp(session_meta.get("updated_at"))
        messages = session_manager.load_session(session_id)
        _collect_workflow_runs(
            workflow_runs,
            session_updated_at=session_updated_at,
            messages=messages,
        )
        _collect_tool_runs(
            tool_runs,
            session_id=session_id,
            session_updated_at=session_updated_at,
            messages=messages,
        )

    aggregated: dict[str, WorkflowWorkspaceSummary] = {}
    for observed in [*workflow_runs.values(), *tool_runs.values()]:
        existing = aggregated.get(observed.concept_id)
        if existing is None:
            aggregated[observed.concept_id] = WorkflowWorkspaceSummary(
                id=observed.concept_id,
                run_count=1,
                last_activity_at=observed.last_activity_at,
                status=observed.status,
            )
            continue

        latest_activity = _pick_newer_timestamp(
            existing.last_activity_at,
            observed.last_activity_at,
        )
        latest_status = (
            observed.status
            if latest_activity == observed.last_activity_at
            else existing.status
        )
        aggregated[observed.concept_id] = WorkflowWorkspaceSummary(
            id=existing.id,
            run_count=existing.run_count + 1,
            last_activity_at=latest_activity,
            status=latest_status,
        )

    ordered = sorted(
        aggregated.values(),
        key=lambda item: (
            item.last_activity_at is not None,
            item.last_activity_at or 0.0,
            item.id,
        ),
        reverse=True,
    )
    return [asdict(item) for item in ordered]


def _collect_workflow_runs(
    workflow_runs: dict[tuple[str, str], _ObservedRun],
    *,
    session_updated_at: float | None,
    messages: list[dict[str, Any]],
) -> None:
    for message_index, message in enumerate(messages):
        workflow_events = message.get("workflow_events")
        if not isinstance(workflow_events, list):
            continue

        for event_index, event in enumerate(workflow_events):
            if not isinstance(event, Mapping):
                continue

            workflow_id = _clean_text(event.get("workflow_id"))
            run_id = _clean_text(event.get("run_id"))
            if workflow_id is None or run_id is None:
                continue

            key = (workflow_id, run_id)
            previous = workflow_runs.get(key)
            event_status = _workflow_event_status(event)
            event_timestamp = _event_timestamp(event)
            last_activity_at = (
                _pick_newer_timestamp(previous.last_activity_at, event_timestamp)
                if previous is not None
                else event_timestamp
            )
            if last_activity_at is None and event_status is not None:
                last_activity_at = session_updated_at

            observed = _ObservedRun(
                concept_id=workflow_id,
                run_key=run_id,
                last_activity_at=last_activity_at,
                status=event_status or (previous.status if previous is not None else "idle"),
                tie_breaker=(message_index, event_index),
            )
            _upsert_observed_run(
                workflow_runs,
                key=key,
                observed=observed,
            )


def _collect_tool_runs(
    tool_runs: dict[tuple[str, str], _ObservedRun],
    *,
    session_id: str,
    session_updated_at: float | None,
    messages: list[dict[str, Any]],
) -> None:
    for message_index, message in enumerate(messages):
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue

        for call_index, call in enumerate(tool_calls):
            if not isinstance(call, Mapping):
                continue

            tool_name = _tool_name(call)
            if tool_name is None or tool_name not in _TOOL_CONCEPTS:
                continue

            run_key = _tool_run_key(
                session_id=session_id,
                message_index=message_index,
                call_index=call_index,
                tool_name=tool_name,
                call=call,
            )
            observed = _ObservedRun(
                concept_id=tool_name,
                run_key=run_key,
                last_activity_at=_tool_timestamp(call) or session_updated_at,
                status=_tool_status(tool_name, call),
                tie_breaker=(message_index, call_index),
            )
            _upsert_observed_run(
                tool_runs,
                key=(tool_name, run_key),
                observed=observed,
            )


def _upsert_observed_run(
    runs: dict[tuple[str, str], _ObservedRun],
    *,
    key: tuple[str, str],
    observed: _ObservedRun,
) -> None:
    previous = runs.get(key)
    if previous is None:
        runs[key] = observed
        return

    previous_timestamp = previous.last_activity_at or 0.0
    observed_timestamp = observed.last_activity_at or 0.0
    if observed_timestamp > previous_timestamp:
        runs[key] = observed
        return

    if observed_timestamp < previous_timestamp:
        return

    if observed.tie_breaker >= previous.tie_breaker:
        runs[key] = observed


def _workflow_event_status(
    event: Mapping[str, Any],
) -> WorkflowWorkspaceStatus | None:
    event_type = _clean_text(event.get("type"))
    if event_type == "workflow_blocked":
        return "blocked"

    if event_type in {"workflow_start", "workflow_step_start"}:
        return "active"

    if event_type == "workflow_artifact":
        return None

    if event_type == "workflow_step_end":
        step_status = _clean_text(event.get("status"))
        if step_status == "failed":
            return "failed"
        if step_status == "blocked":
            return "blocked"
        return "active"

    lifecycle_status = _clean_text(event.get("lifecycle_status"))
    return _workflow_lifecycle_status(lifecycle_status)


def _workflow_lifecycle_status(
    lifecycle_status: str | None,
) -> WorkflowWorkspaceStatus:
    if lifecycle_status in {"created", "preflight_checked", "running", "waiting"}:
        return "active"
    if lifecycle_status == "blocked":
        return "blocked"
    if lifecycle_status == "failed":
        return "failed"
    return "idle"


def _tool_name(call: Mapping[str, Any]) -> str | None:
    result = call.get("result")
    if isinstance(result, Mapping):
        result_tool_name = _clean_text(result.get("tool_name"))
        if result_tool_name:
            return result_tool_name

    return _clean_text(call.get("tool"))


def _tool_status(
    tool_name: str,
    call: Mapping[str, Any],
) -> WorkflowWorkspaceStatus:
    result = call.get("result")
    if not isinstance(result, Mapping):
        return "failed"

    if tool_name == "compliance_preflight":
        report = _tool_report(result)
        final_disposition = _clean_text(report.get("final_disposition"))
        runtime_state = _clean_text(report.get("runtime_state"))
        if final_disposition in {"block", "require_approval"}:
            return "blocked"
        if runtime_state in {"blocked", "approval_required"}:
            return "blocked"

    outcome = _clean_text(result.get("outcome"))
    status = _clean_text(result.get("status"))
    if outcome in _ERROR_OUTCOMES or status == "error":
        return "failed"

    return "idle"


def _tool_report(result: Mapping[str, Any]) -> Mapping[str, Any]:
    structured_payload = result.get("structured_payload")
    if not isinstance(structured_payload, Mapping):
        return {}

    report = structured_payload.get("report")
    if not isinstance(report, Mapping):
        return {}

    return report


def _tool_timestamp(call: Mapping[str, Any]) -> float | None:
    result = call.get("result")
    if not isinstance(result, Mapping):
        return None

    report = _tool_report(result)
    report_created_at = _parse_iso8601_timestamp(report.get("created_at"))
    if report_created_at is not None:
        return report_created_at

    structured_payload = result.get("structured_payload")
    if isinstance(structured_payload, Mapping):
        created_at = _parse_iso8601_timestamp(structured_payload.get("created_at"))
        if created_at is not None:
            return created_at

    return None


def _tool_run_key(
    *,
    session_id: str,
    message_index: int,
    call_index: int,
    tool_name: str,
    call: Mapping[str, Any],
) -> str:
    run_id = _clean_text(call.get("run_id"))
    if run_id and run_id != tool_name:
        return run_id

    result = call.get("result")
    if isinstance(result, Mapping):
        structured_payload = result.get("structured_payload")
        if isinstance(structured_payload, Mapping):
            artifact_path = _clean_text(structured_payload.get("artifact_path"))
            if artifact_path:
                return artifact_path

    return f"{session_id}:{message_index}:{call_index}"


def _event_timestamp(event: Mapping[str, Any]) -> float | None:
    for field_name in ("ended_at", "started_at"):
        timestamp = _parse_iso8601_timestamp(event.get(field_name))
        if timestamp is not None:
            return timestamp
    return None


def _parse_iso8601_timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        normalized = cleaned.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def _coerce_timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _pick_newer_timestamp(
    current: float | None,
    candidate: float | None,
) -> float | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
