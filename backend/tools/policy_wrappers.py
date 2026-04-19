from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import ConfigDict, Field

from config import (
    get_tool_wallclock_default_s,
    get_tool_wallclock_override_s,
)
from runtime import hooks as runtime_hooks

from .contracts import (
    ToolResultEnvelope,
    blocked_result,
    execution_error_result,
    needs_approval_result,
    normalize_tool_output,
    retriable_error_result,
)
from .policy import (
    annotate_tool_result,
    evaluate_pre_tool_policy,
    evaluate_sandbox_arguments,
    get_tool_policy_context,
    scoped_environment,
)
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


def _tool_trace_post_hook(
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
) -> runtime_hooks.PostToolDecision | None:
    """Registered post-tool hook that writes the JSONL trace line.

    Pulls timing out of the invocation context the wrapper sets around the
    hook chain. Returns ``None`` (≡ ``allow``) because tracing is a pure
    side effect that never modifies the tool result.
    """

    if not isinstance(result, ToolResultEnvelope):
        return None

    invocation = runtime_hooks.get_invocation_context()
    policy_context = get_tool_policy_context()
    session_id = (invocation.session_id if invocation else None) or (
        policy_context.session_id if policy_context else None
    )
    turn_id = (invocation.turn_id if invocation else None) or (
        policy_context.turn_id if policy_context else None
    )
    started_at = (
        invocation.started_at if invocation and invocation.started_at else datetime.now(timezone.utc)
    )
    duration_ms = float(invocation.duration_ms) if invocation and invocation.duration_ms is not None else 0.0

    redacted_args, redacted_kwargs = _redact_call_args(args, kwargs)
    args_summary = _summarize_call_args(redacted_args, redacted_kwargs)

    error_payload: dict[str, Any] | None = None
    if result.error is not None:
        error_payload = {
            "code": result.error.code,
            "message": result.error.message,
            "retriable": result.error.retriable,
        }

    record = {
        "ts": started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "turn_id": turn_id,
        "tool_name": name,
        "args_summary": args_summary,
        "result_summary": _build_result_summary(result),
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
            name,
            session_id,
            exc_info=True,
        )
    return None


runtime_hooks.register_post("tool_trace_jsonl", _tool_trace_post_hook)


