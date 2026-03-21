"""Read-only observability query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.params import Query as QueryParam

from access_control import require_inspection_access
from observability import (
    build_observability_overview,
    dashboard_definitions,
    observability_retention_policy,
    query_metric_records,
    query_trace_records,
)

router = APIRouter()


def _base_dir():
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _query_default_to_none(value):
    return None if isinstance(value, QueryParam) else value


@router.get("/observability/metrics")
def list_observability_metrics(
    metric_name: str | None = Query(None),
    request_id: str | None = Query(None),
    session_id: str | None = Query(None),
    run_id: str | None = Query(None),
    step_id: str | None = Query(None),
    job_id: str | None = Query(None),
    workflow_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    span_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    request: Request = None,
):
    require_inspection_access(request)
    resolved_limit = 100 if isinstance(limit, QueryParam) else limit
    records = query_metric_records(
        _base_dir(),
        metric_name=_query_default_to_none(metric_name),
        request_id=_query_default_to_none(request_id),
        session_id=_query_default_to_none(session_id),
        run_id=_query_default_to_none(run_id),
        step_id=_query_default_to_none(step_id),
        job_id=_query_default_to_none(job_id),
        workflow_id=_query_default_to_none(workflow_id),
        trace_id=_query_default_to_none(trace_id),
        span_id=_query_default_to_none(span_id),
        limit=resolved_limit,
    )
    return {
        "metrics": [record.model_dump(mode="json") for record in records],
        "retention_policy": observability_retention_policy(),
    }


@router.get("/observability/traces")
def list_observability_traces(
    trace_id: str | None = Query(None),
    span_id: str | None = Query(None),
    parent_span_id: str | None = Query(None),
    span_name: str | None = Query(None),
    request_id: str | None = Query(None),
    session_id: str | None = Query(None),
    run_id: str | None = Query(None),
    step_id: str | None = Query(None),
    job_id: str | None = Query(None),
    workflow_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    request: Request = None,
):
    require_inspection_access(request)
    resolved_limit = 100 if isinstance(limit, QueryParam) else limit
    records = query_trace_records(
        _base_dir(),
        trace_id=_query_default_to_none(trace_id),
        span_id=_query_default_to_none(span_id),
        parent_span_id=_query_default_to_none(parent_span_id),
        span_name=_query_default_to_none(span_name),
        request_id=_query_default_to_none(request_id),
        session_id=_query_default_to_none(session_id),
        run_id=_query_default_to_none(run_id),
        step_id=_query_default_to_none(step_id),
        job_id=_query_default_to_none(job_id),
        workflow_id=_query_default_to_none(workflow_id),
        status=_query_default_to_none(status),
        limit=resolved_limit,
    )
    return {
        "traces": [record.model_dump(mode="json") for record in records],
        "retention_policy": observability_retention_policy(),
    }


@router.get("/observability/overview")
def get_observability_overview(
    days: int = Query(7, ge=1, le=90),
    request_id: str | None = Query(None),
    session_id: str | None = Query(None),
    workflow_id: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    request: Request = None,
):
    require_inspection_access(request)
    resolved_days = 7 if isinstance(days, QueryParam) else days
    resolved_limit = 5000 if isinstance(limit, QueryParam) else limit
    return build_observability_overview(
        _base_dir(),
        days=resolved_days,
        request_id=_query_default_to_none(request_id),
        session_id=_query_default_to_none(session_id),
        workflow_id=_query_default_to_none(workflow_id),
        limit=resolved_limit,
    )


@router.get("/observability/dashboard-definitions")
def get_observability_dashboard_definitions(request: Request = None):
    require_inspection_access(request)
    return {
        "dashboards": dashboard_definitions(),
        "retention_policy": observability_retention_policy(),
    }
