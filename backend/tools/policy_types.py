from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .registry import EvidenceRequirement, ToolAccessScope

ToolPolicyStatus = Literal["allow", "allow_with_warning", "blocked"]


@dataclass
class ToolPolicyExecutionContext:
    session_id: str | None = None
    request_id: str | None = None
    allowed_access_scope: ToolAccessScope = "execution"


@dataclass(frozen=True)
class ToolPolicyDecision:
    status: ToolPolicyStatus
    warnings: tuple[str, ...] = ()
    block_reason: str | None = None
    block_message: str | None = None


@dataclass(frozen=True)
class ToolPolicyAnnotation:
    access_scope: ToolAccessScope
    evidence_requirement: EvidenceRequirement
    context_available: bool
    status: ToolPolicyStatus
    warnings: tuple[str, ...] = ()
    block_reason: str | None = None
