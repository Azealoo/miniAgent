from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The canonical definitions for these access/evidence literals live here
# so that ``policy_types`` has no import dependency on ``registry``.
# ``registry`` re-exports them for callers that still reference the old
# location.
ToolAccessScope = Literal["inspection", "execution", "admin"]
EvidenceRequirement = Literal["none", "recommended", "required"]
ToolInterruptBehavior = Literal[
    "restartable", "wait_for_completion", "avoid_interrupting"
]

ToolPolicyStatus = Literal[
    "allow",
    "allow_with_warning",
    "blocked",
    "needs_approval",
]

# Network posture declared by a SandboxSpec.
# - "none"   → tool is not allowed to make network calls; any URL argument is blocked.
# - "public" → public internet only; tools are expected to reject loopback / private ranges.
# - "any"    → unrestricted; kept declarative for auditing, no wrapper-level gate.
SandboxNetworkScope = Literal["none", "public", "any"]


@dataclass(frozen=True)
class SandboxSpec:
    """Declarative, per-tool execution sandbox contract.

    The fields are intentionally narrow so the wrapper can enforce them
    uniformly before and after dispatch. Leave a field at its default to
    opt out of that dimension; the wrapper performs no check in that case.
    """

    # Relative roots (under the tool's base_dir) that file-style path
    # arguments must stay inside. Empty tuple = no pre-dispatch path check.
    allowed_file_roots: tuple[str, ...] = ()
    # Names of environment variables the wrapped tool is allowed to see
    # while executing. `None` means "do not scope" — the tool inherits the
    # full process environment. An empty tuple means "no env vars at all".
    allowed_env_vars: tuple[str, ...] | None = None
    network_scope: SandboxNetworkScope = "any"
    # Hostname allowlist when `network_scope="public"`; empty tuple means
    # rely on the tool's own SSRF filter without an explicit allowlist.
    allowed_hosts: tuple[str, ...] = ()
    # Hard cap on dispatch wall-clock. `None` disables the timeout.
    max_wall_clock_seconds: float | None = None
    # Hard cap on the serialized summary byte length. `None` disables.
    max_output_bytes: int | None = None


@dataclass(frozen=True)
class ActiveSkillSpec:
    """Snapshot of a routed skill's policy-relevant frontmatter.

    Carried on ``ToolPolicyExecutionContext.active_skills`` so the tool
    policy layer can enforce skill-scoped guardrails (notably the
    ``tools_allowed`` allowlist) for the duration of a turn.
    """

    name: str
    tools_allowed: tuple[str, ...] = ()
    planner_visible: bool = True
    verifier_visible: bool = True


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
    # Skills the router selected for this turn. When any active skill
    # declares a non-empty ``tools_allowed`` list, tool dispatch is
    # restricted to the union of those allowlists across active skills.
    active_skills: tuple[ActiveSkillSpec, ...] = ()


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
