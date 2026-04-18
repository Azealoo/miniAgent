from __future__ import annotations

import ipaddress
import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import config

from .contracts import ToolResultEnvelope
from .policy_types import (
    SandboxSpec,
    ToolPolicyAnnotation,
    ToolPolicyDecision,
    ToolPolicyExecutionContext,
)
from .registry import ToolManifestEntry

_PATH_ARG_KEYS: frozenset[str] = frozenset(
    {"path", "file", "file_path", "filepath", "target", "output_path", "filename"}
)
_URL_ARG_KEYS: frozenset[str] = frozenset({"url"})

SANDBOX_BLOCK_REASONS: frozenset[str] = frozenset(
    {
        "sandbox_file_root_violation",
        "sandbox_network_scope_violation",
        "sandbox_wall_clock_exceeded",
    }
)

_TOOL_POLICY_CONTEXT: ContextVar[ToolPolicyExecutionContext | None] = ContextVar(
    "bioapex_tool_policy_context",
    default=None,
)


@contextmanager
def tool_policy_context(context: ToolPolicyExecutionContext):
    token: Token = _TOOL_POLICY_CONTEXT.set(context)
    try:
        yield context
    finally:
        _TOOL_POLICY_CONTEXT.reset(token)


def get_tool_policy_context() -> ToolPolicyExecutionContext | None:
    return _TOOL_POLICY_CONTEXT.get()


def evaluate_pre_tool_policy(
    manifest: ToolManifestEntry,
    context: ToolPolicyExecutionContext | None,
) -> ToolPolicyDecision:
    settings = config.get_tool_policy_settings()
    if not bool(settings.get("enabled", True)):
        return ToolPolicyDecision(status="allow")

    if context is None:
        if not bool(settings.get("allow_without_context", True)):
            return ToolPolicyDecision(
                status="blocked",
                block_reason="policy_context_missing",
                block_message="Runtime policy context is required before this tool can run.",
            )
        return ToolPolicyDecision(status="allow")

    warnings: list[str] = []

    if manifest.access_scope == "admin" and context.allowed_access_scope != "admin":
        return ToolPolicyDecision(
            status="blocked",
            block_reason="access_scope_violation",
            block_message="Admin-scoped tool execution is not allowed in this runtime context.",
        )

    if (
        manifest.access_scope == "execution"
        and context.allowed_access_scope not in {"execution", "admin"}
    ):
        return ToolPolicyDecision(
            status="blocked",
            block_reason="access_scope_violation",
            block_message="Execution-scoped tool execution is not allowed in this runtime context.",
        )

    if manifest.requires_approval and not _user_has_approved(manifest, context):
        return ToolPolicyDecision(
            status="needs_approval",
            approval_reason="requires_approval",
            approval_message=(
                f"Tool '{manifest.name}' is gated and needs human approval before it can run."
            ),
        )

    if warnings:
        return ToolPolicyDecision(status="allow_with_warning", warnings=tuple(warnings))

    return ToolPolicyDecision(status="allow")


