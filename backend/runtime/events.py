"""Transport-neutral RuntimeEvent schema shared by every runtime stream adapter.

SSE is only one consumer. The typed models here are the source of truth for every
event that leaves the runtime; the zod mirrors in ``frontend/src/lib/runtime-events.ts``
must stay in sync with them, and the drift-guard in ``tests/test_runtime_events.py``
regenerates ``events.schema.json`` on every run so backend and frontend cannot diverge
silently.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

RUNTIME_EVENT_SCHEMA_VERSION: int = 1

SCHEMA_SNAPSHOT_PATH = Path(__file__).with_name("events.schema.json")


class _RuntimeEventBase(BaseModel):
    """Fields common to every runtime event, regardless of transport."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(
        default=RUNTIME_EVENT_SCHEMA_VERSION,
        description="Version of the RuntimeEvent schema this event conforms to.",
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Stable per-turn identifier stamped by the transport adapter.",
    )
    event_index: Optional[int] = Field(
        default=None,
        description="Monotonic 1-based sequence number within a single turn.",
        ge=1,
    )


class RetrievalRuntimeEvent(_RuntimeEventBase):
    type: Literal["retrieval"] = "retrieval"
    query: str
    results: list[dict[str, Any]]


class TokenRuntimeEvent(_RuntimeEventBase):
    type: Literal["token"] = "token"
    content: str


class ToolStartRuntimeEvent(_RuntimeEventBase):
    type: Literal["tool_start"] = "tool_start"
    tool: str
    input: str
    run_id: str


class ToolEndRuntimeEvent(_RuntimeEventBase):
    type: Literal["tool_end"] = "tool_end"
    tool: str
    output: str
    run_id: str
    result: Optional[dict[str, Any]] = None
    policy: Optional[dict[str, Any]] = None


class PlanCreatedRuntimeEvent(_RuntimeEventBase):
    type: Literal["plan_created"] = "plan_created"
    summary: str
    plan: dict[str, Any]
    run_id: Optional[str] = None
    tool_trace: Optional[list[dict[str, Any]]] = None


class PlanUpdatedRuntimeEvent(_RuntimeEventBase):
    type: Literal["plan_updated"] = "plan_updated"
    summary: str
    plan: dict[str, Any]
    run_id: Optional[str] = None
    tool_trace: Optional[list[dict[str, Any]]] = None


class VerificationResultRuntimeEvent(_RuntimeEventBase):
    type: Literal["verification_result"] = "verification_result"
    summary: str
    verdict: Literal["pass", "repair_required", "fail"]
    verification: dict[str, Any]
    run_id: Optional[str] = None
    tool_trace: Optional[list[dict[str, Any]]] = None


class NewResponseRuntimeEvent(_RuntimeEventBase):
    type: Literal["new_response"] = "new_response"


class CompactionRuntimeEvent(_RuntimeEventBase):
    type: Literal["compaction_event"] = "compaction_event"
    from_turn: int
    to_turn: int
    summary: str
    saved_tokens: int


class DoneRuntimeEvent(_RuntimeEventBase):
    type: Literal["done"] = "done"
    content: str
    session_id: Optional[str] = None


class ErrorRuntimeEvent(_RuntimeEventBase):
    type: Literal["error"] = "error"
    error: str


RuntimeEvent = Annotated[
    Union[
        RetrievalRuntimeEvent,
        TokenRuntimeEvent,
        ToolStartRuntimeEvent,
        ToolEndRuntimeEvent,
        PlanCreatedRuntimeEvent,
        PlanUpdatedRuntimeEvent,
        VerificationResultRuntimeEvent,
        NewResponseRuntimeEvent,
        CompactionRuntimeEvent,
        DoneRuntimeEvent,
        ErrorRuntimeEvent,
    ],
    Field(discriminator="type"),
]

RUNTIME_EVENT_TYPES: tuple[str, ...] = (
    "retrieval",
    "token",
    "tool_start",
    "tool_end",
    "plan_created",
    "plan_updated",
    "verification_result",
    "new_response",
    "compaction_event",
    "done",
    "error",
)

_RUNTIME_EVENT_ADAPTER: TypeAdapter[RuntimeEvent] = TypeAdapter(RuntimeEvent)


def build_runtime_event(payload: dict[str, Any]) -> Any:
    """Validate ``payload`` and return the matching pydantic RuntimeEvent instance."""
    return _RUNTIME_EVENT_ADAPTER.validate_python(payload)


def dump_runtime_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate ``payload`` and return its JSON-mode dict, with ``schema_version`` stamped."""
    event = _RUNTIME_EVENT_ADAPTER.validate_python(payload)
    return _RUNTIME_EVENT_ADAPTER.dump_python(event, mode="json", exclude_none=True)


def generate_runtime_events_schema() -> dict[str, Any]:
    """Return the JSON schema describing the RuntimeEvent union."""
    return _RUNTIME_EVENT_ADAPTER.json_schema(ref_template="#/$defs/{model}")
