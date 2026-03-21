"""
POST /api/sessions/{id}/compress

Compresses the oldest 50% of messages in a session:
1. Validates that ≥ 4 messages exist.
2. Takes the first 50% (min 4).
3. Generates a structured scientific continuity summary.
4. Archives the messages + stores the summary in compressed_context.
"""
from fastapi import APIRouter, HTTPException, Request

from access_control import require_execution_access
from graph.session_summary import generate_structured_summary
from graph.session_manager import _validate_session_id

router = APIRouter()


@router.post("/sessions/{session_id}/compress")
async def compress(session_id: str, request: Request = None):
    require_execution_access(request)
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    from graph.agent import agent_manager

    sm = agent_manager.session_manager  # type: ignore[union-attr]

    # Hold the per-session lock for the full compress operation so that
    # simultaneous manual compress calls and auto-compress cannot race.
    async with sm.get_or_create_compress_lock(session_id):
        messages = sm.load_session(session_id)

        if len(messages) < 4:
            raise HTTPException(400, "Need at least 4 messages to compress.")

        n = max(4, len(messages) // 2)
        to_compress = messages[:n]

        try:
            summary = await generate_structured_summary(
                to_compress, agent_manager.llm  # type: ignore[union-attr]
            )
        except Exception as exc:
            raise HTTPException(500, f"Summary generation failed: {exc}")

        archived_count, remaining_count = sm.compress_history(session_id, summary, n)

    return {
        "session_id": session_id,
        "archived_count": archived_count,
        "remaining_count": remaining_count,
        "summary": summary,
    }
