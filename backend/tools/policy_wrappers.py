from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
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
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TRACE_DIR = Path(__file__).resolve().parents[1] / "storage" / "tool-traces"
_TRACE_DIR_ENV = "BIOAPEX_TOOL_TRACE_DIR"
_SENSITIVE_KW_KEYS = frozenset({"token", "api_key", "password", "authorization"})
_REDACTED_PATH_MARKER = "<redacted-path>"
_REDACTED_VALUE_MARKER = "<redacted>"
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


def _resolve_trace_dir() -> Path:
    override = os.environ.get(_TRACE_DIR_ENV)
    if override:
        return Path(override)
    return _DEFAULT_TRACE_DIR


def _redact_path_if_external(value: str) -> str:
    if not value or value[0] != "/":
        return value
    try:
        resolved = Path(value).resolve()
    except (OSError, ValueError):
        return value
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        return _REDACTED_PATH_MARKER
    return value


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_path_if_external(value)
    return value


def _redact_call_args(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    redacted_args = tuple(_redact_value(arg) for arg in args)
    redacted_kwargs: dict[str, Any] = {}
    for key, value in kwargs.items():
        if str(key).lower() in _SENSITIVE_KW_KEYS:
            redacted_kwargs[key] = _REDACTED_VALUE_MARKER
        else:
            redacted_kwargs[key] = _redact_value(value)
    return redacted_args, redacted_kwargs


def _truncate(text: str) -> str:
    if len(text) <= _MAX_LOGGED_ARG_CHARS:
        return text
    return text[:_MAX_LOGGED_ARG_CHARS] + "...[truncated]"


def _build_result_summary(envelope: ToolResultEnvelope) -> str:
    parts: list[str] = []
    summary = envelope.summary or ""
    if summary:
        parts.append(summary)
    if envelope.error is not None:
        parts.append(f"error[{envelope.error.code}]: {envelope.error.message}")
    combined = " | ".join(parts) if parts else "(no output)"
    return _truncate(combined)


def _emit_tool_trace(
    *,
    tool_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    envelope: ToolResultEnvelope,
    started_at: datetime,
    duration_ms: float,
) -> None:
    context = get_tool_policy_context()
    session_id = context.session_id if context else None
    turn_id = context.turn_id if context else None

    redacted_args, redacted_kwargs = _redact_call_args(args, kwargs)
    args_summary = _summarize_call_args(redacted_args, redacted_kwargs)

    error_payload: dict[str, Any] | None = None
    if envelope.error is not None:
        error_payload = {
            "code": envelope.error.code,
            "message": envelope.error.message,
            "retriable": envelope.error.retriable,
        }

    record = {
        "ts": started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "turn_id": turn_id,
        "tool_name": tool_name,
        "args_summary": args_summary,
        "result_summary": _build_result_summary(envelope),
        "duration_ms": round(duration_ms, 3),
        "error": error_payload,
    }

    filename = f"{session_id}.jsonl" if session_id else "_no_session.jsonl"
    try:
        trace_dir = _resolve_trace_dir()
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / filename
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - tracing must never break the tool path
        logger.warning(
            "Failed to write tool trace for %s (session=%s)",
            tool_name,
            session_id,
            exc_info=True,
        )


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
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
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
        duration_ms = (time.perf_counter() - t0) * 1000.0
        _emit_tool_trace(
            tool_name=self.name,
            args=args,
            kwargs=kwargs,
            envelope=annotated,
            started_at=started_at,
            duration_ms=duration_ms,
        )
        return annotated.summary, annotated.model_dump(mode="json")

    async def _arun(self, *args, **kwargs):  # type: ignore[override]
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
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
        duration_ms = (time.perf_counter() - t0) * 1000.0
        _emit_tool_trace(
            tool_name=self.name,
            args=args,
            kwargs=kwargs,
            envelope=annotated,
            started_at=started_at,
            duration_ms=duration_ms,
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
