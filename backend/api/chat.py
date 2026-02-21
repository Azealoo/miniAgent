"""
POST /api/chat — SSE streaming conversation endpoint.

SSE event types emitted:
  retrieval    {type, query, results}
  token        {type, content}
  tool_start   {type, tool, input}
  tool_end     {type, tool, output}
  new_response {type}
  done         {type, content, session_id}
  title        {type, session_id, title}   (first message only)
  error        {type, error}
"""
import json
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str
    stream: bool = True


@router.post("/chat")
async def chat(request: ChatRequest):
    from graph.agent import agent_manager

    session_manager = agent_manager.session_manager  # type: ignore[union-attr]

    # Is this the first message in the session?
    existing = session_manager.load_session(request.session_id)
    is_first_message = len(existing) == 0

    async def event_generator():
        # Per-request accumulators
        segments: list[dict] = []          # [{content, tool_calls}]
        current_content: list[str] = []
        current_tool_calls: list[dict] = []
        pending_tools: dict[str, dict] = {}  # run_id → {tool, input}

        def _flush_segment() -> None:
            content = "".join(current_content)
            if content or current_tool_calls:
                segments.append(
                    {"content": content, "tool_calls": list(current_tool_calls)}
                )
            current_content.clear()
            current_tool_calls.clear()

        def _sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            async for ev in agent_manager.astream(request.message, request.session_id):
                t = ev["type"]

                if t == "retrieval":
                    yield _sse(
                        {
                            "type": "retrieval",
                            "query": ev["query"],
                            "results": ev["results"],
                        }
                    )

                elif t == "token":
                    current_content.append(ev["content"])
                    yield _sse({"type": "token", "content": ev["content"]})

                elif t == "tool_start":
                    run_id = ev.get("run_id", ev["tool"])
                    pending_tools[run_id] = {"tool": ev["tool"], "input": ev["input"]}
                    yield _sse(
                        {"type": "tool_start", "tool": ev["tool"], "input": ev["input"]}
                    )

                elif t == "tool_end":
                    run_id = ev.get("run_id", ev["tool"])
                    started = pending_tools.pop(run_id, {"tool": ev["tool"], "input": ""})
                    call = {
                        "tool": started["tool"],
                        "input": started["input"],
                        "output": ev["output"],
                    }
                    current_tool_calls.append(call)
                    yield _sse({"type": "tool_end", "tool": ev["tool"], "output": ev["output"]})

                elif t == "new_response":
                    _flush_segment()
                    yield _sse({"type": "new_response"})

                elif t == "done":
                    _flush_segment()

                    # Persist to session
                    session_manager.save_message(
                        request.session_id, "user", request.message
                    )
                    for seg in segments:
                        session_manager.save_message(
                            request.session_id,
                            "assistant",
                            seg["content"],
                            seg["tool_calls"] or None,
                        )

                    final_content = " ".join(
                        s["content"] for s in segments if s["content"]
                    )
                    yield _sse(
                        {
                            "type": "done",
                            "content": final_content,
                            "session_id": request.session_id,
                        }
                    )

                    # Auto-generate title on first message
                    if is_first_message and final_content:
                        title = await _generate_title(
                            agent_manager, request.message
                        )
                        session_manager.rename_session(request.session_id, title)
                        yield _sse(
                            {
                                "type": "title",
                                "session_id": request.session_id,
                                "title": title,
                            }
                        )

                elif t == "error":
                    yield _sse({"type": "error", "error": ev["error"]})

        except Exception as exc:
            yield _sse({"type": "error", "error": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _generate_title(agent_manager, first_message: str) -> str:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        resp = await agent_manager.llm.ainvoke(
            [
                SystemMessage(
                    content="You generate concise chat titles. Reply with ONLY the title."
                ),
                HumanMessage(
                    content=(
                        f"Generate a short English title for a conversation that starts with: "
                        f"'{first_message[:200]}'. "
                        "Maximum 6 words. No punctuation, no quotes."
                    )
                ),
            ]
        )
        return resp.content.strip()[:15]
    except Exception:
        return "New Chat"
