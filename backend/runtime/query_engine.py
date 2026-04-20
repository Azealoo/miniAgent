from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Awaitable, Callable, AsyncGenerator, Sequence

from config import (
    get_max_tokens_per_turn,
    get_max_turn_wallclock_s,
    get_verification_settings,
    snapshot_runtime_config,
)
from runtime.events import (
    RUNTIME_EVENT_SCHEMA_VERSION,
    dump_runtime_event,
    turn_status_to_exit,
)
from runtime.metrics_collector import METRICS
from runtime.turn_ledger import TurnLedger, TurnResult
from tools.registry import ToolManifestEntry, is_concurrency_safe_tier


@dataclass(frozen=True)
class ToolBatchCall:
    """A single resolved tool call pending dispatch.

    ``invoke`` is a zero-argument coroutine factory so the dispatcher can
    await it at the point it chooses (gathered vs. serial). ``manifest``
    tells the dispatcher which tier the call belongs to.
    """

    manifest: ToolManifestEntry
    invoke: Callable[[], Awaitable[Any]]


async def dispatch_tool_batch(
    calls: Sequence[ToolBatchCall],
) -> list[Any]:
    """Partition resolved tool calls by risk tier and dispatch them.

    Read-only/concurrency-safe calls are launched together through
    ``asyncio.gather`` so their I/O overlaps. Destructive calls run
    serially in input order so their side effects happen one at a time.
    Results are returned in the original input order regardless of tier.
    """
    results: list[Any] = [None] * len(calls)
    parallel_indices: list[int] = []
    parallel_awaitables: list[Awaitable[Any]] = []
    serial_indices: list[int] = []

    for idx, call in enumerate(calls):
        if is_concurrency_safe_tier(call.manifest):
            parallel_indices.append(idx)
            parallel_awaitables.append(call.invoke())
        else:
            serial_indices.append(idx)

    if parallel_awaitables:
        gathered = await asyncio.gather(*parallel_awaitables)
        for idx, value in zip(parallel_indices, gathered):
            results[idx] = value

    for idx in serial_indices:
        results[idx] = await calls[idx].invoke()

    return results

_logger = logging.getLogger(__name__)


async def _bounded_async_stream(
    agen: AsyncIterator[dict],
    wallclock_deadline: float | None,
) -> AsyncGenerator[dict, None]:
    """Re-yield ``agen`` events while enforcing an absolute wall-clock deadline.

    When ``wallclock_deadline`` is ``None`` the helper behaves as a thin
    pass-through. Otherwise each ``__anext__()`` is wrapped in
    ``asyncio.wait_for`` with the remaining time budget so a stuck tool
    awaiting inside the inner agent receives a ``CancelledError`` at its
    next await point. The underlying generator is always closed in the
    ``finally`` block so tool ``finally:`` handlers run.

    Raises ``asyncio.TimeoutError`` to the caller when the deadline is hit.
    """
    try:
        while True:
            if wallclock_deadline is not None:
                remaining = wallclock_deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError("turn wallclock budget exceeded")
                event = await asyncio.wait_for(
                    agen.__anext__(),
                    timeout=remaining,
                )
            else:
                event = await agen.__anext__()
            yield event
    except StopAsyncIteration:
        return
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                _logger.debug(
                    "agent astream aclose raised during bounded stream teardown",
                    exc_info=True,
                )


def _count_tokens(value: Any) -> int:
    """Delegate to the shared token accounting helper in api.tokens."""
    from api.tokens import _count_optional_text

    return _count_optional_text(value)


