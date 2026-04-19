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

RUNTIME_EVENT_SCHEMA_VERSION: int = 2

SCHEMA_SNAPSHOT_PATH = Path(__file__).with_name("events.schema.json")

# Canonical reason taxonomy for the terminal ``DoneRuntimeEvent.exit`` payload.
# ``turn_status`` is retained alongside ``exit`` for v1 clients; new consumers
# should branch on ``exit.reason``.
TurnExitReason = Literal[
    "success",
    "tool_error",
    "user_abort",
    "context_limit",
    "token_budget",
    "approval_denied",
    "awaiting_approval",
]

_TURN_STATUS_TO_EXIT: dict[str, tuple[str, int]] = {
    "ok": ("success", 0),
    "awaiting_approval": ("awaiting_approval", 4),
    "budget_exceeded": ("token_budget", 3),
    # ``verifier_cap_exceeded`` is only carried on ``error`` events emitted
    # by ``run_harness_turn``; the SSE adapter strips turn_status off error
    # payloads before they leave the server, so this does not need a slot
    # in ``DoneRuntimeEvent.turn_status``.
    "verifier_cap_exceeded": ("token_budget", 3),
    "error": ("tool_error", 1),
    "cancelled": ("user_abort", 2),
}


class TurnExit(BaseModel):
    """Structured terminal-state payload carried on every ``done`` event.

    Replaces the v1 convention of inferring exit state from ``turn_status``
    alone: callers should branch on ``reason`` and treat ``exit_code`` as the
    shell-style result (0 = success, non-zero = failure class).
    """

    model_config = ConfigDict(extra="forbid")

    reason: TurnExitReason = Field(
        description="Canonical exit reason for the turn.",
    )
    exit_code: int = Field(
        description="Shell-style exit code — 0 for success, non-zero per reason.",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Optional human-readable one-liner describing the exit.",
    )


def turn_status_to_exit(
    turn_status: Optional[str],
    *,
    summary: Optional[str] = None,
) -> TurnExit:
    """Map a legacy ``turn_status`` string onto a structured ``TurnExit``.

    Unknown statuses fall back to ``tool_error`` so v2 consumers always see a
    populated ``exit`` payload.
    """
    status = turn_status if isinstance(turn_status, str) and turn_status else "ok"
    reason, code = _TURN_STATUS_TO_EXIT.get(status, ("tool_error", 1))
    return TurnExit(reason=reason, exit_code=code, summary=summary)  # type: ignore[arg-type]


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


class RetrievalErrorRuntimeEvent(_RuntimeEventBase):
    """Non-fatal signal that a RAG retrieval attempt raised.

    Emitted when ``MemoryIndexer.retrieve`` (or the LLM-probe fallback) throws
    during the pre-turn retrieval phase. The turn itself continues — callers
    still record a retrieval miss via the metrics collector — but the reviewer
    sees the failure in the UI instead of the old silent swallow.
    """

    type: Literal["retrieval_error"] = "retrieval_error"
    query: str
    error_type: str
    message: str


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


class ToolAwaitingApprovalRuntimeEvent(_RuntimeEventBase):
    """Emitted when policy gates a tool call pending human approval.

    Replaces (does not accompany) the `tool_end` event for that run_id; the
    underlying tool was not invoked. The frontend renders an inline gate so a
    reviewer can approve or deny the call before the turn resumes.
    """

    type: Literal["tool_awaiting_approval"] = "tool_awaiting_approval"
    tool: str
    input: str
    run_id: str
    reason: str
    message: str
    result: Optional[dict[str, Any]] = None
    policy: Optional[dict[str, Any]] = None


class ToolChunkRuntimeEvent(_RuntimeEventBase):
    """Mid-tool partial output for streaming-capable tools.

    Always followed by a terminal `tool_end` for the same `run_id`. Chunks are
    transport-only — they are not persisted in session JSON; only the final
    `tool_end` envelope is.
    """

    type: Literal["tool_chunk"] = "tool_chunk"
    tool: str
    run_id: str
    chunk_index: int = Field(ge=0)
    chunk: str
    terminal: bool = False


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
    phase: Optional[Literal["snip", "microcompact", "collapse", "autocompact"]] = Field(
        default=None,
        description=(
            "Which rung of the progressive compaction ladder produced this "
            "event. Absent for legacy payloads predating the four-phase "
            "ladder (issue #82)."
        ),
    )


