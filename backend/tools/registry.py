from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from .contracts import TOOL_RESULT_CONTRACT_VERSION
from .policy_types import (
    EvidenceRequirement,
    SandboxSpec,
    ToolAccessScope,
    ToolInterruptBehavior,
)

# Re-exports kept so existing imports like ``from tools.registry import
# ToolAccessScope`` continue to resolve.
__all__ = [
    "EvidenceRequirement",
    "SandboxSpec",
    "ToolAccessScope",
    "ToolClassificationError",
    "ToolInterruptBehavior",
    "ToolManifestEntry",
    "ToolPolicyMetadata",
    "ToolRegistry",
    "build_tool_manifest_entry",
    "build_tool_registry",
    "is_concurrency_safe_tier",
    "partition_manifests_by_risk",
    "validate_tool_classifications",
]


class ToolClassificationError(ValueError):
    """Raised when a tool manifest combines flags that contradict each other.

    Surfaced at boot so a misclassified tool never reaches the runtime
    dispatch path, where the read-only/destructive partition would silently
    do the wrong thing.
    """


@dataclass(frozen=True)
class ToolPolicyMetadata:
    access_scope: ToolAccessScope
    evidence_requirement: EvidenceRequirement = "none"
    output_contract_version: str | None = TOOL_RESULT_CONTRACT_VERSION
    read_only: bool = False
    destructive: bool = False
    concurrency_safe: bool = False
    planner_exposed: bool = False
    verifier_exposed: bool = False
    interrupt_behavior: ToolInterruptBehavior | None = None
    tool_validates_input: bool = False
    activity_summary_hint: str | None = None
    result_summary_hint: str | None = None
    requires_approval: bool = False
    sandbox: SandboxSpec | None = None


@dataclass(frozen=True)
class ToolManifestEntry:
    name: str
    description: str
    args_schema: dict[str, Any] | None
    response_format: str | None
    access_scope: ToolAccessScope
    evidence_requirement: EvidenceRequirement
    output_contract_version: str | None
    source_module: str
    read_only: bool = False
    destructive: bool = False
    concurrency_safe: bool = False
    planner_exposed: bool = False
    verifier_exposed: bool = False
    interrupt_behavior: ToolInterruptBehavior = "wait_for_completion"
    tool_validates_input: bool = False
    activity_summary_hint: str | None = None
    result_summary_hint: str | None = None
    requires_approval: bool = False
    sandbox: SandboxSpec | None = None


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[Any, ...]
    manifests: tuple[ToolManifestEntry, ...]


# Per-tool SandboxSpec declarations. Attached to manifest entries at
# build time so enforcement is uniform across every high-risk tool.
_HIGH_RISK_SANDBOX_SPECS: dict[str, SandboxSpec] = {
    "python_repl": SandboxSpec(
        allowed_file_roots=("memory/", "skills/", "knowledge/", "artifacts/", "storage/"),
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL", "PYTHONHASHSEED"),
        network_scope="none",
        max_wall_clock_seconds=60.0,
        max_output_bytes=5_000,
    ),
    "fetch_url": SandboxSpec(
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL"),
        network_scope="public",
        max_wall_clock_seconds=30.0,
        max_output_bytes=8_000,
    ),
    "http_json": SandboxSpec(
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL"),
        network_scope="public",
        max_wall_clock_seconds=45.0,
        max_output_bytes=100_000,
    ),
    "write_file": SandboxSpec(
        allowed_file_roots=("memory/", "skills/", "knowledge/"),
        allowed_env_vars=("PATH", "HOME", "LANG", "LC_ALL"),
        network_scope="none",
        max_wall_clock_seconds=15.0,
        max_output_bytes=20_000,
    ),
}


def _sandbox_for(tool_name: str) -> SandboxSpec | None:
    return _HIGH_RISK_SANDBOX_SPECS.get(tool_name)


