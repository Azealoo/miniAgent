from __future__ import annotations

from typing import Literal, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

from config import get_verification_settings
from runtime.helper_agent_runner import (
    build_tool_catalog,
    extract_json_object,
    filter_tools_by_exposure,
    run_scoped_agent,
)
from runtime.model_factory import role_model_is_configured
from tools.contracts import execution_error_result, invalid_input_result, success_result


class VerificationCheck(BaseModel):
    name: str
    status: Literal["pass", "fail", "not_run"]
    note: str


class VerificationVerdict(BaseModel):
    verdict: Literal["pass", "repair_required", "fail"]
    summary: str
    checks: list[VerificationCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)


class VerificationAgentInput(BaseModel):
    task: str = Field(description="The original user task or objective.")
    draft_answer: str = Field(description="The current draft answer or execution result to verify.")
    plan: str | None = Field(
        default=None,
        description="Optional serialized plan or execution summary that the verifier should check against.",
    )


class VerificationAgentTool(BaseTool):
    name: str = "verification_agent"
    description: str = (
        "Use this helper agent after non-trivial tool use or drafting an answer. "
        "The verifier tries to break the current answer and returns a structured verdict: "
        "pass, repair_required, or fail."
    )
    args_schema: Type[BaseModel] = VerificationAgentInput
    response_format: str = "content_and_artifact"

    def _run(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("verification_agent is async-only")

    async def _arun(
        self,
        task: str,
        draft_answer: str,
        plan: str | None = None,
    ) -> tuple[str, dict]:
        from graph.agent import agent_manager

        if not role_model_is_configured("verifier"):
            return execution_error_result(
                self.name,
                "Verifier model is not configured. Set OPENAI_API_KEY or BIOAPEX_VERIFIER_API_KEY.",
                metadata={"role": "verifier"},
            )

        try:
            llm = agent_manager.verifier_llm
            tools = filter_tools_by_exposure(agent_manager.tools, "verifier")
            tool_catalog = build_tool_catalog(tools)
            verification_settings = get_verification_settings()
            retry_on_repair_required = bool(
                verification_settings.get("retry_on_repair_required", True)
            )
            user_prompt = (
                "Verify whether the draft answer satisfies the task and whether anything important is missing.\n\n"
                f"Task:\n{task.strip()}\n\n"
                f"Draft answer:\n{draft_answer.strip()}\n\n"
                "Available tools:\n"
                f"{tool_catalog}\n\n"
                "Return only JSON with this exact top-level shape:\n"
                '{'
                '"verdict": "pass" | "repair_required" | "fail",'
                '"summary": string,'
                '"checks": [{"name": string, "status": "pass" | "fail" | "not_run", "note": string}],'
                '"issues": string[],'
                '"repair_instructions": string[]'
                '}\n'
                "Verdict rubric:\n"
                '- Use "pass" when the draft is good enough to send as-is. Minor polish, optional extra citations, '
                "or small stylistic improvements should still pass.\n"
                '- Use "repair_required" only when the draft is mostly usable but needs a material fix before it '
                "should be sent to the user.\n"
                '- Use "fail" when the draft is fundamentally incorrect, unsafe, or does not satisfy the task.\n'
                "Do not use repair_required for optional improvements that would not materially change the user's "
                "outcome.\n"
            )
            if plan and plan.strip():
                user_prompt += f"\nPlan or execution context:\n{plan.strip()}\n"

            system_prompt = (
                "You are BioAPEX's verification specialist. Be skeptical, but calibrated: challenge the draft "
                "answer for material correctness, completeness, evidence, and safety issues without nitpicking "
                "trivial polish. If the answer is genuinely good enough for the task, return pass. "
                f"{'Repair-required verdicts trigger an automatic retry, so reserve them for substantive fixes. ' if retry_on_repair_required else ''}"
                "Use the tool catalog you were given, stay concise, and return only JSON."
            )

            run = await run_scoped_agent(
                llm=llm,
                tools=tools,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            verdict_payload = extract_json_object(run.response_text)
            verdict = VerificationVerdict.model_validate(verdict_payload)
        except ValidationError as exc:
            return invalid_input_result(
                self.name,
                f"Verifier produced an invalid verdict: {exc}",
                metadata={"raw_response": run.response_text if 'run' in locals() else None},
            )
        except Exception as exc:
            return execution_error_result(
                self.name,
                f"Verification execution failed: {exc}",
                metadata={"task": task},
            )

        summary = f"Verifier verdict: {verdict.verdict}. {verdict.summary}"
        return success_result(
            self.name,
            summary,
            structured_payload={
                "agent_type": "verification",
                "verification": verdict.model_dump(mode="json"),
                "tool_trace": list(run.tool_trace),
            },
            metadata={
                "verdict": verdict.verdict,
                "check_count": len(verdict.checks),
            },
            source_payload={"raw_response": run.response_text},
        )
