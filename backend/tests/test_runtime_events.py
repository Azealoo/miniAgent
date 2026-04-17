"""Drift-guard + smoke tests for the transport-neutral RuntimeEvent schema.

Every SSE (and future WebSocket/stdin) payload leaving the runtime is validated
through the pydantic models in ``runtime.events``. The frontend mirrors them as
zod schemas — the committed ``runtime/events.schema.json`` snapshot here is the
contract both sides agree on. This test re-generates the snapshot and fails the
build on drift.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime.events import (
    RUNTIME_EVENT_SCHEMA_VERSION,
    RUNTIME_EVENT_TYPES,
    SCHEMA_SNAPSHOT_PATH,
    build_runtime_event,
    dump_runtime_event,
    generate_runtime_events_schema,
)


def test_runtime_event_schema_snapshot_matches_pydantic_models() -> None:
    """Fail the build if the committed JSON schema drifts from pydantic models.

    The frontend zod schemas are regenerated against the committed snapshot;
    without this guard a silent backend change would leave the frontend parsing
    the old shape. Regenerate with:
        python -c "import json; from runtime.events import *; \
            SCHEMA_SNAPSHOT_PATH.write_text(json.dumps(generate_runtime_events_schema(), indent=2, sort_keys=True) + '\\n')"
    """
    committed = json.loads(SCHEMA_SNAPSHOT_PATH.read_text())
    current = generate_runtime_events_schema()
    assert current == committed, (
        "backend/runtime/events.schema.json is out of date with "
        "runtime.events — regenerate it and update the frontend zod mirror."
    )


def test_runtime_event_snapshot_lists_every_expected_event_type() -> None:
    committed = json.loads(SCHEMA_SNAPSHOT_PATH.read_text())
    discriminator_mapping = committed["discriminator"]["mapping"]
    assert set(discriminator_mapping.keys()) == set(RUNTIME_EVENT_TYPES)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "retrieval", "query": "brca1", "results": [{"text": "x", "source": "a", "score": 0.1}]},
        {"type": "token", "content": "hello"},
        {"type": "tool_start", "tool": "read_file", "input": "x", "run_id": "run-1"},
        {
            "type": "tool_end",
            "tool": "read_file",
            "output": "x",
            "run_id": "run-1",
            "result": {"status": "success"},
        },
        {
            "type": "plan_created",
            "summary": "planner",
            "plan": {"goal": "g", "steps": []},
        },
        {
            "type": "plan_updated",
            "summary": "planner",
            "plan": {"goal": "g", "steps": []},
        },
        {
            "type": "verification_result",
            "summary": "ok",
            "verdict": "pass",
            "verification": {"verdict": "pass"},
        },
        {"type": "new_response"},
        {"type": "done", "content": "final"},
        {"type": "error", "error": "boom"},
    ],
)
def test_build_runtime_event_accepts_each_event_type(payload: dict) -> None:
    event = build_runtime_event(payload)
    assert event.type == payload["type"]
    assert event.schema_version == RUNTIME_EVENT_SCHEMA_VERSION


def test_dump_runtime_event_stamps_schema_version_and_drops_nones() -> None:
    dumped = dump_runtime_event({"type": "token", "content": "hello"})
    assert dumped == {
        "type": "token",
        "content": "hello",
        "schema_version": RUNTIME_EVENT_SCHEMA_VERSION,
    }


def test_dump_runtime_event_preserves_transport_envelope_fields() -> None:
    dumped = dump_runtime_event(
        {
            "type": "token",
            "content": "hello",
            "request_id": "req-1",
            "event_index": 7,
        }
    )
    assert dumped["request_id"] == "req-1"
    assert dumped["event_index"] == 7
    assert dumped["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION


def test_build_runtime_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        build_runtime_event({"type": "not_a_type", "content": "x"})


def test_build_runtime_event_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        build_runtime_event({"type": "token", "content": "hi", "surprise": True})


def test_build_runtime_event_rejects_bad_verdict() -> None:
    with pytest.raises(ValidationError):
        build_runtime_event(
            {
                "type": "verification_result",
                "summary": "x",
                "verdict": "maybe",
                "verification": {},
            }
        )


def test_schema_snapshot_path_points_inside_backend_runtime() -> None:
    assert SCHEMA_SNAPSHOT_PATH.parent.name == "runtime"
    assert SCHEMA_SNAPSHOT_PATH.name == "events.schema.json"
    assert SCHEMA_SNAPSHOT_PATH.exists()
