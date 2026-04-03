from __future__ import annotations

from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError

from runtime.helper_agent_runner import (
    build_tool_catalog,
    extract_json_object,
    filter_tools_by_exposure,
    run_scoped_agent,
)
from runtime.model_factory import role_model_is_configured
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

            run = await run_scoped_agent(
                llm=llm,
                tools=tools,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            plan_payload = extract_json_object(run.response_text)
            plan = ExecutionPlan.model_validate(plan_payload)
        except ValidationError as exc:
            return invalid_input_result(
                self.name,
                f"Planner produced an invalid execution plan: {exc}",
                metadata={"raw_response": run.response_text if 'run' in locals() else None},
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
                "tool_trace": list(run.tool_trace),
            },
            metadata={"step_count": len(plan.steps)},
            source_payload={"raw_response": run.response_text},
        )
