"""Deterministic compliance preflight before biology-sensitive execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from artifacts.naming import build_content_hash_manifest, stable_artifact_name
from artifacts.schemas import (
    SCHEMA_PACK_VERSION,
    ComplianceApprovalRecord,
    ComplianceApprovalScope,
    ComplianceDecisionSource,
    ComplianceDisposition,
    ComplianceReport,
    ComplianceRuleHit,
    ComplianceRuntimeState,
    ComplianceSeverity,
    RiskCategory,
    normalize_identifier,
)
from artifacts import prepare_run_directory
from compliance.audit import append_compliance_audit_record
from tools.contracts import ToolResultError, artifact_ref, build_tool_result, success_result

COMPLIANCE_PREFLIGHT_TOOL_NAME = "compliance_preflight"
COMPLIANCE_WORKFLOW_NAME = "compliance-preflight"
_RULESET_PATH = Path(__file__).resolve().parent / "rules" / "mvp_rules.yaml"
_ACTION_RANK: dict[ComplianceDisposition, int] = {
    "allow": 0,
    "allow_with_warning": 1,
    "require_approval": 2,
    "block": 3,
}
_SEVERITY_RANK: dict[ComplianceSeverity, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}
_MAX_TRIGGER_TEXT = 160
_DEFAULT_APPROVAL_SCOPE: ComplianceApprovalScope = "message"


class CompliancePreflightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    attached_identifiers: list[str] = Field(default_factory=list)
    selected_workflow: str | None = None
    session_id: str | None = None
    approval_override: "ComplianceOverrideInput | None" = None

    @field_validator("user_message")
    @classmethod
    def _validate_user_message(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("user_message must not be empty.")
        return text

    @field_validator("attached_identifiers")
    @classmethod
    def _validate_attached_identifiers(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            normalized = item.strip()
            if normalized:
                cleaned.append(normalized)
        return cleaned

    @field_validator("selected_workflow", "session_id")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ComplianceOverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str
    approval_scope: ComplianceApprovalScope = _DEFAULT_APPROVAL_SCOPE
    rationale: str | None = None

    @field_validator("approved_by")
    @classmethod
    def _validate_approved_by(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("approved_by must not be empty.")
        return cleaned

    @field_validator("approval_scope")
    @classmethod
    def _validate_approval_scope(cls, value: ComplianceApprovalScope) -> ComplianceApprovalScope:
        if value != _DEFAULT_APPROVAL_SCOPE:
            raise ValueError("Only message-scoped compliance overrides are currently supported.")
        return value

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


CompliancePreflightInput.model_rebuild()


class ComplianceRuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    category: RiskCategory
    severity: ComplianceSeverity
    recommended_action: ComplianceDisposition
    sources: list[Literal["message", "attachments", "workflow"]] = Field(min_length=1)
    patterns: list[str] = Field(min_length=1)

    @field_validator("rule_id")
    @classmethod
    def _validate_rule_id(cls, value: str) -> str:
        return normalize_identifier(value)


class ComplianceRuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    rules: list[ComplianceRuleDefinition]


@dataclass(frozen=True)
class CompliancePreflightResult:
    report: ComplianceReport
    artifact_path: Path
    artifact_relpath: str
    tool_input: str
    tool_summary: str
    tool_result: dict
    warning_text: str | None
    response_text: str | None
    should_continue: bool


@dataclass(frozen=True)
class ComplianceDecision:
    runtime_state: ComplianceRuntimeState
    decision_source: ComplianceDecisionSource
    preflight_disposition: ComplianceDisposition
    final_disposition: ComplianceDisposition
    human_approval_required: bool
    approval_scope: ComplianceApprovalScope | None
    approval: ComplianceApprovalRecord | None


def run_compliance_preflight(
    base_dir: Path | str,
    payload: CompliancePreflightInput,
) -> CompliancePreflightResult:
    base_path = Path(base_dir).resolve()
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)

    try:
        ruleset = _load_ruleset()
        hits = _evaluate_rules(ruleset, payload)
        preflight_disposition = _choose_disposition(hits)
        dominant_hit = _dominant_hit(hits)
        risk_category: RiskCategory = dominant_hit.category if dominant_hit else "none"
        decision = _resolve_decision(preflight_disposition, payload, timestamp)
        layout = prepare_run_directory(base_path, COMPLIANCE_WORKFLOW_NAME, created_at=timestamp)
        report = _build_report(
            layout.run_id,
            layout.created_at,
            payload,
            hits,
            risk_category,
            decision,
        )
        artifact_path, artifact_relpath = _persist_report(layout, report)
        audit_log_path = append_compliance_audit_record(base_path, report, artifact_relpath)
        audit_log_relpath = audit_log_path.relative_to(base_path).as_posix()
        tool_summary = _build_tool_summary(report)
        warning_text = _build_warning_text(report)
        response_text = _build_response_text(report)
    except Exception as exc:
        layout = prepare_run_directory(base_path, COMPLIANCE_WORKFLOW_NAME, created_at=timestamp)
        decision = ComplianceDecision(
            runtime_state="approval_required",
            decision_source="safe_fallback",
            preflight_disposition="require_approval",
            final_disposition="require_approval",
            human_approval_required=True,
            approval_scope=_DEFAULT_APPROVAL_SCOPE,
            approval=None,
        )
        report = _build_report(
            layout.run_id,
            layout.created_at,
            payload,
            [],
            "none",
            decision,
        )
        artifact_path, artifact_relpath = _persist_report(layout, report)
        audit_log_path = append_compliance_audit_record(base_path, report, artifact_relpath)
        audit_log_relpath = audit_log_path.relative_to(base_path).as_posix()
        tool_summary = "Compliance preflight failed safely and requires approval before execution can continue."
        warning_text = None
        response_text = (
            "Compliance preflight could not complete deterministically, so this request "
            "was stopped pending review. No biology-sensitive work was executed.\n\n"
            f"Internal preflight error: {exc}"
        )

    tool_input = _build_tool_input(payload)
    tool_contract_kwargs = {
        "structured_payload": {
            "report": report.model_dump(mode="json"),
            "artifact_path": artifact_relpath,
            "audit_log_path": audit_log_relpath,
            "inspected_inputs": {
                "user_message": payload.user_message,
                "attached_identifiers": payload.attached_identifiers,
                "selected_workflow": payload.selected_workflow,
                "session_id": payload.session_id,
            },
        },
        "artifact_refs": [
            artifact_ref(
                path=str(artifact_path),
                label="compliance_report",
                artifact_type="compliance_report",
                identifier=report.id,
            )
        ],
        "warnings": _result_warnings(report),
        "metadata": {
            "runtime_state": report.runtime_state,
            "preflight_disposition": report.preflight_disposition,
            "final_disposition": report.final_disposition,
            "decision_source": report.decision_source,
            "risk_category": report.risk_category,
            "rule_hits": len(report.triggered_rules),
            "artifact_path": artifact_relpath,
            "audit_log_path": audit_log_relpath,
            "approval_scope": report.approval_scope,
            "approved_by": report.approval.approved_by if report.approval else None,
        },
    }

    if report.final_disposition in {"require_approval", "block"}:
        summary, tool_result = build_tool_result(
            COMPLIANCE_PREFLIGHT_TOOL_NAME,
            tool_summary,
            outcome="blocked",
            error=ToolResultError(
                code="blocked",
                message=tool_summary,
                retriable=False,
            ),
            **tool_contract_kwargs,
        )
    else:
        summary, tool_result = success_result(
            COMPLIANCE_PREFLIGHT_TOOL_NAME,
            tool_summary,
            **tool_contract_kwargs,
        )

    return CompliancePreflightResult(
        report=report,
        artifact_path=artifact_path,
        artifact_relpath=artifact_relpath,
        tool_input=tool_input,
        tool_summary=summary,
        tool_result=tool_result,
        warning_text=warning_text,
        response_text=response_text,
        should_continue=report.final_disposition in {"allow", "allow_with_warning"},
    )


def _load_ruleset() -> ComplianceRuleSet:
    payload = yaml.safe_load(_RULESET_PATH.read_text(encoding="utf-8"))
    return ComplianceRuleSet.model_validate(payload)


def _evaluate_rules(
    ruleset: ComplianceRuleSet,
    payload: CompliancePreflightInput,
) -> list[ComplianceRuleHit]:
    inspected_sources = {
        "message": [payload.user_message],
        "attachments": payload.attached_identifiers,
        "workflow": [payload.selected_workflow] if payload.selected_workflow else [],
    }

    hits: list[ComplianceRuleHit] = []
    for rule in ruleset.rules:
        for source in rule.sources:
            for value in inspected_sources[source]:
                match_text = _match_rule(rule, value)
                if match_text is None:
                    continue
                hits.append(
                    ComplianceRuleHit(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        trigger_text=_format_trigger_text(source, value, match_text),
                        severity=rule.severity,
                        recommended_action=rule.recommended_action,
                    )
                )
                break
            else:
                continue
            break
    return _sorted_hits(hits)


def _match_rule(rule: ComplianceRuleDefinition, value: str) -> str | None:
    for pattern in rule.patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _format_trigger_text(source: str, raw_value: str, match_text: str) -> str:
    if source == "message":
        text = match_text.strip()
    elif source == "attachments":
        text = f"attachment:{raw_value.strip()}"
    else:
        text = f"workflow:{raw_value.strip()}"
    if len(text) > _MAX_TRIGGER_TEXT:
        return text[: _MAX_TRIGGER_TEXT - 15] + "...[truncated]"
    return text


def _sorted_hits(hits: list[ComplianceRuleHit]) -> list[ComplianceRuleHit]:
    return sorted(
        hits,
        key=lambda hit: (
            _ACTION_RANK[hit.recommended_action],
            _SEVERITY_RANK[hit.severity],
            hit.rule_id,
        ),
        reverse=True,
    )


def _dominant_hit(hits: list[ComplianceRuleHit]) -> ComplianceRuleHit | None:
    return hits[0] if hits else None


def _choose_disposition(hits: list[ComplianceRuleHit]) -> ComplianceDisposition:
    dominant_hit = _dominant_hit(hits)
    if dominant_hit is None:
        return "allow"
    return dominant_hit.recommended_action


def _runtime_state_for_disposition(
    disposition: ComplianceDisposition,
) -> ComplianceRuntimeState:
    return {
        "allow": "allowed",
        "allow_with_warning": "warning_issued",
        "require_approval": "approval_required",
        "block": "blocked",
    }[disposition]


def _resolve_decision(
    preflight_disposition: ComplianceDisposition,
    payload: CompliancePreflightInput,
    timestamp: datetime,
) -> ComplianceDecision:
    approval_scope = (
        _DEFAULT_APPROVAL_SCOPE if preflight_disposition == "require_approval" else None
    )
    if payload.approval_override and preflight_disposition == "require_approval":
        approval = ComplianceApprovalRecord(
            approved_by=payload.approval_override.approved_by,
            approval_scope=payload.approval_override.approval_scope,
            approved_at=timestamp,
            override_for_disposition=preflight_disposition,
            rationale=payload.approval_override.rationale,
        )
        return ComplianceDecision(
            runtime_state="approved_override",
            decision_source="human_override",
            preflight_disposition=preflight_disposition,
            final_disposition="allow",
            human_approval_required=True,
            approval_scope=payload.approval_override.approval_scope,
            approval=approval,
        )

    return ComplianceDecision(
        runtime_state=_runtime_state_for_disposition(preflight_disposition),
        decision_source="deterministic_rules",
        preflight_disposition=preflight_disposition,
        final_disposition=preflight_disposition,
        human_approval_required=preflight_disposition == "require_approval",
        approval_scope=approval_scope,
        approval=None,
    )


def _build_report(
    run_id: str,
    created_at: datetime,
    payload: CompliancePreflightInput,
    hits: list[ComplianceRuleHit],
    risk_category: RiskCategory,
    decision: ComplianceDecision,
) -> ComplianceReport:
    report_id = f"compliance-preflight-{run_id.lower()}".replace("_", "-")
    return ComplianceReport.model_validate(
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "compliance_report",
            "id": report_id,
            "run_id": run_id,
            "created_at": created_at,
            "source_workflow": COMPLIANCE_WORKFLOW_NAME,
            "related_artifacts": [],
            "request_context": {
                "user_message": payload.user_message,
                "attached_identifiers": payload.attached_identifiers,
                "selected_workflow": payload.selected_workflow,
                "session_id": payload.session_id,
            },
            "risk_category": risk_category,
            "triggered_rules": [hit.model_dump(mode="json") for hit in hits],
            "runtime_state": decision.runtime_state,
            "decision_source": decision.decision_source,
            "preflight_disposition": decision.preflight_disposition,
            "block_status": "blocked" if decision.final_disposition == "block" else "not_blocked",
            "human_approval_required": decision.human_approval_required,
            "approval_scope": decision.approval_scope,
            "approval": decision.approval.model_dump(mode="json") if decision.approval else None,
            "final_disposition": decision.final_disposition,
        }
    )


def _persist_report(layout, report: ComplianceReport) -> tuple[Path, str]:
    report_payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    report_path = layout.stable_artifact_path("compliance_report")
    report_path.write_text(report_payload, encoding="utf-8")

    run_record_text = layout.run_record_path.read_text(encoding="utf-8")
    content_hash_manifest = build_content_hash_manifest(
        run_id=layout.run_id,
        schema_version=SCHEMA_PACK_VERSION,
        created_at=layout.created_at,
        source_workflow=layout.workflow,
        entries={
            "run.json": run_record_text,
            stable_artifact_name("compliance_report"): report_payload,
        },
    )
    layout.content_hash_manifest_path.write_text(
        json.dumps(content_hash_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path, layout.stable_artifact_relpath("compliance_report").as_posix()


def _build_tool_input(payload: CompliancePreflightInput) -> str:
    parts = [payload.user_message.strip()]
    if payload.attached_identifiers:
        parts.append(f"attachments={', '.join(payload.attached_identifiers)}")
    if payload.selected_workflow:
        parts.append(f"workflow={payload.selected_workflow}")
    if payload.approval_override:
        parts.append(
            "approval_override="
            f"{payload.approval_override.approval_scope}:{payload.approval_override.approved_by}"
        )
    return "\n".join(parts)


def _build_tool_summary(report: ComplianceReport) -> str:
    if report.runtime_state == "blocked":
        return "Compliance preflight blocked this request before execution."
    if report.runtime_state == "approval_required":
        return "Compliance preflight requires approval before execution can continue."
    if report.runtime_state == "approved_override" and report.approval is not None:
        return (
            "Compliance preflight required approval and recorded a "
            f"{report.approval.approval_scope}-scoped override by {report.approval.approved_by}."
        )
    if not report.triggered_rules:
        return "Compliance preflight completed with disposition allow and no deterministic rule hits."
    return (
        "Compliance preflight completed with disposition "
        f"{report.final_disposition} and {len(report.triggered_rules)} rule hit(s) "
        f"in category {report.risk_category}."
    )


def _build_warning_text(report: ComplianceReport) -> str | None:
    if report.runtime_state == "warning_issued":
        return (
            "Compliance warning: this request references privacy-sensitive human-data context. "
            "Continue only with de-identified inputs and preserve the dataset privacy classification."
        )
    if report.runtime_state == "approved_override" and report.approval is not None:
        return (
            "Compliance approval override recorded: "
            f"{report.approval.approved_by} approved this {report.approval.approval_scope}-scoped "
            "request, and execution may continue under audit."
        )
    return None


def _build_response_text(report: ComplianceReport) -> str | None:
    if report.final_disposition == "allow":
        return None

    header = {
        "allow_with_warning": "Compliance preflight issued a warning before execution.",
        "require_approval": "Compliance preflight requires approval before execution can continue.",
        "block": "Compliance preflight blocked this request before execution.",
    }[report.final_disposition]

    lines = [header, "", "Triggered rules:"]
    for hit in report.triggered_rules:
        lines.append(
            f"- `{hit.rule_id}` ({hit.category}, {hit.severity}): matched `{hit.trigger_text}`"
        )
    if report.final_disposition in {"require_approval", "block"}:
        lines.extend(
            [
                "",
                "No biology-sensitive work was executed after the compliance check.",
            ]
        )
    return "\n".join(lines)


def _result_warnings(report: ComplianceReport) -> list[str]:
    warnings: list[str] = []
    if report.runtime_state == "warning_issued":
        warnings.append("compliance_warning")
    if report.runtime_state == "approval_required":
        warnings.append("approval_required")
    if report.runtime_state == "blocked":
        warnings.append("blocked_by_compliance")
    if report.runtime_state == "approved_override":
        warnings.append("approved_override")
    return warnings