class WarningRuntimeEvent(_RuntimeEventBase):
    """Non-fatal diagnostic surfaced to the user during a turn.

    Emitted just before ``done`` when a runtime check finds a condition the
    reviewer should see but that does not interrupt response delivery. The
    canonical use case is ``kind == "citation_mismatch"``: the final answer
    cited PMIDs that are not present on any evidence card included in this
    turn's ``evidence_review`` artifact.
    """

    type: Literal["warning"] = "warning"
    kind: str
    message: str
    missing: list[str] = Field(default_factory=list)
    cited: list[str] = Field(default_factory=list)
    included: list[str] = Field(default_factory=list)
    review_path: Optional[str] = None


class DoneRuntimeEvent(_RuntimeEventBase):
    type: Literal["done"] = "done"
    content: str
    session_id: Optional[str] = None
    turn_status: Optional[
        Literal["ok", "awaiting_approval", "budget_exceeded", "error", "cancelled"]
    ] = Field(
        default=None,
        description=(
            "Legacy v1 terminal state indicator, retained for clients that have "
            "not migrated to the ``exit`` payload. New consumers must branch on "
            "``exit.reason`` instead — the canonical taxonomy is defined there."
        ),
    )
    exit: Optional[TurnExit] = Field(
        default=None,
        description=(
            "Structured terminal-state payload introduced in schema_version=2. "
            "``reason`` covers success|tool_error|user_abort|context_limit|"
            "token_budget|approval_denied|awaiting_approval and ``exit_code`` is "
            "shell-style (0 for success, non-zero per reason). Absent on v1 "
            "payloads during rollout but stamped on every producer path here."
        ),
    )


class ErrorRuntimeEvent(_RuntimeEventBase):
    type: Literal["error"] = "error"
    error: str


class WorkflowStepStartedRuntimeEvent(_RuntimeEventBase):
    """Emitted by the workflow runner before it invokes a step's executor.

    ``run_id`` identifies the workflow run (stable across all three step events
    for the same invocation); ``step_id`` identifies the step within the spec.
    Transport-only — not persisted in session JSON.
    """

    type: Literal["workflow_step_started"] = "workflow_step_started"
    workflow_id: str
    run_id: str
    step_id: str
    step_index: int = Field(ge=1)
    total_steps: int = Field(ge=1)
    label: Optional[str] = None
    attempt: int = Field(default=1, ge=1)


class WorkflowStepEndedRuntimeEvent(_RuntimeEventBase):
    type: Literal["workflow_step_ended"] = "workflow_step_ended"
    workflow_id: str
    run_id: str
    step_id: str
    step_index: int = Field(ge=1)
    total_steps: int = Field(ge=1)
    duration_ms: int = Field(ge=0)
    outputs: Optional[dict[str, Any]] = None


class WorkflowStepFailedRuntimeEvent(_RuntimeEventBase):
    type: Literal["workflow_step_failed"] = "workflow_step_failed"
    workflow_id: str
    run_id: str
    step_id: str
    step_index: int = Field(ge=1)
    total_steps: int = Field(ge=1)
    duration_ms: int = Field(ge=0)
    error: str
    failure_policy: Literal["fail_workflow", "block_workflow", "continue_with_warning"]
    attempt: int = Field(default=1, ge=1)


RuntimeEvent = Annotated[
    Union[
        RetrievalRuntimeEvent,
        RetrievalErrorRuntimeEvent,
        TokenRuntimeEvent,
        ToolStartRuntimeEvent,
        ToolEndRuntimeEvent,
        ToolAwaitingApprovalRuntimeEvent,
        ToolChunkRuntimeEvent,
        PlanCreatedRuntimeEvent,
        PlanUpdatedRuntimeEvent,
        VerificationResultRuntimeEvent,
        NewResponseRuntimeEvent,
        CompactionRuntimeEvent,
        WarningRuntimeEvent,
        DoneRuntimeEvent,
        ErrorRuntimeEvent,
        WorkflowStepStartedRuntimeEvent,
        WorkflowStepEndedRuntimeEvent,
        WorkflowStepFailedRuntimeEvent,
    ],
    Field(discriminator="type"),
]

RUNTIME_EVENT_TYPES: tuple[str, ...] = (
    "retrieval",
    "retrieval_error",
    "token",
    "tool_start",
    "tool_end",
    "tool_awaiting_approval",
    "tool_chunk",
    "plan_created",
    "plan_updated",
    "verification_result",
    "new_response",
    "compaction_event",
    "warning",
    "done",
    "error",
    "workflow_step_started",
    "workflow_step_ended",
    "workflow_step_failed",
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
