from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field

from .contracts import (
    ToolResultEnvelope,
    blocked_result,
    execution_error_result,
    normalize_tool_output,
    retriable_error_result,
)
from .policy import annotate_tool_result, evaluate_pre_tool_policy, get_tool_policy_context
from .registry import ToolManifestEntry, ToolRegistry

logger = logging.getLogger(__name__)

_MAX_LOGGED_ARG_CHARS = 500
_RETRIABLE_EXCEPTION_TYPES: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
)
_RETRIABLE_MESSAGE_TOKENS = (
    "timeout",
    "timed out",
    "temporar",
    "connection",
    "rate limit",
    " 429",
    " 500",
    " 502",
    " 503",
    " 504",
)


def _summarize_call_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    try:
        rendered = repr({"args": args, "kwargs": kwargs})
    except Exception:  # pragma: no cover - defensive
        rendered = f"<unrepresentable args: {type(args).__name__}/{type(kwargs).__name__}>"
    if len(rendered) > _MAX_LOGGED_ARG_CHARS:
        rendered = rendered[:_MAX_LOGGED_ARG_CHARS] + "...[truncated]"
    return rendered


def _is_retriable_exception(exc: BaseException) -> bool:
    if isinstance(exc, _RETRIABLE_EXCEPTION_TYPES):
        return True
    message = str(exc).lower()
    return any(token in message for token in _RETRIABLE_MESSAGE_TOKENS)


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

    def _handle_tool_exception(
        self,
        exc: BaseException,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        arg_summary = _summarize_call_args(args, kwargs)
        logger.exception(
            "Tool %s raised %s during execution",
            self.name,
            type(exc).__name__,
            extra={
                "tool_name": self.name,
                "tool_args": arg_summary,
                "exception_type": type(exc).__name__,
            },
        )
        exception_message = str(exc).strip()
        envelope_message = (
            f"{type(exc).__name__}: {exception_message}"
            if exception_message
            else f"Tool {self.name} raised {type(exc).__name__}."
        )
        metadata = {
            "exception_type": type(exc).__name__,
            "exception_source": "tool_execution",
        }
        if _is_retriable_exception(exc):
            return retriable_error_result(self.name, envelope_message, metadata=metadata)
        return execution_error_result(self.name, envelope_message, metadata=metadata)

    def _run(self, *args, **kwargs):  # type: ignore[override]
        decision = evaluate_pre_tool_policy(self.manifest, get_tool_policy_context())
        if decision.status == "blocked":
            raw_output = blocked_result(
                self.name,
                decision.block_message or "Blocked by BioAPEX runtime policy.",
                metadata={"policy_block_reason": decision.block_reason},
            )
        else:
            try:
                raw_output = self.wrapped_tool._run(*args, **kwargs)
            except Exception as exc:
                raw_output = self._handle_tool_exception(exc, args, kwargs)

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
            try:
                raw_output = await self.wrapped_tool._arun(*args, **kwargs)
            except Exception as exc:
                raw_output = self._handle_tool_exception(exc, args, kwargs)

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
