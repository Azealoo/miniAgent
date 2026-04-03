from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token

import config

from .contracts import ToolResultEnvelope
from .policy_types import (
    ToolPolicyAnnotation,
    ToolPolicyDecision,
    ToolPolicyExecutionContext,
)
from .registry import ToolManifestEntry

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

    if warnings:
        return ToolPolicyDecision(status="allow_with_warning", warnings=tuple(warnings))

    return ToolPolicyDecision(status="allow")


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
    )

    metadata = dict(result.metadata)
    metadata["policy"] = {
        "access_scope": annotation.access_scope,
        "evidence_requirement": annotation.evidence_requirement,
        "context_available": annotation.context_available,
        "status": annotation.status,
        "warnings": list(annotation.warnings),
        "block_reason": annotation.block_reason,
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
    }

    result.warnings = warnings
    result.metadata = metadata
    return result
