"""Read-only audit log query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.params import Query as QueryParam

from audit.store import AuditEventType, audit_retention_policy, query_audit_events

router = APIRouter()


def _base_dir():
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _query_default_to_none(value):
    return None if isinstance(value, QueryParam) else value


@router.get("/audit/events")
def list_audit_events(
    event_type: AuditEventType | None = Query(None),
    session_id: str | None = Query(None),
    run_id: str | None = Query(None),
    step_id: str | None = Query(None),
    job_id: str | None = Query(None),
    workflow_id: str | None = Query(None),
    tool_name: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    resolved_limit = 100 if isinstance(limit, QueryParam) else limit
    events = query_audit_events(
        _base_dir(),
        event_type=_query_default_to_none(event_type),
        session_id=_query_default_to_none(session_id),
        run_id=_query_default_to_none(run_id),
        step_id=_query_default_to_none(step_id),
        job_id=_query_default_to_none(job_id),
        workflow_id=_query_default_to_none(workflow_id),
        tool_name=_query_default_to_none(tool_name),
        outcome=_query_default_to_none(outcome),
        limit=resolved_limit,
    )
    return {
        "events": [event.model_dump(mode="json") for event in events],
        "retention_policy": audit_retention_policy(),
    }
