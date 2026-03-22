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
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from access_control import require_execution_access
from audit.store import append_chat_request_event, append_tool_invocation_event
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from observability import append_metric_record, append_trace_record, chat_span_id
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


def _evidence_review_required_response(message: str) -> str:
    return (
        "Evidence review is required before BioAPEX can provide a substantive answer to this "
        "biology request. No reviewed evidence output was completed in this turn, so unsupported "
        "claims are being withheld.\n\n"
        f"Request requiring review: {message.strip()}"
    )


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
async def chat(request: ChatRequest, http_request: Request = None):
    require_execution_access(http_request)
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
        from evidence.review_gate import (
            EVIDENCE_REVIEW_GATE_TOOL_NAME,
            EvidenceReviewGateInput,
            run_evidence_review_gate,
        )
        from protocol_executor import (
            ProtocolExecutorInput,
            classify_protocol_execution_request,
            run_protocol_executor,
        )

        append_chat_request_event(
            agent_manager.base_dir,
            session_id=request.session_id,
            message=request.message,
            attached_identifiers=request.attached_identifiers,
            selected_workflow=request.selected_workflow,
        )

        request_id = str(uuid.uuid4())
        request_started_at = datetime.now(timezone.utc).replace(microsecond=0)
        request_started_monotonic = time.perf_counter()
        first_visible_at: datetime | None = None
        first_visible_monotonic: float | None = None
        first_visible_event_type: str | None = None
        observability_recorded = False

        # Per-request accumulators
        segments: list[dict] = []          # [{content, tool_calls, workflow_events, retrievals}]
        current_content: list[str] = []
        current_tool_calls: list[dict] = []
        current_workflow_events: list[dict] = []
        current_retrievals: list[dict] = []
        pending_tools: dict[str, dict] = {}  # run_id → {tool, input}
        user_msg_saved = False              # guard: save user message exactly once
        review_required = False
        review_completed = False
        buffered_pre_review_tokens: list[str] = []
        agent_history = list(history)

        def _flush_segment() -> None:
            content = "".join(current_content)
            if content or current_tool_calls or current_workflow_events or current_retrievals:
                segments.append(
                    {
                        "content": content,
                        "tool_calls": list(current_tool_calls),
                        "workflow_events": list(current_workflow_events),
                        "retrievals": list(current_retrievals),
                    }
                )
            current_content.clear()
            current_tool_calls.clear()
            current_workflow_events.clear()
            current_retrievals.clear()

        def _mark_first_visible(payload_type: str) -> None:
            nonlocal first_visible_at, first_visible_monotonic, first_visible_event_type
            if first_visible_at is not None:
                return
            if payload_type not in {
                "retrieval",
                "token",
                "tool_start",
                "tool_end",
                "workflow_start",
                "workflow_step_start",
                "workflow_step_end",
                "workflow_blocked",
                "workflow_artifact",
                "workflow_done",
                "new_response",
                "done",
                "error",
            }:
                return
            first_visible_at = datetime.now(timezone.utc).replace(microsecond=0)
            first_visible_monotonic = time.perf_counter()
            first_visible_event_type = payload_type

        def _sse(payload: dict) -> str:
            payload_to_emit = dict(payload)
            payload_to_emit.setdefault("request_id", request_id)
            payload_type = payload_to_emit.get("type")
            if isinstance(payload_type, str):
                _mark_first_visible(payload_type)
            return f"data: {json.dumps(payload_to_emit, ensure_ascii=False)}\n\n"

        def _save_user_message() -> None:
            nonlocal user_msg_saved
            if not user_msg_saved:
                session_manager.save_message(
                    request.session_id,
                    "user",
                    request.message,
                    request_id=request_id,
                )
                user_msg_saved = True

        def _record_turn_observability(*, turn_status: str) -> None:
            nonlocal observability_recorded
            if observability_recorded:
                return
            observability_recorded = True

            ended_at = datetime.now(timezone.utc).replace(microsecond=0)
            ended_monotonic = time.perf_counter()
            first_visible_seconds = max(
                0.0,
                (first_visible_monotonic or ended_monotonic) - request_started_monotonic,
            )
            backend_execution_seconds = max(0.0, ended_monotonic - request_started_monotonic)
            span_id = chat_span_id(request_id)
            tool_call_count = sum(len(segment["tool_calls"]) for segment in segments) + len(current_tool_calls)
            workflow_event_count = (
                sum(len(segment["workflow_events"]) for segment in segments) + len(current_workflow_events)
            )
            attributes = {
                "selected_workflow": request.selected_workflow,
                "attached_identifier_count": len(request.attached_identifiers),
                "review_required": review_required,
                "review_completed": review_completed,
                "assistant_segment_count": len(segments)
                + (1 if current_content or current_tool_calls or current_workflow_events or current_retrievals else 0),
                "tool_call_count": tool_call_count,
                "workflow_event_count": workflow_event_count,
                "first_visible_event_type": first_visible_event_type or "done",
                "stream": request.stream,
            }
            append_metric_record(
                agent_manager.base_dir,
                metric_name="chat_latency_seconds",
                metric_kind="duration",
                value=first_visible_seconds,
                unit="seconds",
                request_id=request_id,
                session_id=request.session_id,
                workflow_id=request.selected_workflow,
                trace_id=request_id,
                span_id=span_id,
                attributes={**attributes, "latency_scope": "user_visible"},
                recorded_at=first_visible_at or ended_at,
            )
            append_metric_record(
                agent_manager.base_dir,
                metric_name="chat_latency_seconds",
                metric_kind="duration",
                value=backend_execution_seconds,
                unit="seconds",
                request_id=request_id,
                session_id=request.session_id,
                workflow_id=request.selected_workflow,
                trace_id=request_id,
                span_id=span_id,
                attributes={**attributes, "latency_scope": "backend_execution"},
                recorded_at=ended_at,
            )
            append_trace_record(
                agent_manager.base_dir,
                trace_id=request_id,
                span_id=span_id,
                span_name="chat_turn",
                started_at=request_started_at,
                ended_at=ended_at,
                status=turn_status,
                request_id=request_id,
                session_id=request.session_id,
                workflow_id=request.selected_workflow,
                attributes=attributes,
                duration_seconds=backend_execution_seconds,
            )

        async def _finalize_turn(*, turn_status: str = "ok") -> list[str]:
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
                    seg["retrievals"] or None,
                    request_id=request_id,
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

            _record_turn_observability(turn_status=turn_status)
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
            append_tool_invocation_event(
                agent_manager.base_dir,
                session_id=request.session_id,
                workflow_id=request.selected_workflow,
                tool_name=started["tool"],
                tool_run_id=preflight_run_id,
                tool_input=started["input"],
                result=preflight.tool_result,
            )
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
                blocked_turn = preflight.report.final_disposition in {"block", "require_approval"}
                for payload in await _finalize_turn(turn_status="blocked" if blocked_turn else "ok"):
                    yield payload
                return

            protocol_request = classify_protocol_execution_request(
                agent_manager.base_dir,
                ProtocolExecutorInput(
                    user_message=request.message,
                    attached_identifiers=request.attached_identifiers,
                    selected_workflow=request.selected_workflow,
                ),
            )
            if protocol_request.is_protocol_request:
                protocol_result = run_protocol_executor(
                    agent_manager.base_dir,
                    ProtocolExecutorInput(
                        user_message=request.message,
                        attached_identifiers=request.attached_identifiers,
                        selected_workflow=request.selected_workflow,
                    ),
                    compliance_report=preflight.report,
                    compliance_artifact_relpath=preflight.artifact_relpath,
                    classification=protocol_request,
                )
                protocol_run_id = protocol_result.protocol_run.run_id
                pending_tools[protocol_run_id] = {
                    "tool": "protocol_executor",
                    "input": protocol_result.tool_input,
                }
                yield _sse(
                    {
                        "type": "tool_start",
                        "tool": "protocol_executor",
                        "input": protocol_result.tool_input,
                        "run_id": protocol_run_id,
                    }
                )
                started = pending_tools.pop(
                    protocol_run_id,
                    {"tool": "protocol_executor", "input": protocol_result.tool_input},
                )
                protocol_call = {
                    "tool": started["tool"],
                    "input": started["input"],
                    "output": protocol_result.tool_summary,
                    "run_id": protocol_run_id,
                    "result": protocol_result.tool_result,
                }
                current_tool_calls.append(protocol_call)
                append_tool_invocation_event(
                    agent_manager.base_dir,
                    session_id=request.session_id,
                    workflow_id=request.selected_workflow,
                    tool_name=started["tool"],
                    tool_run_id=protocol_run_id,
                    tool_input=started["input"],
                    result=protocol_result.tool_result,
                )
                yield _sse(
                    {
                        "type": "tool_end",
                        "tool": "protocol_executor",
                        "output": protocol_result.tool_summary,
                        "run_id": protocol_run_id,
                        "result": protocol_result.tool_result,
                    }
                )
                current_content.append(protocol_result.response_text)
                yield _sse({"type": "token", "content": protocol_result.response_text})
                for payload in await _finalize_turn():
                    yield payload
                return

            gate = run_evidence_review_gate(
                EvidenceReviewGateInput(
                    user_message=request.message,
                    attached_identifiers=request.attached_identifiers,
                    selected_workflow=request.selected_workflow,
                )
            )
            gate_run_id = f"{EVIDENCE_REVIEW_GATE_TOOL_NAME}:{request.session_id}"
            pending_tools[gate_run_id] = {
                "tool": EVIDENCE_REVIEW_GATE_TOOL_NAME,
                "input": gate.tool_input,
            }
            yield _sse(
                {
                    "type": "tool_start",
                    "tool": EVIDENCE_REVIEW_GATE_TOOL_NAME,
                    "input": gate.tool_input,
                    "run_id": gate_run_id,
                }
            )
            started = pending_tools.pop(
                gate_run_id,
                {"tool": EVIDENCE_REVIEW_GATE_TOOL_NAME, "input": gate.tool_input},
            )
            gate_call = {
                "tool": started["tool"],
                "input": started["input"],
                "output": gate.tool_summary,
                "run_id": gate_run_id,
                "result": gate.tool_result,
            }
            current_tool_calls.append(gate_call)
            append_tool_invocation_event(
                agent_manager.base_dir,
                session_id=request.session_id,
                workflow_id=request.selected_workflow,
                tool_name=started["tool"],
                tool_run_id=gate_run_id,
                tool_input=started["input"],
                result=gate.tool_result,
            )
            yield _sse(
                {
                    "type": "tool_end",
                    "tool": EVIDENCE_REVIEW_GATE_TOOL_NAME,
                    "output": gate.tool_summary,
                    "run_id": gate_run_id,
                    "result": gate.tool_result,
                }
            )
            review_required = gate.requires_review
            if gate.system_message:
                agent_history = agent_history + [{"role": "system", "content": gate.system_message}]

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
                        session_id=request.session_id,
                        request_id=request_id,
                    )
                    for workflow_event in blocked_run.workflow_events:
                        workflow_payload = dict(workflow_event)
                        workflow_payload.setdefault("request_id", request_id)
                        current_workflow_events.append(workflow_payload)
                        yield _sse(workflow_payload)

                    workflow_summary = describe_blocked_workflow(
                        prepared_workflow,
                        prepared_workflow.blocking_reason,
                    )
                    current_content.append(workflow_summary)
                    yield _sse({"type": "token", "content": workflow_summary})
                    for payload in await _finalize_turn(turn_status="blocked"):
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
                        session_id=request.session_id,
                        request_id=request_id,
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
                        workflow_payload = dict(workflow_event)
                        workflow_payload.setdefault("request_id", request_id)
                        current_workflow_events.append(workflow_payload)
                        yield _sse(workflow_payload)

                workflow_result = workflow_future.result()
                workflow_summary = describe_workflow_result(prepared_workflow, workflow_result)
                current_content.append(workflow_summary)
                yield _sse({"type": "token", "content": workflow_summary})
                workflow_status = (
                    "blocked"
                    if workflow_result.run.lifecycle_status == "blocked"
                    else "error" if workflow_result.run.lifecycle_status == "failed" else "ok"
                )
                for payload in await _finalize_turn(turn_status=workflow_status):
                    yield payload
                return

            async for ev in agent_manager.astream(request.message, agent_history):
                t = ev["type"]

                if t == "retrieval":
                    current_retrievals.extend(ev["results"])
                    yield _sse(
                        {
                            "type": "retrieval",
                            "query": ev["query"],
                            "results": ev["results"],
                        }
                    )

                elif t == "token":
                    if review_required and not review_completed:
                        buffered_pre_review_tokens.append(ev["content"])
                    else:
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
                    append_tool_invocation_event(
                        agent_manager.base_dir,
                        session_id=request.session_id,
                        workflow_id=request.selected_workflow,
                        tool_name=ev["tool"],
                        tool_run_id=run_id,
                        tool_input=started["input"],
                        result=ev.get("result"),
                    )
                    payload = {
                        "type": "tool_end",
                        "tool": ev["tool"],
                        "output": ev["output"],
                        "run_id": run_id,
                    }
                    if ev.get("result") is not None:
                        payload["result"] = ev["result"]
                    yield _sse(payload)
                    if ev["tool"] == "evidence_review":
                        review_completed = True
                        buffered_pre_review_tokens.clear()

                elif is_workflow_stream_event_type(t):
                    workflow_event = normalize_workflow_stream_event(
                        {**ev, "request_id": ev.get("request_id", request_id)}
                    )
                    current_workflow_events.append(workflow_event)
                    yield _sse(workflow_event)

                elif t == "new_response":
                    if review_required and not review_completed:
                        buffered_pre_review_tokens.clear()
                    else:
                        _flush_segment()
                        yield _sse({"type": "new_response"})

                elif t == "done":
                    if review_required and not review_completed:
                        fallback = _evidence_review_required_response(request.message)
                        current_content.append(fallback)
                        yield _sse({"type": "token", "content": fallback})
                    elif review_required and review_completed and not any(
                        segment["content"] for segment in segments
                    ) and not current_content:
                        post_review_note = (
                            "Evidence review completed for this turn. Inspect the tool trace for "
                            "the structured review outputs and artifact refs."
                        )
                        current_content.append(post_review_note)
                        yield _sse({"type": "token", "content": post_review_note})
                    turn_status = "blocked" if review_required and not review_completed else "ok"
                    for payload in await _finalize_turn(turn_status=turn_status):
                        yield payload

                elif t == "error":
                    # Persist the user message even when the agent fails so the
                    # session history stays consistent for future turns.
                    _save_user_message()
                    yield _sse({"type": "error", "error": ev["error"]})
                    _record_turn_observability(turn_status="error")
                    return

        except Exception as exc:
            # Same: ensure user message is recorded before surfacing the error.
            _save_user_message()
            yield _sse({"type": "error", "error": str(exc)})
            _record_turn_observability(turn_status="error")
            return

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
