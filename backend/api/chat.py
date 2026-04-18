"""
POST /api/chat — SSE streaming conversation endpoint.

All emitted events include:
  request_id   stable per-turn identifier
  event_index  monotonic 1-based sequence number within the stream

SSE event types emitted:
  retrieval    {type, query, results}
  token        {type, content}
  tool_start   {type, tool, input, run_id}
  tool_end     {type, tool, output, result, run_id}
  tool_awaiting_approval {type, tool, input, run_id, reason, message, result?, policy?}
  plan_created {type, summary, plan, tool_trace?, run_id?}
  plan_updated {type, summary, plan, tool_trace?, run_id?}
  verification_result {type, summary, verdict, verification, tool_trace?, run_id?}
  new_response {type}
  done         {type, content, session_id, turn_status?}
  error        {type, error}

Event shaping and persistence live in ``runtime.query_engine.QueryEngine``;
this route is intentionally limited to request plumbing.

POST /api/chat/approval records a reviewer's approve/deny decision for a gated
tool call. A turn that hit ``tool_awaiting_approval`` ends with
``turn_status=awaiting_approval``; once a decision is recorded, the next
``/api/chat`` turn loads it into the tool policy context so the agent can
proceed (on approve) or route around the tool (on deny).
"""
from typing import Literal

from access_control import require_execution_access
from audit.store import append_tool_approval_decision_event
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime.query_engine import QueryEngine

router = APIRouter()

_MAX_MESSAGE_LEN = 32_000  # ~8 k tokens; prevents context blowout and large session files
_MAX_RATIONALE_LEN = 2_000
_MAX_ACTOR_LEN = 120


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    session_id: str

    @field_validator("message")
    @classmethod
    def _check_message_length(cls, value: str) -> str:
        if len(value) > _MAX_MESSAGE_LEN:
            raise ValueError(f"message too long (max {_MAX_MESSAGE_LEN} characters)")
        return value


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    run_id: str
    tool_name: str
    decision: Literal["approve", "deny"]
    actor: str = Field(default="ui-user")
    rationale: str | None = None

    @field_validator("actor")
    @classmethod
    def _check_actor(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            return "ui-user"
        if len(cleaned) > _MAX_ACTOR_LEN:
            raise ValueError(f"actor too long (max {_MAX_ACTOR_LEN} characters)")
        return cleaned

    @field_validator("rationale")
    @classmethod
    def _check_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if len(cleaned) > _MAX_RATIONALE_LEN:
            raise ValueError(
                f"rationale too long (max {_MAX_RATIONALE_LEN} characters)"
            )
        return cleaned


class ApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recorded: bool
    session_id: str
    run_id: str
    tool_name: str
    decision: Literal["approve", "deny"]
    actor: str
    recorded_at: str


@router.post("/chat")
async def chat(request: ChatRequest, http_request: Request = None):
    require_execution_access(http_request)
    try:
        QueryEngine.validate_session_id(request.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    from graph.agent import agent_manager

    engine = QueryEngine(agent_manager)
    stream = engine.stream_turn_sse(
        message=request.message,
        session_id=request.session_id,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/approval", response_model=ApprovalDecisionResponse)
async def submit_approval_decision(
    request: ApprovalDecisionRequest,
    http_request: Request = None,
) -> ApprovalDecisionResponse:
    require_execution_access(http_request)
    try:
        QueryEngine.validate_session_id(request.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    from graph import approval_store
    from graph.agent import agent_manager

    if agent_manager.base_dir is None:
        raise HTTPException(status_code=503, detail="Agent runtime is not initialized.")

    record = approval_store.record_decision(
        agent_manager.base_dir,
        session_id=request.session_id,
        tool_name=request.tool_name,
        run_id=request.run_id,
        decision=request.decision,
        actor=request.actor,
        rationale=request.rationale,
    )

    append_tool_approval_decision_event(
        agent_manager.base_dir,
        session_id=request.session_id,
        tool_name=request.tool_name,
        run_id=request.run_id,
        decision=request.decision,
        actor=record["actor"],
        rationale=record["rationale"],
    )

    return ApprovalDecisionResponse(
        recorded=True,
        session_id=request.session_id,
        run_id=record["run_id"],
        tool_name=record["tool_name"],
        decision=record["decision"],
        actor=record["actor"],
        recorded_at=record["recorded_at"],
    )
