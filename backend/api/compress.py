"""
POST /api/sessions/{id}/compress

Compresses the oldest 50% of messages in a session:
1. Validates that ≥ 4 messages exist.
2. Takes the first 50% (min 4).
3. Calls DeepSeek to generate a concise English summary (≤ 500 chars).
4. Archives the messages + stores the summary in compressed_context.
"""
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage

router = APIRouter()


@router.post("/sessions/{session_id}/compress")
async def compress(session_id: str):
    from graph.agent import agent_manager

    sm = agent_manager.session_manager
    messages = sm.load_session(session_id)  # type: ignore[union-attr]

    if len(messages) < 4:
        raise HTTPException(400, "Need at least 4 messages to compress.")

    n = max(4, len(messages) // 2)
    to_compress = messages[:n]

    # Format conversation for summarisation
    conversation = "\n".join(
        f"{m['role'].upper()}: {m.get('content', '')}" for m in to_compress
    )

    try:
        # Use a lower-temperature variant for consistent summaries
        summary_llm = agent_manager.llm.bind(temperature=0.3)  # type: ignore[union-attr]
        resp = await summary_llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are a helpful assistant that summarises conversations concisely. "
                        "Reply in English. Keep the summary under 500 characters."
                    )
                ),
                HumanMessage(
                    content=f"Please summarise the following conversation:\n\n{conversation}"
                ),
            ]
        )
        summary = resp.content.strip()[:500]
    except Exception as exc:
        raise HTTPException(500, f"Summary generation failed: {exc}")

    archived_count, remaining_count = sm.compress_history(  # type: ignore[union-attr]
        session_id, summary, n
    )

    return {
        "session_id": session_id,
        "archived_count": archived_count,
        "remaining_count": remaining_count,
        "summary": summary,
    }
