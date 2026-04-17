from __future__ import annotations

from typing import Literal, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

from config import get_verification_settings
from runtime.helper_agent_runner import (
    build_tool_catalog,
    extract_json_object,
    filter_tools_by_exposure,
)
from runtime.model_factory import role_model_is_configured
from runtime.subagent import (
    SubAgentContract,
    default_max_steps,
    default_token_budget,
    run_subagent,
)
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
        if agent_manager.base_dir is None:
            return execution_error_result(
                self.name,
                "Verifier cannot run before AgentManager is initialized (base_dir missing).",
                metadata={"role": "verifier"},
            )

        artifact = None
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

            contract = SubAgentContract(
                name=self.name,
                system_prompt=system_prompt,
                tools_allowed=tuple(tools),
                max_steps=default_max_steps(),
                token_budget=default_token_budget(),
            )
            artifact = await run_subagent(
                contract,
                llm=llm,
                user_prompt=user_prompt,
                base_dir=agent_manager.base_dir,
            )
            if artifact.status != "ok":
                return execution_error_result(
                    self.name,
                    f"Verifier sub-agent exited with status {artifact.status}.",
                    metadata={
                        "subagent_status": artifact.status,
                        "subagent_artifact_path": artifact.relative_path,
                        "subagent_error": artifact.error,
                    },
                )
            verdict_payload = extract_json_object(artifact.response_text)
            verdict = VerificationVerdict.model_validate(verdict_payload)
        except ValidationError as exc:
            return invalid_input_result(
                self.name,
                f"Verifier produced an invalid verdict: {exc}",
                metadata={
                    "raw_response": artifact.response_text if artifact is not None else None,
                    "subagent_artifact_path": artifact.relative_path if artifact is not None else None,
                },
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
                "tool_trace": list(artifact.tool_trace),
                "subagent_run": {
                    "run_id": artifact.run_id,
                    "status": artifact.status,
                    "artifact_path": artifact.relative_path,
                    "tokens_used": artifact.tokens_used,
                    "steps_used": artifact.steps_used,
                },
            },
            metadata={
                "verdict": verdict.verdict,
                "check_count": len(verdict.checks),
                "subagent_artifact_path": artifact.relative_path,
                "subagent_run_id": artifact.run_id,
            },
            source_payload={"raw_response": artifact.response_text},
        )
