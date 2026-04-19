from __future__ import annotations

from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

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
    resolve_session_stable_prefix,
    run_subagent,
)
from tools.contracts import execution_error_result, invalid_input_result, success_result


class PlanStep(BaseModel):
    step_id: str
    intent: str
    allowed_tools: list[str] = Field(default_factory=list)
    preferred_tool_order: list[str] = Field(default_factory=list)
    exit_criteria: str


class ExecutionPlan(BaseModel):
    goal: str
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    steps: list[PlanStep]
    success_criteria: list[str] = Field(default_factory=list)
    verification_checks: list[str] = Field(default_factory=list)


class PlanAgentInput(BaseModel):
    task: str = Field(description="The user task that needs an execution plan.")
    context: str | None = Field(
        default=None,
        description="Optional current execution context, findings, or constraints to help the planner.",
    )


class PlanAgentTool(BaseTool):
    name: str = "plan_agent"
    description: str = (
        "Use this helper agent before broad tool use on non-trivial tasks. "
        "The planner explores with read-only tools and returns a structured execution plan "
        "with ordered steps, tool guidance, success criteria, and verification checks."
    )
    args_schema: Type[BaseModel] = PlanAgentInput
    response_format: str = "content_and_artifact"

    def _run(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("plan_agent is async-only")

    async def _arun(self, task: str, context: str | None = None) -> tuple[str, dict]:
        from graph.agent import agent_manager

        if not role_model_is_configured("planner"):
            return execution_error_result(
                self.name,
                "Planner model is not configured. Set OPENAI_API_KEY or BIOAPEX_PLANNER_API_KEY.",
                metadata={"role": "planner"},
            )
        if agent_manager.base_dir is None:
            return execution_error_result(
                self.name,
                "Planner cannot run before AgentManager is initialized (base_dir missing).",
                metadata={"role": "planner"},
            )

        artifact = None
        try:
            llm = agent_manager.planner_llm
            tools = filter_tools_by_exposure(agent_manager.tools, "planner")
            tool_catalog = build_tool_catalog(tools)
            user_prompt = (
                "Design a BioAPEX execution plan for the following task.\n\n"
                f"Task:\n{task.strip()}\n\n"
                "Available tools:\n"
                f"{tool_catalog}\n\n"
                "Return only JSON with this exact top-level shape:\n"
                '{'
                '"goal": string,'
                '"assumptions": string[],'
                '"constraints": string[],'
                '"steps": [{"step_id": string, "intent": string, "allowed_tools": string[], "preferred_tool_order": string[], "exit_criteria": string}],'
                '"success_criteria": string[],'
                '"verification_checks": string[]'
                '}\n'
            )
            if context and context.strip():
                user_prompt += f"\nCurrent context:\n{context.strip()}\n"

            system_prompt = (
                "You are BioAPEX's planning specialist. Use only the tools you were given. "
                "Stay read-only unless the tool catalog explicitly says otherwise. "
                "Explore just enough to decide a sound execution order. "
                "Return only JSON. Prefer concrete step order and tool order over vague advice."
            )

            contract = SubAgentContract(
                name=self.name,
                system_prompt=system_prompt,
                tools_allowed=tuple(tools),
                max_steps=default_max_steps(),
                token_budget=default_token_budget(),
                stable_prefix=resolve_session_stable_prefix(),
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
                    f"Planner sub-agent exited with status {artifact.status}.",
                    metadata={
                        "subagent_status": artifact.status,
                        "subagent_artifact_path": artifact.relative_path,
                        "subagent_error": artifact.error,
                    },
                )
            plan_payload = extract_json_object(artifact.response_text)
            plan = ExecutionPlan.model_validate(plan_payload)
        except ValidationError as exc:
            return invalid_input_result(
                self.name,
                f"Planner produced an invalid execution plan: {exc}",
                metadata={
                    "raw_response": artifact.response_text if artifact is not None else None,
                    "subagent_artifact_path": artifact.relative_path if artifact is not None else None,
                },
            )
        except Exception as exc:
            return execution_error_result(
                self.name,
                f"Planner execution failed: {exc}",
                metadata={"task": task},
            )

        summary = f"Planner produced {len(plan.steps)} step(s) for: {plan.goal}"
        return success_result(
            self.name,
            summary,
            structured_payload={
                "agent_type": "plan",
                "plan": plan.model_dump(mode="json"),
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
                "step_count": len(plan.steps),
                "subagent_artifact_path": artifact.relative_path,
                "subagent_run_id": artifact.run_id,
            },
            source_payload={"raw_response": artifact.response_text},
        )
