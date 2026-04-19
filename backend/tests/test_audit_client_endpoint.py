"""Tests for /api/audit/client — the frontend-error ingestion endpoint.

Mirrors the pattern used in ``test_audit_logging.py``: swap the live
``agent_manager`` base directory for a tmp path, drive the endpoint, and
assert the audit log carries a ``client_error`` event.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.audit_client import (
    _BUCKET_CAPACITY,
    _reset_rate_limiter_for_tests,
    router as audit_client_router,
)
from audit.store import query_audit_events


@pytest.fixture
def isolated_audit_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm
    original_memory_indexer = agent_manager.memory_indexer

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.llm = MagicMock()
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("workspace", "memory", "skills", "knowledge"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

    _reset_rate_limiter_for_tests()
    try:
        yield tmp_path
    finally:
        _reset_rate_limiter_for_tests()
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm
        agent_manager.memory_indexer = original_memory_indexer


@pytest.fixture
def client(isolated_audit_state):
    app = FastAPI()
    app.include_router(audit_client_router, prefix="/api")
    return TestClient(app)


def test_records_client_error_event(client, isolated_audit_state):
    response = client.post(
        "/api/audit/client",
        json={
            "level": "error",
            "event": "error_boundary",
            "message": "kaboom",
            "stack": "at Exploder (/_next/static/chunks/app.js:1:1)",
            "meta": {"label": "Workspace"},
            "session_id": "session-abc",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"recorded": True}

    events = query_audit_events(
        isolated_audit_state,
        event_type="client_error",
    )
    assert len(events) == 1
    event = events[0]
    assert event.outcome == "error"
    assert event.session_id == "session-abc"
    assert event.actor == "client"
    assert event.details["event"] == "error_boundary"
    assert event.details["message"] == "kaboom"
    assert event.details["meta"]["label"] == "Workspace"


def test_long_fields_are_truncated(client, isolated_audit_state):
    long_message = "x" * 5_000
    long_stack = "y" * 10_000
    response = client.post(
        "/api/audit/client",
        json={
            "event": "error_boundary",
            "message": long_message,
            "stack": long_stack,
        },
    )
    assert response.status_code == 200

    events = query_audit_events(isolated_audit_state, event_type="client_error")
    assert len(events) == 1
    details = events[0].details
    assert len(details["message"]) <= 500
    assert len(details["stack"]) <= 4_000


def test_rate_limit_returns_429_after_burst(client, isolated_audit_state):
    # Fill the bucket, then one more should be refused.
    payload = {"event": "sse_stream_overflow", "message": "too many"}
    for _ in range(_BUCKET_CAPACITY):
        response = client.post("/api/audit/client", json=payload)
        assert response.status_code == 200

    blocked = client.post("/api/audit/client", json=payload)
    assert blocked.status_code == 429

    recorded = query_audit_events(isolated_audit_state, event_type="client_error")
    assert len(recorded) == _BUCKET_CAPACITY


def test_rejects_missing_event_name(client):
    response = client.post(
        "/api/audit/client",
        json={"event": "", "message": "nope"},
    )
    assert response.status_code == 422


def test_secret_looking_meta_is_passed_through_as_given(
    client, isolated_audit_state
):
    # The endpoint trusts the frontend scrub for PII. The backend's job is
    # size caps + rate limiting; it should still accept whatever structured
    # data the frontend sends so replayed scrub bugs remain visible in the
    # audit log instead of being silently re-redacted server-side.
    response = client.post(
        "/api/audit/client",
        json={
            "event": "error_boundary",
            "meta": {"status": 500, "request_count": 3, "note": None},
        },
    )
    assert response.status_code == 200
    events = query_audit_events(isolated_audit_state, event_type="client_error")
    meta = events[0].details["meta"]
    assert meta["status"] == 500
    assert meta["request_count"] == 3
