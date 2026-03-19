"""
POST /api/chat — SSE streaming conversation endpoint.

SSE event types emitted:
  retrieval    {type, query, results}
  token        {type, content}
  tool_start   {type, tool, input, run_id, compliance_state?}
  tool_end     {type, tool, output, result, run_id, compliance_state?}
  workflow_*   additive typed workflow lifecycle events
  new_response {type}
  done         {type, content, session_id}
  title        {type, session_id, title}   (first message only)
  error        {type, error}
"""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from graph.session_manager import _validate_session_id
from workflow_chat import (
    describe_blocked_workflow,
    describe_workflow_result,
    materialize_blocked_workflow_run,
    prepare_selected_workflow_run,
)
from workflow_runner import InternalDAGRunner
from workflow_streaming import is_workflow_stream_event_type, normalize_workflow_stream_event

router = APIRouter()

# Strong-reference set for background tasks.
# asyncio.create_task() does not hold a reference to the task — if nothing
# else does, the GC can collect the task mid-execution (Python ≥ 3.9 warning).
_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    """Schedule *coro* as a background task that won't be GC'd mid-execution."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


_MAX_MESSAGE_LEN = 32_000  # ~8 k tokens; prevents context blowout and large session files


class ChatRequest(BaseModel):
    message: str
    session_id: str
    stream: bool = True
    attached_identifiers: list[str] = Field(default_factory=list)
    selected_workflow: str | None = None

    @field_validator("message")
    @classmethod
    def _check_message_length(cls, v: str) -> str:
        if len(v) > _MAX_MESSAGE_LEN:
            raise ValueError(f"message too long (max {_MAX_MESSAGE_LEN} characters)")
        return v


@router.post("/chat")
async def chat(request: ChatRequest):
    try:
        _validate_session_id(request.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    from graph.agent import agent_manager

    session_manager = agent_manager.session_manager  # type: ignore[union-attr]

    # Should we auto-generate a title at the end of this turn?
    # Checked before compression so we capture the pre-turn state.
    # We use "no assistant reply yet" as the condition — not "no messages at all" —
    # because after the M1 fix a failed first turn saves a user message, and we
    # still want title generation on the first *successful* assistant response.
    existing = session_manager.load_session(request.session_id)
    is_first_message = not any(m.get("role") == "assistant" for m in existing)

    # Auto-compress if history is too long (≥ 40 messages)
    await session_manager.auto_compress_if_needed(  # type: ignore[union-attr]
        request.session_id, agent_manager.llm
    )

    # Load and prepare history for the agent
    history = session_manager.load_session_for_agent(request.session_id)  # type: ignore[union-attr]

    async def event_generator():
        from compliance.preflight import (
            CompliancePreflightInput,
            run_compliance_preflight,
        )

        # Per-request accumulators
        segments: list[dict] = []          # [{content, tool_calls, workflow_events}]
        current_content: list[str] = []
        current_tool_calls: list[dict] = []
        current_workflow_events: list[dict] = []
        pending_tools: dict[str, dict] = {}  # run_id → {tool, input}
        user_msg_saved = False              # guard: save user message exactly once

        def _flush_segment() -> None:
            content = "".join(current_content)
            if content or current_tool_calls or current_workflow_events:
                segments.append(
                    {
                        "content": content,
                        "tool_calls": list(current_tool_calls),
                        "workflow_events": list(current_workflow_events),
                    }
                )
            current_content.clear()
            current_tool_calls.clear()
            current_workflow_events.clear()

        def _sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def _save_user_message() -> None:
            nonlocal user_msg_saved
            if not user_msg_saved:
                session_manager.save_message(
                    request.session_id, "user", request.message
                )
                user_msg_saved = True

        async def _finalize_turn() -> list[str]:
            _flush_segment()

            # Persist user message + each assistant segment to session
            _save_user_message()
            for seg in segments:
                session_manager.save_message(
                    request.session_id,
                    "assistant",
                    seg["content"],
                    seg["tool_calls"] or None,
                    seg["workflow_events"] or None,
                )

            final_content = " ".join(s["content"] for s in segments if s["content"])
            payloads = [
                _sse(
                    {
                        "type": "done",
                        "content": final_content,
                        "session_id": request.session_id,
                    }
                )
            ]

            if is_first_message and final_content:
                _sid = request.session_id
                title_task = asyncio.create_task(
                    _generate_title_only(agent_manager, request.message)
                )
                _background_tasks.add(title_task)
                title_task.add_done_callback(_background_tasks.discard)

                def _persist_title(task: asyncio.Task) -> None:
                    try:
                        title = task.result()
                        if title:
                            session_manager.rename_session(_sid, title)
                    except Exception:
                        pass

                title_task.add_done_callback(_persist_title)

                try:
                    title = await asyncio.wait_for(
                        asyncio.shield(title_task), timeout=12.0
                    )
                    if title:
                        payloads.append(
                            _sse(
                                {
                                    "type": "title",
                                    "session_id": _sid,
                                    "title": title,
                                }
                            )
                        )
                except asyncio.CancelledError:
                    raise
                except (asyncio.TimeoutError, Exception):
                    pass

            return payloads

        try:
            preflight = run_compliance_preflight(
                agent_manager.base_dir,
                CompliancePreflightInput(
                    user_message=request.message,
                    attached_identifiers=request.attached_identifiers,
                    selected_workflow=request.selected_workflow,
                    session_id=request.session_id,
                ),
            )
            preflight_run_id = preflight.report.run_id
            pending_tools[preflight_run_id] = {
                "tool": "compliance_preflight",
                "input": preflight.tool_input,
            }
            yield _sse(
                {
                    "type": "tool_start",
                    "tool": "compliance_preflight",
                    "input": preflight.tool_input,
                    "run_id": preflight_run_id,
                    "compliance_state": "preflight_pending",
                }
            )

            started = pending_tools.pop(
                preflight_run_id,
                {"tool": "compliance_preflight", "input": preflight.tool_input},
            )
            preflight_call = {
                "tool": started["tool"],
                "input": started["input"],
                "output": preflight.tool_summary,
                "run_id": preflight_run_id,
                "result": preflight.tool_result,
            }
            current_tool_calls.append(preflight_call)
            yield _sse(
                {
                    "type": "tool_end",
                    "tool": "compliance_preflight",
                    "output": preflight.tool_summary,
                    "run_id": preflight_run_id,
                    "compliance_state": preflight.report.runtime_state,
                    "result": preflight.tool_result,
                }
            )

            if preflight.warning_text:
                current_content.append(preflight.warning_text)
                yield _sse({"type": "token", "content": preflight.warning_text})
                _flush_segment()
                yield _sse({"type": "new_response"})

            if not preflight.should_continue:
                if preflight.response_text:
                    current_content.append(preflight.response_text)
                    yield _sse({"type": "token", "content": preflight.response_text})
                for payload in await _finalize_turn():
                    yield payload
                return

            if request.selected_workflow:
                prepared_workflow = prepare_selected_workflow_run(
                    agent_manager.base_dir,
                    request.selected_workflow,
                    message=request.message,
                    attached_identifiers=request.attached_identifiers,
                )

                if prepared_workflow.blocking_reason:
                    blocked_run = materialize_blocked_workflow_run(
                        agent_manager.base_dir,
                        prepared_workflow,
                        reason=prepared_workflow.blocking_reason,
                    )
                    for workflow_event in blocked_run.workflow_events:
                        current_workflow_events.append(workflow_event)
                        yield _sse(workflow_event)

                    workflow_summary = describe_blocked_workflow(
                        prepared_workflow,
                        prepared_workflow.blocking_reason,
                    )
                    current_content.append(workflow_summary)
                    yield _sse({"type": "token", "content": workflow_summary})
                    for payload in await _finalize_turn():
                        yield payload
                    return

                workflow_queue: asyncio.Queue[dict] = asyncio.Queue()
                loop = asyncio.get_running_loop()

                def _on_workflow_event(event: dict) -> None:
                    loop.call_soon_threadsafe(workflow_queue.put_nowait, event)

                workflow_runner = InternalDAGRunner(agent_manager.base_dir)
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="workflow-chat") as executor:
                    workflow_future = executor.submit(
                        workflow_runner.run,
                        prepared_workflow.spec_path,
                        prepared_workflow.inputs,
                        event_callback=_on_workflow_event,
                    )

                    while True:
                        if workflow_future.done() and workflow_queue.empty():
                            break
                        try:
                            workflow_event = await asyncio.wait_for(
                                workflow_queue.get(),
                                timeout=0.1,
                            )
                        except asyncio.TimeoutError:
                            continue
                        current_workflow_events.append(workflow_event)
                        yield _sse(workflow_event)

                    workflow_result = workflow_future.result()
                workflow_summary = describe_workflow_result(prepared_workflow, workflow_result)
                current_content.append(workflow_summary)
                yield _sse({"type": "token", "content": workflow_summary})
                for payload in await _finalize_turn():
                    yield payload
                return

            async for ev in agent_manager.astream(request.message, history):
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
                        {
                            "type": "tool_start",
                            "tool": ev["tool"],
                            "input": ev["input"],
                            "run_id": run_id,
                        }
                    )

                elif t == "tool_end":
                    run_id = ev.get("run_id", ev["tool"])
                    started = pending_tools.pop(run_id, {"tool": ev["tool"], "input": ""})
                    call = {
                        "tool": started["tool"],
                        "input": started["input"],
                        "output": ev["output"],
                        "run_id": run_id,
                    }
                    if ev.get("result") is not None:
                        call["result"] = ev["result"]
                    current_tool_calls.append(call)
                    payload = {
                        "type": "tool_end",
                        "tool": ev["tool"],
                        "output": ev["output"],
                        "run_id": run_id,
                    }
                    if ev.get("result") is not None:
                        payload["result"] = ev["result"]
                    yield _sse(payload)

                elif is_workflow_stream_event_type(t):
                    workflow_event = normalize_workflow_stream_event(ev)
                    current_workflow_events.append(workflow_event)
                    yield _sse(workflow_event)

                elif t == "new_response":
                    _flush_segment()
                    yield _sse({"type": "new_response"})

                elif t == "done":
                    for payload in await _finalize_turn():
                        yield payload

                elif t == "error":
                    # Persist the user message even when the agent fails so the
                    # session history stays consistent for future turns.
                    _save_user_message()
                    yield _sse({"type": "error", "error": ev["error"]})

        except Exception as exc:
            # Same: ensure user message is recorded before surfacing the error.
            _save_user_message()
            yield _sse({"type": "error", "error": str(exc)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _generate_title_only(agent_manager, first_message: str) -> str:
    """Call the LLM to produce a short chat title.  Returns the title string
    (empty on failure).  Callers are responsible for persisting it."""
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
                        "Maximum 10 words. No punctuation, no quotes."
                    )
                ),
            ]
        )
        return resp.content.strip()[:60]
    except Exception:
        return ""  # non-fatal — done-callback skips rename when title is empty
