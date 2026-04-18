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
  plan_created {type, summary, plan, tool_trace?, run_id?}
  plan_updated {type, summary, plan, tool_trace?, run_id?}
  verification_result {type, summary, verdict, verification, tool_trace?, run_id?}
  new_response {type}
  done         {type, content, session_id}
  error        {type, error}

Event shaping and persistence live in ``runtime.query_engine.QueryEngine``;
this route is intentionally limited to request plumbing.
"""
from access_control import require_execution_access
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, field_validator

from runtime.query_engine import QueryEngine

router = APIRouter()

_MAX_MESSAGE_LEN = 32_000  # ~8 k tokens; prevents context blowout and large session files


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
