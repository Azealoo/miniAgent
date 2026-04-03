from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .contracts import TOOL_RESULT_CONTRACT_VERSION

ToolAccessScope = Literal["inspection", "execution", "admin"]
EvidenceRequirement = Literal["none", "recommended", "required"]
ToolInterruptBehavior = Literal["restartable", "wait_for_completion", "avoid_interrupting"]


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


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[Any, ...]
    manifests: tuple[ToolManifestEntry, ...]


_POLICY_OVERRIDES: dict[str, ToolPolicyMetadata] = {
    "terminal": ToolPolicyMetadata(
        access_scope="execution",
        activity_summary_hint="State the command goal and the target environment before running it.",
        result_summary_hint="Summarize the command outcome, key stdout or stderr signals, and any file or process side effects.",
    ),
    "python_repl": ToolPolicyMetadata(
        access_scope="execution",
        activity_summary_hint="State the code goal and the data or files it will touch before executing it.",
        result_summary_hint="Summarize the computed result, warnings, and any files or variables materially changed.",
    ),
    "fetch_url": ToolPolicyMetadata(access_scope="inspection"),
    "http_json": ToolPolicyMetadata(access_scope="inspection"),
    "ncbi_eutils": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
    ),
    "evidence_retrieval": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
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
    ),
    "ensembl_api": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
    ),
    "read_file": ToolPolicyMetadata(access_scope="inspection"),
    "write_file": ToolPolicyMetadata(
        access_scope="execution",
        destructive=True,
        interrupt_behavior="avoid_interrupting",
        activity_summary_hint="State what file will be written and why before applying the change.",
        result_summary_hint="Summarize what changed on disk and name the affected file paths.",
    ),
    "search_knowledge_base": ToolPolicyMetadata(
        access_scope="inspection",
        evidence_requirement="recommended",
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
    )


def build_tool_registry(base_dir: Path, tools: list[Any]) -> ToolRegistry:
    manifests = tuple(build_tool_manifest_entry(tool) for tool in tools)
    return ToolRegistry(tools=tuple(tools), manifests=manifests)