def evaluate_sandbox_arguments(
    manifest: ToolManifestEntry,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> ToolPolicyDecision:
    """Pre-dispatch check that kwargs conform to the manifest's SandboxSpec.

    Only file-root (path-style args) and network scope (url-style args) are
    inspected here; wall-clock, env-var scoping, and output-byte caps are
    enforced around the dispatch itself by the wrapper.
    """

    sandbox = manifest.sandbox
    if sandbox is None:
        return ToolPolicyDecision(status="allow")

    if sandbox.allowed_file_roots:
        violation = _first_path_root_violation(kwargs, sandbox.allowed_file_roots)
        if violation is not None:
            arg_key, value = violation
            return ToolPolicyDecision(
                status="blocked",
                block_reason="sandbox_file_root_violation",
                block_message=(
                    f"Tool '{manifest.name}' path argument '{arg_key}'={value!r} is "
                    f"outside the sandbox-allowed roots {list(sandbox.allowed_file_roots)}."
                ),
            )

    if sandbox.network_scope != "any":
        violation = _first_network_violation(kwargs, sandbox)
        if violation is not None:
            arg_key, value, reason = violation
            return ToolPolicyDecision(
                status="blocked",
                block_reason="sandbox_network_scope_violation",
                block_message=(
                    f"Tool '{manifest.name}' URL argument '{arg_key}'={value!r} "
                    f"violates sandbox network scope '{sandbox.network_scope}': {reason}."
                ),
            )

    return ToolPolicyDecision(status="allow")


def _first_path_root_violation(
    kwargs: dict[str, Any],
    allowed_roots: tuple[str, ...],
) -> tuple[str, str] | None:
    normalized_roots = [
        root.rstrip("/") + "/" if not root.endswith("/") else root
        for root in allowed_roots
    ]
    for key, value in kwargs.items():
        if key not in _PATH_ARG_KEYS or not isinstance(value, str):
            continue
        candidate = value.strip().lstrip("/").removeprefix("./")
        if ".." in Path(candidate).parts:
            return key, value
        if not any(candidate.startswith(root) for root in normalized_roots):
            return key, value
    return None


def _first_network_violation(
    kwargs: dict[str, Any],
    sandbox: SandboxSpec,
) -> tuple[str, str, str] | None:
    for key, value in kwargs.items():
        if key not in _URL_ARG_KEYS or not isinstance(value, str) or not value.strip():
            continue
        if sandbox.network_scope == "none":
            return key, value, "network access is disabled"
        if sandbox.network_scope == "public":
            reason = _public_network_violation_reason(value, sandbox.allowed_hosts)
            if reason is not None:
                return key, value, reason
    return None


def _public_network_violation_reason(
    url: str, allowed_hosts: tuple[str, ...]
) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "URL is malformed"
    host = (parsed.hostname or "").lower()
    if not host:
        return "URL has no host"
    if allowed_hosts and host not in {h.lower() for h in allowed_hosts}:
        return f"host '{host}' is not in the sandbox allowed_hosts list"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None
    if addr.is_loopback or addr.is_link_local or addr.is_private:
        return f"host '{host}' resolves to a private/reserved IP range"
    return None


@contextmanager
def scoped_environment(allowed_env_vars: tuple[str, ...] | None) -> Iterator[None]:
    """Temporarily mask environment variables outside the allowlist.

    When `allowed_env_vars` is `None` the environment is untouched.
    Callers wrap dispatch so that even if the tool reads `os.environ`
    directly (e.g. python_repl), only whitelisted variables are visible.
    """

    if allowed_env_vars is None:
        yield
        return

    allowed = set(allowed_env_vars)
    removed: dict[str, str] = {}
    try:
        for key in list(os.environ.keys()):
            if key not in allowed:
                removed[key] = os.environ[key]
                del os.environ[key]
        yield
    finally:
        for key, value in removed.items():
            os.environ[key] = value


def _user_has_approved(
    manifest: ToolManifestEntry,
    context: ToolPolicyExecutionContext,
) -> bool:
    approved = context.approved_tool_runs
    if not approved:
        return False
    if manifest.name in approved:
        return True
    return False


def annotate_tool_result(
    manifest: ToolManifestEntry,
    result: ToolResultEnvelope,
    context: ToolPolicyExecutionContext | None,
    decision: ToolPolicyDecision,
) -> ToolResultEnvelope:
    settings = config.get_tool_policy_settings()
    warnings = list(result.warnings)
    for warning in decision.warnings:
        if warning not in warnings:
            warnings.append(warning)

    if (
        bool(settings.get("warn_on_missing_artifact_refs", True))
        and manifest.evidence_requirement != "none"
        and not result.artifact_refs
    ):
        artifact_warning = "artifact_refs_missing"
        if artifact_warning not in warnings:
            warnings.append(artifact_warning)

    annotation = ToolPolicyAnnotation(
        access_scope=manifest.access_scope,
        evidence_requirement=manifest.evidence_requirement,
        context_available=context is not None,
        status=decision.status,
        warnings=tuple(decision.warnings),
        block_reason=decision.block_reason,
        approval_reason=decision.approval_reason,
    )

    metadata = dict(result.metadata)
    metadata["policy"] = {
        "access_scope": annotation.access_scope,
        "evidence_requirement": annotation.evidence_requirement,
        "context_available": annotation.context_available,
        "status": annotation.status,
        "warnings": list(annotation.warnings),
        "block_reason": annotation.block_reason,
        "approval_reason": annotation.approval_reason,
    }
    metadata["contract"] = {
        "output_contract_version": manifest.output_contract_version,
        "read_only": manifest.read_only,
        "destructive": manifest.destructive,
        "concurrency_safe": manifest.concurrency_safe,
        "interrupt_behavior": manifest.interrupt_behavior,
        "tool_validates_input": manifest.tool_validates_input,
        "activity_summary_hint": manifest.activity_summary_hint,
        "result_summary_hint": manifest.result_summary_hint,
        "planner_exposed": manifest.planner_exposed,
        "verifier_exposed": manifest.verifier_exposed,
        "requires_approval": manifest.requires_approval,
    }

    result.warnings = warnings
    result.metadata = metadata
    return result
