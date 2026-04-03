from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field

from .contracts import ToolResultEnvelope, blocked_result, normalize_tool_output
from .policy import annotate_tool_result, evaluate_pre_tool_policy, get_tool_policy_context
from .registry import ToolManifestEntry, ToolRegistry


class PolicyWrappedTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    args_schema: Any = None
    response_format: str = "content_and_artifact"
    wrapped_tool: Any = Field(exclude=True)
    manifest: ToolManifestEntry = Field(exclude=True)

    def _normalize_raw_output(self, raw_output: Any) -> ToolResultEnvelope:
        if (
            isinstance(raw_output, tuple)
            and len(raw_output) == 2
            and isinstance(raw_output[0], str)
        ):
            summary, artifact = raw_output
            result = normalize_tool_output(self.name, artifact)
            if not result.summary:
                result.summary = summary
            return result

        return normalize_tool_output(self.name, raw_output)

    def _run(self, *args, **kwargs):  # type: ignore[override]
        decision = evaluate_pre_tool_policy(self.manifest, get_tool_policy_context())
        if decision.status == "blocked":
            raw_output = blocked_result(
                self.name,
                decision.block_message or "Blocked by BioAPEX runtime policy.",
                metadata={"policy_block_reason": decision.block_reason},
            )
        else:
            raw_output = self.wrapped_tool._run(*args, **kwargs)

        result = self._normalize_raw_output(raw_output)
        annotated = annotate_tool_result(
            self.manifest,
            result,
            get_tool_policy_context(),
            decision,
        )
        return annotated.summary, annotated.model_dump(mode="json")

    async def _arun(self, *args, **kwargs):  # type: ignore[override]
        decision = evaluate_pre_tool_policy(self.manifest, get_tool_policy_context())
        if decision.status == "blocked":
            raw_output = blocked_result(
                self.name,
                decision.block_message or "Blocked by BioAPEX runtime policy.",
                metadata={"policy_block_reason": decision.block_reason},
            )
        else:
            raw_output = await self.wrapped_tool._arun(*args, **kwargs)

        result = self._normalize_raw_output(raw_output)
        annotated = annotate_tool_result(
            self.manifest,
            result,
            get_tool_policy_context(),
            decision,
        )
        return annotated.summary, annotated.model_dump(mode="json")


def build_policy_wrapped_tools(registry: ToolRegistry) -> list[BaseTool]:
    wrapped_tools: list[BaseTool] = []
    for tool, manifest in zip(registry.tools, registry.manifests):
        wrapped_tools.append(
            PolicyWrappedTool(
                name=tool.name,
                description=getattr(tool, "description", ""),
                args_schema=getattr(tool, "args_schema", None),
                response_format="content_and_artifact",
                wrapped_tool=tool,
                manifest=manifest,
            )
        )
    return wrapped_tools