_POLICY_OVERRIDES: dict[str, ToolPolicyMetadata] = {
    "terminal": ToolPolicyMetadata(
        access_scope="execution",
        requires_approval=True,
        activity_summary_hint="State the command goal and the target environment before running it.",
        result_summary_hint="Summarize the command outcome, key stdout or stderr signals, and any file or process side effects.",
    ),
    "python_repl": ToolPolicyMetadata(
        access_scope="execution",
        requires_approval=True,
        activity_summary_hint="State the code goal and the data or files it will touch before executing it.",
        result_summary_hint="Summarize the computed result, warnings, and any files or variables materially changed.",
    ),
    "fetch_url": ToolPolicyMetadata(access_scope="inspection", verifier_exposed=True),
    "http_json": ToolPolicyMetadata(access_scope="inspection", verifier_exposed=True),
    "ncbi_eutils": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
        verifier_exposed=True,
    ),
    "evidence_retrieval": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
        verifier_exposed=True,
    ),
    "evidence_review": ToolPolicyMetadata(
        access_scope="execution",
        evidence_requirement="required",
        verifier_exposed=True,
    ),
    "entity_grounding": ToolPolicyMetadata(
        access_scope="execution",
        evidence_requirement="recommended",
    ),
    "uniprot_api": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
        verifier_exposed=True,
    ),
    "ensembl_api": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
        verifier_exposed=True,
    ),
    "read_file": ToolPolicyMetadata(access_scope="inspection", verifier_exposed=True),
    "write_file": ToolPolicyMetadata(
        access_scope="execution",
        destructive=True,
        requires_approval=True,
        interrupt_behavior="avoid_interrupting",
        activity_summary_hint="State what file will be written and why before applying the change.",
        result_summary_hint="Summarize what changed on disk and name the affected file paths.",
    ),
    "search_knowledge_base": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
        verifier_exposed=True,
    ),
    "plan_agent": ToolPolicyMetadata(access_scope="inspection"),
    "verification_agent": ToolPolicyMetadata(access_scope="inspection"),
}

_READ_ONLY_TOOL_NAMES = {
    "fetch_url",
    "http_json",
    "ncbi_eutils",
    "evidence_retrieval",
    "uniprot_api",
    "ensembl_api",
    "read_file",
    "search_knowledge_base",
}

_CONCURRENCY_SAFE_TOOL_NAMES = {
    "fetch_url",
    "http_json",
    "ncbi_eutils",
    "uniprot_api",
    "ensembl_api",
    "read_file",
    "search_knowledge_base",
}


def _tool_args_schema(tool: Any) -> dict[str, Any] | None:
    schema = getattr(tool, "args_schema", None)
    if schema is None:
        return None
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    return None


def _default_interrupt_behavior(
    *,
    read_only: bool,
    destructive: bool,
) -> ToolInterruptBehavior:
    if read_only:
        return "restartable"
    if destructive:
        return "avoid_interrupting"
    return "wait_for_completion"


def _default_activity_summary_hint(
    *,
    read_only: bool,
    destructive: bool,
) -> str:
    if read_only:
        return "State what you are inspecting and name the target before using this tool."
    if destructive:
        return "Call out the side effect and target clearly before using this tool."
    return "State the action being taken and the main target before using this tool."


def _default_result_summary_hint(
    *,
    read_only: bool,
    destructive: bool,
) -> str:
    if read_only:
        return "Summarize the main finding, notable warnings, and any artifacts or paths worth opening next."
    if destructive:
        return "Summarize the side effect, changed targets, warnings, and any follow-up inspection path."
    return "Summarize the main outcome, notable warnings, and any artifacts or next inspection targets."


