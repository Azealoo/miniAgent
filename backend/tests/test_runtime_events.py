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
    TurnExit,
    build_runtime_event,
    dump_runtime_event,
    generate_runtime_events_schema,
    turn_status_to_exit,
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
            "type": "tool_awaiting_approval",
            "tool": "terminal",
            "input": "rm -rf /",
            "run_id": "run-2",
            "reason": "requires_approval",
            "message": "Approve before running.",
        },
        {
            "type": "tool_chunk",
            "tool": "terminal",
            "run_id": "run-2",
            "chunk_index": 0,
            "chunk": "partial output...",
            "terminal": False,
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
        {
            "type": "compaction_event",
            "from_turn": 1,
            "to_turn": 4,
            "summary": "Compacted early turns.",
            "saved_tokens": 1200,
        },
        {"type": "done", "content": "final"},
        {"type": "error", "error": "boom"},
        {
            "type": "workflow_step_started",
            "workflow_id": "rna-seq-qc",
            "run_id": "wf-run-1",
            "step_id": "preflight_check",
            "step_index": 1,
            "total_steps": 2,
            "label": "Validate dataset manifest",
        },
        {
            "type": "workflow_step_ended",
            "workflow_id": "rna-seq-qc",
            "run_id": "wf-run-1",
            "step_id": "preflight_check",
            "step_index": 1,
            "total_steps": 2,
            "duration_ms": 42,
            "outputs": {"validated_manifest": "artifacts/.../manifest.json"},
        },
        {
            "type": "workflow_step_failed",
            "workflow_id": "rna-seq-qc",
            "run_id": "wf-run-1",
            "step_id": "summarize_qc",
            "step_index": 2,
            "total_steps": 2,
            "duration_ms": 128,
            "error": "KeyError: min_genes",
            "failure_policy": "fail_workflow",
        },
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


def test_build_runtime_event_rejects_negative_chunk_index() -> None:
    with pytest.raises(ValidationError):
        build_runtime_event(
            {
                "type": "tool_chunk",
                "tool": "terminal",
                "run_id": "run-1",
                "chunk_index": -1,
                "chunk": "x",
            }
        )


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


def test_runtime_schema_version_is_two() -> None:
    """Issue #90 bumps the schema to 2 to gate the new ``done.exit`` payload."""
    assert RUNTIME_EVENT_SCHEMA_VERSION == 2


@pytest.mark.parametrize(
    ("turn_status", "expected_reason", "expected_code"),
    [
        ("ok", "success", 0),
        ("error", "tool_error", 1),
        ("cancelled", "user_abort", 2),
        ("budget_exceeded", "token_budget", 3),
        ("awaiting_approval", "awaiting_approval", 4),
        (None, "success", 0),
        ("something_unknown", "tool_error", 1),
    ],
)
def test_turn_status_to_exit_maps_every_known_status(
    turn_status: str | None,
    expected_reason: str,
    expected_code: int,
) -> None:
    exit_payload = turn_status_to_exit(turn_status)
    assert isinstance(exit_payload, TurnExit)
    assert exit_payload.reason == expected_reason
    assert exit_payload.exit_code == expected_code


def test_done_runtime_event_accepts_structured_exit_payload() -> None:
    event = build_runtime_event(
        {
            "type": "done",
            "content": "final",
            "turn_status": "budget_exceeded",
            "exit": {
                "reason": "token_budget",
                "exit_code": 3,
                "summary": "turn budget exceeded at 9001 tokens",
            },
        }
    )
    assert event.type == "done"
    assert event.exit is not None
    assert event.exit.reason == "token_budget"
    assert event.exit.exit_code == 3
    assert event.exit.summary == "turn budget exceeded at 9001 tokens"


def test_done_runtime_event_rejects_unknown_exit_reason() -> None:
    with pytest.raises(ValidationError):
        build_runtime_event(
            {
                "type": "done",
                "content": "final",
                "exit": {"reason": "totally_invented", "exit_code": 9},
            }
        )


def test_warning_runtime_event_accepts_schema_version_deprecated_kind() -> None:
    """The v1 deprecation notice rides on the existing ``warning`` channel."""
    event = build_runtime_event(
        {
            "type": "warning",
            "kind": "schema_version_deprecated",
            "message": "client requested RuntimeEvent schema_version=1",
        }
    )
    assert event.type == "warning"
    assert event.kind == "schema_version_deprecated"
