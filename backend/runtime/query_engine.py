from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, AsyncGenerator

from config import get_max_tokens_per_turn, get_verification_settings
from runtime.turn_ledger import TurnLedger


def _count_tokens(value: Any) -> int:
    """Delegate to the shared token accounting helper in api.tokens."""
    from api.tokens import _count_optional_text

    return _count_optional_text(value)


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
    ) -> AsyncGenerator[dict, None]:
        ledger = TurnLedger()

        for event in ledger.consume({"type": "persist_user_message"}):
            yield event

        async for event in self.run_harness_turn(turn):
            if event.get("type") == "done":
                turn_status = event.get("turn_status") or event.get("status", "ok")
                yield {
                    "type": "done",
                    "turn_status": turn_status,
                    "turn_result": ledger.finalize(turn_status=turn_status),
                }
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
        input_tokens = _count_tokens(turn.message) + sum(
            _count_tokens(message.get("content")) for message in turn.history
        )
        output_tokens = 0

        def _budget_exceeded() -> bool:
            return budget > 0 and (input_tokens + output_tokens) > budget

        def _budget_error_event() -> dict[str, Any]:
            total = input_tokens + output_tokens
            return {
                "type": "error",
                "error": f"turn budget exceeded at {total} tokens",
                "turn_status": "budget_exceeded",
            }

        while True:
            latest_plan_event: dict[str, Any] | None = None
            latest_verification_event: dict[str, Any] | None = None
            draft_segments: list[str] = []
            current_segment: list[str] = []
            turn_status = "ok"

            async for event in self.agent_manager.astream(
                current_turn.message,
                current_turn.history,
            ):
                event_type = event.get("type")
                if event_type == "done":
                    turn_status = event.get("turn_status") or event.get("status", "ok")
                    break

                if event_type == "token":
                    content = event.get("content")
                    if isinstance(content, str) and content:
                        current_segment.append(content)
                        output_tokens += _count_tokens(content)
                    yield event
                    if _budget_exceeded():
                        yield _budget_error_event()
                        return
                    continue

                if event_type == "new_response":
                    if current_segment:
                        draft_segments.append("".join(current_segment))
                        current_segment.clear()
                    yield event
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
                    yield helper_event

                if _budget_exceeded():
                    yield _budget_error_event()
                    return

            if current_segment:
                draft_segments.append("".join(current_segment))

            if _budget_exceeded():
                yield _budget_error_event()
                return

            should_retry = (
                not repair_attempted
                and turn_status == "ok"
                and self._verification_requires_repair(latest_verification_event)
                and latest_verification_event is not None
            )
            if not should_retry:
                yield {"type": "done", "turn_status": turn_status}
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