def build_tool_manifest_entry(tool: Any) -> ToolManifestEntry:
    policy = _POLICY_OVERRIDES.get(tool.name, ToolPolicyMetadata(access_scope="execution"))
    args_schema = _tool_args_schema(tool)
    read_only = policy.read_only or tool.name in _READ_ONLY_TOOL_NAMES
    destructive = policy.destructive
    concurrency_safe = policy.concurrency_safe or tool.name in _CONCURRENCY_SAFE_TOOL_NAMES
    planner_exposed = policy.planner_exposed or read_only
    verifier_exposed = policy.verifier_exposed or read_only
    interrupt_behavior = policy.interrupt_behavior or _default_interrupt_behavior(
        read_only=read_only,
        destructive=destructive,
    )
    tool_validates_input = policy.tool_validates_input or args_schema is not None
    activity_summary_hint = policy.activity_summary_hint or _default_activity_summary_hint(
        read_only=read_only,
        destructive=destructive,
    )
    result_summary_hint = policy.result_summary_hint or _default_result_summary_hint(
        read_only=read_only,
        destructive=destructive,
    )
    sandbox = policy.sandbox if policy.sandbox is not None else _sandbox_for(tool.name)
    return ToolManifestEntry(
        name=tool.name,
        description=getattr(tool, "description", ""),
        args_schema=args_schema,
        response_format=getattr(tool, "response_format", None),
        access_scope=policy.access_scope,
        evidence_requirement=policy.evidence_requirement,
        output_contract_version=policy.output_contract_version,
        source_module=tool.__class__.__module__,
        read_only=read_only,
        destructive=destructive,
        concurrency_safe=concurrency_safe,
        planner_exposed=planner_exposed,
        verifier_exposed=verifier_exposed,
        interrupt_behavior=interrupt_behavior,
        tool_validates_input=tool_validates_input,
        activity_summary_hint=activity_summary_hint,
        result_summary_hint=result_summary_hint,
        requires_approval=policy.requires_approval,
        sandbox=sandbox,
    )


def build_tool_registry(base_dir: Path, tools: list[Any]) -> ToolRegistry:
    manifests = tuple(build_tool_manifest_entry(tool) for tool in tools)
    return ToolRegistry(tools=tuple(tools), manifests=manifests)


def is_concurrency_safe_tier(manifest: ToolManifestEntry) -> bool:
    """True when the manifest is safe to dispatch alongside others via gather.

    The risk-tier rule is: read-only, concurrency-safe, and not destructive.
    Any tool that fails this check runs in the serial (destructive) tier.
    """
    return (
        manifest.read_only
        and manifest.concurrency_safe
        and not manifest.destructive
    )


def partition_manifests_by_risk(
    manifests: Iterable[ToolManifestEntry],
) -> tuple[tuple[ToolManifestEntry, ...], tuple[ToolManifestEntry, ...]]:
    """Split manifests into (concurrency_safe_tier, destructive_tier).

    Preserves input order within each tier so downstream dispatchers can
    line results up against the original call list.
    """
    parallel: list[ToolManifestEntry] = []
    serial: list[ToolManifestEntry] = []
    for manifest in manifests:
        if is_concurrency_safe_tier(manifest):
            parallel.append(manifest)
        else:
            serial.append(manifest)
    return tuple(parallel), tuple(serial)


def validate_tool_classifications(
    manifests: Iterable[ToolManifestEntry],
) -> None:
    """Refuse to accept a manifest set with contradictory risk flags.

    Enforced invariants:

    * ``destructive`` and ``read_only`` cannot both be true — a read-only
      tool by definition has no side effects to roll back.
    * ``destructive`` and ``concurrency_safe`` cannot both be true — the
      parallel tier must never contain a tool that mutates shared state.
    * ``concurrency_safe`` requires ``read_only`` — the batch dispatcher
      only gathers reads; a concurrency-safe-but-not-read-only manifest
      would be routed to parallel when it must not be.

    Called at app startup (``backend/app.py`` lifespan) so a miscategorised
    tool aborts boot rather than corrupting a live turn.
    """
    errors: list[str] = []
    for manifest in manifests:
        name = manifest.name
        if manifest.destructive and manifest.read_only:
            errors.append(
                f"{name!r}: cannot be both destructive and read_only"
            )
        if manifest.destructive and manifest.concurrency_safe:
            errors.append(
                f"{name!r}: cannot be both destructive and concurrency_safe"
            )
        if manifest.concurrency_safe and not manifest.read_only:
            errors.append(
                f"{name!r}: concurrency_safe requires read_only=True"
            )
    if errors:
        raise ToolClassificationError(
            "Misclassified tool manifests detected:\n  - "
            + "\n  - ".join(errors)
        )
