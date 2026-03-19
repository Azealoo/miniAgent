"""Typed contracts for additive workflow SSE events."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from artifacts.schemas import WorkflowLifecycleStatus

WORKFLOW_EVENT_CONTRACT_VERSION = "workflow_event.v1"

WorkflowStepStreamStatus = Literal[
    "created",
    "waiting",
    "running",
    "failed",
    "completed",
    "blocked",
]
WorkflowBlockingSource = Literal["qc_gate", "compliance_hook", "step_failure", "unknown"]
WorkflowBlockStage = Literal["before_execution", "before_step", "after_step", "before_publish"]
WorkflowArtifactScope = Literal["run_record", "step_output", "workflow_output", "related_artifact"]


class WorkflowArtifactRefPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str
    path: str
    id: str | None = None
    run_id: str | None = None


class WorkflowStreamEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["workflow_event.v1"] = WORKFLOW_EVENT_CONTRACT_VERSION
    run_id: str
    workflow_id: str


class WorkflowStartEvent(WorkflowStreamEventBase):
    type: Literal["workflow_start"] = "workflow_start"
    workflow_name: str
    lifecycle_status: WorkflowLifecycleStatus
    resumed: bool = False
    run_record_path: str


class WorkflowStepStartEvent(WorkflowStreamEventBase):
    type: Literal["workflow_step_start"] = "workflow_step_start"
    step_id: str
    step_label: str
    status: Literal["running"] = "running"
    executor_type: str
    prerequisite_step_ids: list[str] = Field(default_factory=list)
    engine_name: str | None = None


class WorkflowStepEndEvent(WorkflowStreamEventBase):
    type: Literal["workflow_step_end"] = "workflow_step_end"
    step_id: str
    step_label: str
    status: Literal["completed", "failed", "blocked"] = "completed"
    artifact_refs: list[WorkflowArtifactRefPayload] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WorkflowBlockedEvent(WorkflowStreamEventBase):
    type: Literal["workflow_blocked"] = "workflow_blocked"
    lifecycle_status: Literal["blocked"] = "blocked"
    reason: str
    stage: WorkflowBlockStage
    blocking_source: WorkflowBlockingSource
    step_id: str | None = None
    step_label: str | None = None


class WorkflowArtifactEvent(WorkflowStreamEventBase):
    type: Literal["workflow_artifact"] = "workflow_artifact"
    artifact: WorkflowArtifactRefPayload
    scope: WorkflowArtifactScope
    step_id: str | None = None
    step_label: str | None = None
    output_name: str | None = None


class WorkflowDoneEvent(WorkflowStreamEventBase):
    type: Literal["workflow_done"] = "workflow_done"
    lifecycle_status: WorkflowLifecycleStatus
    run_record_path: str
    completed_steps: int
    total_steps: int
    warning_count: int


WorkflowStreamEvent = Annotated[
    (
        WorkflowStartEvent
        | WorkflowStepStartEvent
        | WorkflowStepEndEvent
        | WorkflowBlockedEvent
        | WorkflowArtifactEvent
        | WorkflowDoneEvent
    ),
    Field(discriminator="type"),
]

WORKFLOW_STREAM_EVENT_TYPES = {
    "workflow_start",
    "workflow_step_start",
    "workflow_step_end",
    "workflow_blocked",
    "workflow_artifact",
    "workflow_done",
}

_WORKFLOW_EVENT_ADAPTER = TypeAdapter(WorkflowStreamEvent)


def is_workflow_stream_event_type(event_type: str) -> bool:
    return event_type in WORKFLOW_STREAM_EVENT_TYPES


def normalize_workflow_stream_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a workflow stream payload for SSE/session use."""

    event = _WORKFLOW_EVENT_ADAPTER.validate_python(payload)
    return event.model_dump(mode="json")


__all__ = [
    "WORKFLOW_EVENT_CONTRACT_VERSION",
    "WORKFLOW_STREAM_EVENT_TYPES",
    "WorkflowArtifactScope",
    "WorkflowBlockingSource",
    "WorkflowDoneEvent",
    "WorkflowStartEvent",
    "WorkflowStepEndEvent",
    "WorkflowStepStartEvent",
    "WorkflowStreamEvent",
    "is_workflow_stream_event_type",
    "normalize_workflow_stream_event",
]
