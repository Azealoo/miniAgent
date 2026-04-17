from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry import EvidenceRequirement, ToolAccessScope

ToolPolicyStatus = Literal[
    "allow",
    "allow_with_warning",
    "blocked",
    "needs_approval",
]


@dataclass
class ToolPolicyExecutionContext:
    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    allowed_access_scope: ToolAccessScope = "execution"
    # Set of `tool_name` (or `f"{tool_name}:{run_id}"`) strings the user has
    # already approved this turn. The runtime is responsible for populating
    # this from the approval API; the policy layer only consults it.
    approved_tool_runs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ToolPolicyDecision:
    status: ToolPolicyStatus
    warnings: tuple[str, ...] = ()
    block_reason: str | None = None
    block_message: str | None = None
    approval_reason: str | None = None
    approval_message: str | None = None


@dataclass(frozen=True)
class ToolPolicyAnnotation:
    access_scope: ToolAccessScope
    evidence_requirement: EvidenceRequirement
    context_available: bool
    status: ToolPolicyStatus
    warnings: tuple[str, ...] = ()
    block_reason: str | None = None
    approval_reason: str | None = None