class _SandboxWallClockExceeded(Exception):
    """Raised internally when dispatch runs past the sandbox's wall-clock cap."""

    def __init__(self, max_wall_clock: float) -> None:
        super().__init__(
            f"sandbox wall-clock budget of {max_wall_clock:.1f}s was exceeded"
        )
        self.max_wall_clock = max_wall_clock


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

    def _dispatch_sync_with_wall_clock(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        max_wall_clock: float | None,
    ) -> Any:
        if max_wall_clock is None or max_wall_clock <= 0:
            return self.wrapped_tool._run(*args, **kwargs)

        result_holder: dict[str, Any] = {}

        def _target() -> None:
            try:
                result_holder["value"] = self.wrapped_tool._run(*args, **kwargs)
            except BaseException as exc:  # captured and rethrown from the caller thread
                result_holder["exc"] = exc

        thread = threading.Thread(
            target=_target,
            name=f"sandbox-{self.name}",
            daemon=True,
        )
        thread.start()
        thread.join(timeout=max_wall_clock)
        if thread.is_alive():
            raise _SandboxWallClockExceeded(max_wall_clock)
        if "exc" in result_holder:
            raise result_holder["exc"]
        return result_holder.get("value")

    async def _dispatch_async_with_wall_clock(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        max_wall_clock: float | None,
    ) -> Any:
        if max_wall_clock is None or max_wall_clock <= 0:
            return await self.wrapped_tool._arun(*args, **kwargs)
        try:
            return await asyncio.wait_for(
                self.wrapped_tool._arun(*args, **kwargs),
                timeout=max_wall_clock,
            )
        except asyncio.TimeoutError as exc:
            raise _SandboxWallClockExceeded(max_wall_clock) from exc

    def _apply_output_byte_cap(self, envelope: ToolResultEnvelope) -> ToolResultEnvelope:
        sandbox = self.manifest.sandbox
        if sandbox is None or sandbox.max_output_bytes is None:
            return envelope
        max_bytes = sandbox.max_output_bytes
        if max_bytes <= 0:
            return envelope
        summary = envelope.summary or ""
        encoded = summary.encode("utf-8")
        if len(encoded) <= max_bytes:
            return envelope
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        marker = "\n...[sandbox output truncated]"
        envelope.summary = truncated + marker
        if "sandbox_output_truncated" not in envelope.warnings:
            envelope.warnings.append("sandbox_output_truncated")
        metadata = dict(envelope.metadata)
        metadata.setdefault("sandbox", {})
        if isinstance(metadata["sandbox"], dict):
            metadata["sandbox"].update(
                {
                    "output_truncated": True,
                    "max_output_bytes": max_bytes,
                    "summary_bytes_before_cap": len(encoded),
                }
            )
        envelope.metadata = metadata
        return envelope

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

    def _resolve_pre_dispatch_decision(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ):
        decision = evaluate_pre_tool_policy(self.manifest, get_tool_policy_context())
        if decision.status in ("blocked", "needs_approval"):
            return decision
        sandbox_decision = evaluate_sandbox_arguments(self.manifest, args, kwargs)
        if sandbox_decision.status != "allow":
            return sandbox_decision
        return decision

    def _short_circuit_raw_output(self, decision) -> Any | None:
        if decision.status == "blocked":
            return blocked_result(
                self.name,
                decision.block_message or "Blocked by BioAPEX runtime policy.",
                metadata={"policy_block_reason": decision.block_reason},
            )
        if decision.status == "needs_approval":
            return needs_approval_result(
                self.name,
                decision.approval_message
                or f"Tool '{self.name}' requires human approval before it can run.",
                metadata={
                    "policy_approval_reason": decision.approval_reason,
                    "requires_approval": True,
                },
            )
        return None

    def _sandbox_wall_clock(self) -> float | None:
        """Resolve the per-tool wall-clock budget actually enforced at dispatch.

        Resolution order (first hit wins, ``None`` means "no cap"):
          1. ``tool_wallclock.overrides[<tool_name>]`` from runtime config.
             A configured value of ``0`` disables the cap explicitly.
          2. ``SandboxSpec.max_wall_clock_seconds`` declared on the tool
             manifest (today set in ``tools/registry.py`` for high-risk tools).
          3. ``tool_wallclock.default_seconds`` from runtime config as the
             project-wide floor for tools without a sandbox declaration.
        """
        override = get_tool_wallclock_override_s(self.name)
        if override is not None:
            return override if override > 0 else None
        sandbox = self.manifest.sandbox
        if sandbox is not None and sandbox.max_wall_clock_seconds is not None:
            return sandbox.max_wall_clock_seconds
        default = get_tool_wallclock_default_s()
        return default if default > 0 else None

    def _sandbox_env_allowlist(self) -> tuple[str, ...] | None:
        sandbox = self.manifest.sandbox
        if sandbox is None:
            return None
        return sandbox.allowed_env_vars

    def _handle_wall_clock_exceeded(
        self,
        exc: _SandboxWallClockExceeded,
    ) -> Any:
        return blocked_result(
            self.name,
            (
                f"Tool '{self.name}' exceeded the sandbox wall-clock budget of "
                f"{exc.max_wall_clock:.1f}s and was stopped."
            ),
            metadata={
                "policy_block_reason": "sandbox_wall_clock_exceeded",
                "sandbox_wall_clock_seconds": exc.max_wall_clock,
            },
        )

    def _apply_pre_tool_hooks(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[tuple[Any, ...], dict[str, Any], Any | None]:
        """Run registered pre-tool hooks.

        Returns ``(args, kwargs, short_circuit_raw_output)``. The first two
        carry any modify-overrides; the third is non-``None`` when a hook
        returned ``deny`` or ``ask`` and the wrapper should skip dispatch.
        """

        decision = runtime_hooks.pre_tool(self.name, args, kwargs)
        if decision.status == "deny":
            message = decision.message or f"Tool '{self.name}' was denied by a runtime hook."
            return args, kwargs, blocked_result(
                self.name,
                message,
                metadata={
                    "hook_block_reason": decision.reason or "runtime_hook_deny",
                },
            )
        if decision.status == "ask":
            message = (
                decision.message
                or f"Tool '{self.name}' requires human approval before it can run."
            )
            return args, kwargs, needs_approval_result(
                self.name,
                message,
                metadata={
                    "hook_approval_reason": decision.reason or "runtime_hook_ask",
                    "requires_approval": True,
                },
            )
        if decision.status == "modify":
            new_args = decision.args if decision.args is not None else args
            new_kwargs = decision.kwargs if decision.kwargs is not None else kwargs
            return new_args, new_kwargs, None
        return args, kwargs, None

    def _apply_post_tool_hooks(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        envelope: ToolResultEnvelope,
    ) -> ToolResultEnvelope:
        """Run registered post-tool hooks, possibly replacing the envelope."""

        decision = runtime_hooks.post_tool(self.name, args, kwargs, envelope)
        if decision.status == "deny":
            message = decision.message or f"Tool '{self.name}' output was denied by a runtime hook."
            summary, payload = blocked_result(
                self.name,
                message,
                metadata={
                    "hook_block_reason": decision.reason or "runtime_hook_post_deny",
                },
            )
            del summary
            return ToolResultEnvelope.model_validate(payload)
        if decision.status in {"modify", "ask"} and isinstance(
            decision.result, ToolResultEnvelope
        ):
            return decision.result
        return envelope

    def _build_invocation_context(
        self,
        *,
        started_at: datetime,
        duration_ms: float | None,
    ) -> runtime_hooks.HookInvocationContext:
        policy_context = get_tool_policy_context()
        return runtime_hooks.HookInvocationContext(
            tool_name=self.name,
            started_at=started_at,
            duration_ms=duration_ms,
            session_id=policy_context.session_id if policy_context else None,
            turn_id=policy_context.turn_id if policy_context else None,
            request_id=policy_context.request_id if policy_context else None,
        )

    def _run(self, *args, **kwargs):  # type: ignore[override]
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        decision = self._resolve_pre_dispatch_decision(args, kwargs)
        raw_output = self._short_circuit_raw_output(decision)
        if raw_output is None:
            with runtime_hooks.hook_invocation_context(
                self._build_invocation_context(started_at=started_at, duration_ms=None)
            ):
                args, kwargs, hook_raw = self._apply_pre_tool_hooks(args, kwargs)
            if hook_raw is not None:
                raw_output = hook_raw
        if raw_output is None:
            try:
                with scoped_environment(self._sandbox_env_allowlist()):
                    raw_output = self._dispatch_sync_with_wall_clock(
                        args, kwargs, self._sandbox_wall_clock()
                    )
            except _SandboxWallClockExceeded as exc:
                raw_output = self._handle_wall_clock_exceeded(exc)
            except Exception as exc:
                raw_output = self._handle_tool_exception(exc, args, kwargs)

        result = self._normalize_raw_output(raw_output)
        result = self._apply_output_byte_cap(result)
        annotated = annotate_tool_result(
            self.manifest,
            result,
            get_tool_policy_context(),
            decision,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0
        with runtime_hooks.hook_invocation_context(
            self._build_invocation_context(started_at=started_at, duration_ms=duration_ms)
        ):
            annotated = self._apply_post_tool_hooks(args, kwargs, annotated)
        return annotated.summary, annotated.model_dump(mode="json")

    async def _arun(self, *args, **kwargs):  # type: ignore[override]
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        decision = self._resolve_pre_dispatch_decision(args, kwargs)
        raw_output = self._short_circuit_raw_output(decision)
        if raw_output is None:
            with runtime_hooks.hook_invocation_context(
                self._build_invocation_context(started_at=started_at, duration_ms=None)
            ):
                args, kwargs, hook_raw = self._apply_pre_tool_hooks(args, kwargs)
            if hook_raw is not None:
                raw_output = hook_raw
        if raw_output is None:
            try:
                with scoped_environment(self._sandbox_env_allowlist()):
                    raw_output = await self._dispatch_async_with_wall_clock(
                        args, kwargs, self._sandbox_wall_clock()
                    )
            except _SandboxWallClockExceeded as exc:
                raw_output = self._handle_wall_clock_exceeded(exc)
            except asyncio.CancelledError:
                # Client-disconnect cancellation must reach in-flight async
                # tools at their next await point and bubble back up so the
                # whole turn unwinds. Converting it to an error envelope
                # would let the agent loop keep running on a half-cancelled
                # task tree.
                raise
            except Exception as exc:
                raw_output = self._handle_tool_exception(exc, args, kwargs)

        result = self._normalize_raw_output(raw_output)
        result = self._apply_output_byte_cap(result)
        annotated = annotate_tool_result(
            self.manifest,
            result,
            get_tool_policy_context(),
            decision,
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0
        with runtime_hooks.hook_invocation_context(
            self._build_invocation_context(started_at=started_at, duration_ms=duration_ms)
        ):
            annotated = self._apply_post_tool_hooks(args, kwargs, annotated)
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