def _coerce_nonnegative_int(value: Any, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else 0


def _coerce_nonnegative_float(value: Any, default: float) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else 0.0


@dataclass(frozen=True)
class QueryTurnInput:
    message: str
    history: list[dict]
    policy_context: Any | None = None


class QueryEngine:
    """
    Runtime boundary for conversation turns.

    The HTTP route should hand off execution decisions here so the route can
    focus on transport and persistence concerns.
    """

    def __init__(self, agent_manager) -> None:
        self.agent_manager = agent_manager

    @staticmethod
    def validate_session_id(session_id: str) -> None:
        """Re-export session-id validation so the HTTP route can stay on ``runtime.*``."""
        from graph.session_manager import _validate_session_id

        _validate_session_id(session_id)

    @staticmethod
    def _extract_helper_tool_payload(
        event: dict[str, Any],
    ) -> tuple[str, dict[str, Any], str, list[dict[str, Any]]] | None:
        if event.get("type") != "tool_end":
            return None

        tool_name = event.get("tool")
        result = event.get("result")
        if not isinstance(tool_name, str) or not isinstance(result, dict):
            return None
        if result.get("status") != "success":
            return None

        structured_payload = result.get("structured_payload")
        if not isinstance(structured_payload, dict):
            return None

        summary = result.get("summary")
        if not isinstance(summary, str) or not summary:
            output = event.get("output")
            summary = output if isinstance(output, str) else tool_name

        tool_trace = structured_payload.get("tool_trace")
        normalized_trace = (
            [dict(item) for item in tool_trace if isinstance(item, dict)]
            if isinstance(tool_trace, list)
            else []
        )
        return tool_name, structured_payload, summary, normalized_trace

    @staticmethod
    def _build_plan_helper_event(
        structured_payload: dict[str, Any],
        *,
        summary: str,
        run_id: Any,
        normalized_trace: list[dict[str, Any]],
        saw_plan: bool,
    ) -> dict[str, Any] | None:
        plan = structured_payload.get("plan")
        if (
            structured_payload.get("agent_type") != "plan"
            or not isinstance(plan, dict)
        ):
            return None
        return {
            "type": "plan_updated" if saw_plan else "plan_created",
            "run_id": run_id,
            "summary": summary,
            "plan": dict(plan),
            "tool_trace": normalized_trace,
        }

    @staticmethod
    def _build_verification_helper_event(
        structured_payload: dict[str, Any],
        *,
        summary: str,
        run_id: Any,
        normalized_trace: list[dict[str, Any]],
        saw_plan: bool,
    ) -> dict[str, Any] | None:
        del saw_plan
        verification = structured_payload.get("verification")
        if (
            structured_payload.get("agent_type") != "verification"
            or not isinstance(verification, dict)
        ):
            return None
        verdict = verification.get("verdict")
        return {
            "type": "verification_result",
            "run_id": run_id,
            "summary": summary,
            "verdict": verdict if isinstance(verdict, str) else "fail",
            "verification": dict(verification),
            "tool_trace": normalized_trace,
        }

    @classmethod
    def _extract_helper_agent_event(
        cls,
        event: dict[str, Any],
        *,
        saw_plan: bool,
    ) -> dict[str, Any] | None:
        helper_payload = cls._extract_helper_tool_payload(event)
        if helper_payload is None:
            return None

        tool_name, structured_payload, summary, normalized_trace = helper_payload
        run_id = event.get("run_id")
        helper_builder = {
            "plan_agent": cls._build_plan_helper_event,
            "verification_agent": cls._build_verification_helper_event,
        }.get(tool_name)
        if helper_builder is None:
            return None
        return helper_builder(
            structured_payload,
            summary=summary,
            run_id=run_id,
            normalized_trace=normalized_trace,
            saw_plan=saw_plan,
        )

    @staticmethod
    def _verification_requires_repair(event: dict[str, Any] | None) -> bool:
        if not isinstance(event, dict):
            return False
        verdict = event.get("verdict")
        if verdict == "fail":
            return True
        if verdict != "repair_required":
            return False
        verification_settings = get_verification_settings()
        return bool(verification_settings.get("retry_on_repair_required", True))

    @staticmethod
    def _build_repair_history(
        turn: QueryTurnInput,
        *,
        latest_plan: dict[str, Any] | None,
        latest_verification: dict[str, Any],
        draft_answer: str,
    ) -> list[dict[str, str]]:
        verification_payload = latest_verification.get("verification")
        verification = (
            dict(verification_payload)
            if isinstance(verification_payload, dict)
            else {}
        )
        repair_lines = [
            "This is the single runtime-managed repair retry for the same user task.",
            "Return a corrected answer for the user. Keep any valid material, fix the verifier findings, "
            "and do not mention the repair pass unless it helps the user.",
            "Clearly separate what you confirmed by inspecting files or tool outputs in this turn from "
            "what came from retrieved memory, templates, or prior-session notes. Do not present "
            "background guidance as verified current project state.",
            f"Original user task:\n{turn.message.strip()}",
        ]

        if latest_plan is not None:
            repair_lines.append(
                "Latest plan artifact:\n"
                + json.dumps(latest_plan.get("plan", {}), indent=2, sort_keys=True)
            )

        verifier_lines = [
            f"Verdict: {latest_verification.get('verdict', 'fail')}",
            f"Summary: {latest_verification.get('summary', '')}",
        ]
        issues = verification.get("issues")
        if isinstance(issues, list) and issues:
            verifier_lines.append("Issues:")
            verifier_lines.extend(
                f"- {issue}" for issue in issues if isinstance(issue, str) and issue
            )
        repair_instructions = verification.get("repair_instructions")
        if isinstance(repair_instructions, list) and repair_instructions:
            verifier_lines.append("Repair instructions:")
            verifier_lines.extend(
                f"- {instruction}"
                for instruction in repair_instructions
                if isinstance(instruction, str) and instruction
            )
        repair_lines.append("Latest verifier findings:\n" + "\n".join(verifier_lines))

        if draft_answer.strip():
            repair_lines.append(f"First-pass draft answer:\n{draft_answer.strip()}")

        repair_lines.append(
            "Use the verifier findings to improve the answer before you finalize."
        )
        return list(turn.history) + [{"role": "system", "content": "\n\n".join(repair_lines)}]

    async def run_turn(
        self,
        turn: QueryTurnInput,
        *,
        ledger: TurnLedger | None = None,
    ) -> AsyncGenerator[dict, None]:
        if ledger is None:
            ledger = TurnLedger()

        for event in ledger.consume({"type": "persist_user_message"}):
            yield event

        async for event in self.run_harness_turn(turn):
            if event.get("type") == "done":
                turn_status = event.get("turn_status") or event.get("status", "ok")
                forwarded: dict[str, Any] = {
                    "type": "done",
                    "turn_status": turn_status,
                    "turn_result": ledger.finalize(turn_status=turn_status),
                }
                exit_payload = event.get("exit")
                if isinstance(exit_payload, dict):
                    forwarded["exit"] = exit_payload
                yield forwarded
                return
            if event.get("type") == "error":
                turn_status = event.get("turn_status", "error")
                payload = dict(event)
                payload["turn_result"] = ledger.finalize(turn_status=turn_status)
                yield payload
                return
            for output_event in ledger.consume(event):
                yield output_event

    async def run_harness_turn(
        self,
        turn: QueryTurnInput,
    ) -> AsyncGenerator[dict, None]:
        saw_plan = False
        repair_attempted = False
        current_turn = turn

        budget = get_max_tokens_per_turn()
        verification_settings = get_verification_settings()
        verifier_max_wall_s = _coerce_nonnegative_float(
            verification_settings.get("verifier_max_wall_s"), 0.0
        )
        verifier_max_tokens = _coerce_nonnegative_int(
            verification_settings.get("verifier_max_tokens"), 0
        )

        input_tokens = _count_tokens(turn.message) + sum(
            _count_tokens(message.get("content")) for message in turn.history
        )
        output_tokens = 0
        # Populated the first time a ``verification_result`` helper event is
        # observed; the wallclock + token caps only apply from that point on,
        # and cover the single repair retry that may follow.
        verifier_started_monotonic: float | None = None
        verifier_start_output_tokens = 0
        METRICS.record_input_tokens(input_tokens)

        # Turn-level wall-clock budget (seconds). 0 disables the cap. The
        # deadline is absolute over the entire turn (inclusive of any repair
        # retry pass) so a stuck tool cannot extend the turn by entering the
        # retry loop.
        wallclock_budget_s = get_max_turn_wallclock_s()
        wallclock_deadline = (
            time.monotonic() + wallclock_budget_s
            if wallclock_budget_s > 0
            else None
        )

        def _budget_exceeded() -> bool:
            return budget > 0 and (input_tokens + output_tokens) > budget

        def _budget_error_event() -> dict[str, Any]:
            total = input_tokens + output_tokens
            event = {
                "type": "error",
                "error": f"turn budget exceeded at {total} tokens",
                "turn_status": "budget_exceeded",
                "exit": turn_status_to_exit(
                    "budget_exceeded",
                    summary=f"turn budget exceeded at {total} tokens",
                ).model_dump(exclude_none=True),
            }
            METRICS.observe_event(event)
            return event

        def _wallclock_timeout_error_event() -> dict[str, Any]:
            summary = (
                f"turn wallclock budget of {wallclock_budget_s:.1f}s exceeded"
            )
            event = {
                "type": "error",
                "error": summary,
                "turn_status": "cancelled",
                "exit": turn_status_to_exit(
                    "cancelled",
                    summary=summary,
                ).model_dump(exclude_none=True),
            }
            METRICS.observe_event(event)
            return event

        def _verifier_cap_breach_reason() -> str | None:
            if verifier_started_monotonic is None:
                return None
            if verifier_max_wall_s > 0:
                elapsed = time.monotonic() - verifier_started_monotonic
                if elapsed > verifier_max_wall_s:
                    return (
                        f"verifier wallclock cap exceeded at {elapsed:.2f}s "
                        f"(limit {verifier_max_wall_s:g}s)"
                    )
            if verifier_max_tokens > 0:
                used = output_tokens - verifier_start_output_tokens
                if used > verifier_max_tokens:
                    return (
                        f"verifier token cap exceeded at {used} output tokens "
                        f"(limit {verifier_max_tokens})"
                    )
            return None

        def _verifier_cap_error_event(summary: str) -> dict[str, Any]:
            event = {
                "type": "error",
                "error": summary,
                "turn_status": "verifier_cap_exceeded",
                "exit": turn_status_to_exit(
                    "verifier_cap_exceeded",
                    summary=summary,
                ).model_dump(exclude_none=True),
            }
            METRICS.observe_event(event)
            return event

        while True:
            latest_plan_event: dict[str, Any] | None = None
            latest_verification_event: dict[str, Any] | None = None
            draft_segments: list[str] = []
            current_segment: list[str] = []
            turn_status = "ok"

            inner_agen = self.agent_manager.astream(
                current_turn.message,
                current_turn.history,
            )
            bounded = _bounded_async_stream(inner_agen, wallclock_deadline)
            wallclock_timed_out = False
            try:
                async for event in bounded:
                    event_type = event.get("type")
                    if event_type == "done":
                        turn_status = event.get("turn_status") or event.get("status", "ok")
                        break

                    METRICS.observe_event(event)

                    if event_type == "token":
                        content = event.get("content")
                        if isinstance(content, str) and content:
                            current_segment.append(content)
                            output_tokens += _count_tokens(content)
                        yield event
                        if _budget_exceeded():
                            yield _budget_error_event()
                            return
                        cap_reason = _verifier_cap_breach_reason()
                        if cap_reason is not None:
                            yield _verifier_cap_error_event(cap_reason)
                            return
                        continue

                    if event_type == "new_response":
                        if current_segment:
                            draft_segments.append("".join(current_segment))
                            current_segment.clear()
                        yield event
                        continue

                    # Prompt-cache usage samples are internal: the metrics
                    # collector records them against the Prometheus gauges but
                    # they should not reach the SSE wire.
                    if event_type == "llm_usage":
                        continue

                    if event_type == "tool_start":
                        input_tokens += _count_tokens(event.get("input"))
                    elif event_type == "tool_end":
                        output_tokens += _count_tokens(event.get("output"))

                    yield event
                    helper_event = self._extract_helper_agent_event(event, saw_plan=saw_plan)
                    if helper_event is not None:
                        if helper_event["type"] in {"plan_created", "plan_updated"}:
                            saw_plan = True
                            latest_plan_event = helper_event
                        elif helper_event["type"] == "verification_result":
                            latest_verification_event = helper_event
                            if verifier_started_monotonic is None:
                                verifier_started_monotonic = time.monotonic()
                                verifier_start_output_tokens = output_tokens
                        METRICS.observe_event(helper_event)
                        yield helper_event

                    if _budget_exceeded():
                        yield _budget_error_event()
                        return
                    cap_reason = _verifier_cap_breach_reason()
                    if cap_reason is not None:
                        yield _verifier_cap_error_event(cap_reason)
                        return
            except asyncio.TimeoutError:
                # Turn wallclock budget exceeded. asyncio.wait_for has
                # already cancelled the in-flight astream task (and any
                # tool awaiting inside it), so emitting an error event is
                # safe — the consumer will finalize the ledger in the same
                # "cancelled" path used for client-disconnect.
                wallclock_timed_out = True

            if wallclock_timed_out:
                if current_segment:
                    draft_segments.append("".join(current_segment))
                yield _wallclock_timeout_error_event()
                return

            if current_segment:
                draft_segments.append("".join(current_segment))

            if _budget_exceeded():
                yield _budget_error_event()
                return
            cap_reason = _verifier_cap_breach_reason()
            if cap_reason is not None:
                yield _verifier_cap_error_event(cap_reason)
                return

            should_retry = (
                not repair_attempted
                and turn_status == "ok"
                and self._verification_requires_repair(latest_verification_event)
                and latest_verification_event is not None
            )
            if not should_retry:
                done_event: dict[str, Any] = {
                    "type": "done",
                    "turn_status": turn_status,
                    "exit": turn_status_to_exit(turn_status).model_dump(
                        exclude_none=True
                    ),
                }
                METRICS.observe_event(done_event)
                yield done_event
                return

            repair_attempted = True
            yield {"type": "new_response"}
            current_turn = replace(
                turn,
                history=self._build_repair_history(
                    turn,
                    latest_plan=latest_plan_event,
                    latest_verification=latest_verification_event,
                    draft_answer="\n\n".join(segment for segment in draft_segments if segment),
                ),
            )
            input_tokens += sum(
                _count_tokens(message.get("content")) for message in current_turn.history
            )

    @staticmethod
    def _attach_policy_payload(
        payload: dict[str, Any],
        result: Any,
    ) -> dict[str, Any]:
        if isinstance(result, dict):
            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                policy = metadata.get("policy")
                if isinstance(policy, dict):
                    payload["policy"] = policy
        return payload

    @classmethod
    def _shape_event_for_sse(cls, event: dict[str, Any]) -> dict[str, Any]:
        event_type = event.get("type")
        if event_type == "retrieval":
            return {
                "type": "retrieval",
                "query": event["query"],
                "results": event["results"],
            }
        if event_type == "token":
            return {"type": "token", "content": event["content"]}
        if event_type == "tool_start":
            payload = dict(event)
            payload["run_id"] = event.get("run_id", event["tool"])
            return payload
        if event_type == "tool_end":
            payload = dict(event)
            payload["run_id"] = event.get("run_id", event["tool"])
            return cls._attach_policy_payload(payload, event.get("result"))
        if event_type == "tool_awaiting_approval":
            payload = dict(event)
            payload["run_id"] = event.get("run_id", event["tool"])
            return cls._attach_policy_payload(payload, event.get("result"))
        if event_type == "tool_chunk":
            payload = dict(event)
            payload["run_id"] = event.get("run_id", event["tool"])
            return payload
        if event_type == "new_response":
            return {"type": "new_response"}
        return event

    async def stream_turn_sse(
        self,
        *,
        message: str,
        session_id: str,
        client_schema_version: int | None = None,
    ) -> AsyncGenerator[str, None]:
        """Run a turn and yield fully-shaped SSE payload strings.

        Owns:
          - per-turn ``request_id`` and monotonic ``event_index`` assignment
          - tool policy context for the turn
          - SSE envelope formatting for every runtime event
          - persistence of the user message and assistant segments via ``TurnLedger``

        ``client_schema_version`` is taken from the ``X-Runtime-Event-Schema-Version``
        request header. When a v1 client connects, a single ``warning`` event with
        ``kind="schema_version_deprecated"`` is emitted before the stream body so
        the consumer learns that it should migrate to reading ``done.exit``.
        """
        # Deferred imports: ``tools`` pulls in langchain at module load time,
        # which some QueryEngine unit tests avoid by importing the class
        # without the full runtime. Keep the dependency scoped to SSE runs.
        from graph import approval_store
        from runtime.compaction import maybe_compact_turn_boundary
        from tools.policy import tool_policy_context
        from tools.policy_types import ToolPolicyExecutionContext

        session_manager = self.agent_manager.session_manager
        assert session_manager is not None

        # Freeze runtime config for the duration of the turn. Mid-turn edits
        # to backend/config.json or env overrides are rejected at the file
        # API boundary, and the captured ``loaded_at`` is stamped onto the
        # session so later inspection tools can trace which config shaped
        # this turn's decisions.
        runtime_snapshot = snapshot_runtime_config()
        try:
            session_manager.stamp_runtime_config_snapshot(
                session_id,
                loaded_at=runtime_snapshot.loaded_at,
            )
        except Exception:
            _logger.warning(
                "Failed to stamp runtime-config snapshot onto session %s",
                session_id,
                exc_info=True,
            )

        await session_manager.auto_compress_if_needed(
            session_id,
            self.agent_manager.llm,
        )
        compaction_event = await maybe_compact_turn_boundary(
            session_manager,
            session_id,
            self.agent_manager.llm,
        )
        history = session_manager.load_session_for_agent(session_id)

        request_id = str(uuid.uuid4())
        base_dir = getattr(self.agent_manager, "base_dir", None)
        approved_tool_runs: frozenset[str] = frozenset()
        denied_tool_runs: frozenset[str] = frozenset()
        if base_dir is not None:
            try:
                approved_tool_runs = approval_store.approved_tool_names(
                    base_dir, session_id
                )
                denied_tool_runs = frozenset(
                    record["tool_name"]
                    for record in approval_store.denied_records(base_dir, session_id)
                )
            except Exception:
                approved_tool_runs = frozenset()
                denied_tool_runs = frozenset()
        policy_context = ToolPolicyExecutionContext(
            session_id=session_id,
            request_id=request_id,
            turn_id=request_id,
            approved_tool_runs=approved_tool_runs,
            denied_tool_runs=denied_tool_runs,
        )
        ledger = TurnLedger(
            session_manager=session_manager,
            session_id=session_id,
            request_id=request_id,
            user_message=message,
        )

        event_counter = itertools.count(1)

        def _sse(payload: dict[str, Any]) -> str:
            envelope = dict(payload)
            envelope.setdefault("request_id", request_id)
            envelope.setdefault("event_index", next(event_counter))
            # Validate + stamp schema_version through the transport-neutral
            # RuntimeEvent schema so SSE, WebSocket, and any future adapter share
            # one source of truth for event shapes.
            validated = dump_runtime_event(envelope)
            return f"data: {json.dumps(validated, ensure_ascii=False)}\n\n"

        turn = QueryTurnInput(
            message=message,
            history=list(history),
            policy_context=policy_context,
        )

        with tool_policy_context(policy_context):
            try:
                if (
                    isinstance(client_schema_version, int)
                    and client_schema_version < RUNTIME_EVENT_SCHEMA_VERSION
                ):
                    yield _sse(
                        {
                            "type": "warning",
                            "kind": "schema_version_deprecated",
                            "message": (
                                f"client requested RuntimeEvent schema_version="
                                f"{client_schema_version}; server is on "
                                f"{RUNTIME_EVENT_SCHEMA_VERSION}. Read ``done.exit`` "
                                "(reason/exit_code/summary) instead of ``done.turn_status``."
                            ),
                        }
                    )
                if compaction_event is not None:
                    METRICS.observe_event(compaction_event)
                    yield _sse(compaction_event)
                async for event in self.run_turn(turn, ledger=ledger):
                    event_type = event.get("type")

                    if event_type == "persist_user_message":
                        ledger.persist_user_message()
                        continue

                    if event_type == "done":
                        turn_result = event.get("turn_result")
                        if not isinstance(turn_result, TurnResult):
                            raise RuntimeError("runtime done event missing turn_result")
                        ledger.persist_user_message()
                        ledger.persist_segments(turn_result)
                        turn_status = getattr(turn_result, "turn_status", None)
                        done_payload: dict[str, Any] = {
                            "type": "done",
                            "content": turn_result.final_content,
                            "session_id": session_id,
                        }
                        if isinstance(turn_status, str) and turn_status not in {"", "ok"}:
                            done_payload["turn_status"] = turn_status
                        done_payload["exit"] = turn_status_to_exit(
                            turn_status if isinstance(turn_status, str) else None,
                        ).model_dump(exclude_none=True)
                        if (
                            base_dir is not None
                            and turn_status != "awaiting_approval"
                        ):
                            try:
                                approval_store.consume(base_dir, session_id)
                            except Exception:
                                pass
                        yield _sse(done_payload)
                        return

                    if event_type == "error":
                        turn_result = event.get("turn_result")
                        if not isinstance(turn_result, TurnResult):
                            # Defensive fallback: finalize so the user message
                            # and any accumulated segments land in one batch.
                            turn_result = ledger.finalize(turn_status="error")
                        ledger.persist_segments(turn_result)
                        yield _sse({"type": "error", "error": event["error"]})
                        return

                    yield _sse(self._shape_event_for_sse(event))
            except (asyncio.CancelledError, GeneratorExit):
                # Client disconnect (or any upstream cancel) reaches us as a
                # CancelledError thrown into the awaiting `async for`, or as
                # GeneratorExit when the consumer drops the generator entirely.
                # Persist whatever the agent has already produced so the next
                # turn picks up from a consistent on-disk state, then re-raise
                # so cancellation continues propagating to in-flight tools.
                # Pending approvals are deliberately NOT consumed here: the
                # turn never reached its terminal state, so they remain valid
                # for the next /api/chat retry.
                try:
                    ledger.persist_user_message()
                    cancelled_result = ledger.finalize(turn_status="cancelled")
                    ledger.persist_segments(cancelled_result)
                except Exception:
                    _logger.warning(
                        "Failed to persist partial turn state on cancellation",
                        exc_info=True,
                    )
                raise
            except Exception as exc:
                # Persistence is batched through persist_segments so the user
                # message and any partial assistant segments land in one
                # advisory-flock scope — never split across two writes.
                try:
                    ledger.persist_segments(ledger.finalize(turn_status="error"))
                except Exception:
                    _logger.warning(
                        "Failed to persist partial turn state on unexpected exception",
                        exc_info=True,
                    )
                error_event = {"type": "error", "error": str(exc)}
                METRICS.observe_event(error_event)
                yield _sse(error_event)
