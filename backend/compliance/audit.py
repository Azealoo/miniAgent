"""Append-only audit helpers for compliance decisions."""

from __future__ import annotations

import json
from pathlib import Path

from audit.store import append_audit_event, request_summary
from artifacts.schemas import ComplianceReport

COMPLIANCE_AUDIT_DIR = Path("storage") / "compliance_audit"
COMPLIANCE_AUDIT_FILENAME = "compliance_decisions.jsonl"


def append_compliance_audit_record(
    base_dir: Path | str,
    report: ComplianceReport,
    artifact_relpath: str,
) -> Path:
    base_path = Path(base_dir).resolve()
    audit_dir = base_path / COMPLIANCE_AUDIT_DIR
    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_path = audit_dir / COMPLIANCE_AUDIT_FILENAME
    report_payload = report.model_dump(mode="json")
    summary = request_summary(
        message=report.request_context.user_message,
        attached_identifiers=report.request_context.attached_identifiers,
        selected_workflow=report.request_context.selected_workflow,
    )
    record = {
        "event_type": "compliance_decision",
        "schema_version": report.schema_version,
        "recorded_at": report_payload["created_at"],
        "report_id": report.id,
        "run_id": report.run_id,
        "session_id": report.request_context.session_id,
        "artifact_path": artifact_relpath,
        "risk_category": report.risk_category,
        "runtime_state": report.runtime_state,
        "preflight_disposition": report.preflight_disposition,
        "final_disposition": report.final_disposition,
        "decision_source": report.decision_source,
        "approval_scope": report.approval_scope,
        "approved_by": report.approval.approved_by if report.approval else None,
        "triggered_rule_ids": [hit.rule_id for hit in report.triggered_rules],
        "request_summary": summary,
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    append_audit_event(
        base_path,
        event_type="compliance_decision",
        summary=(
            f"Compliance preflight {report.final_disposition} for risk category "
            f"{report.risk_category}."
        ),
        outcome=report.final_disposition,
        session_id=report.request_context.session_id,
        run_id=report.run_id,
        workflow_id=report.request_context.selected_workflow,
        artifact_paths=[artifact_relpath],
        details={
            "schema_version": report.schema_version,
            "report_id": report.id,
            "artifact_path": artifact_relpath,
            "risk_category": report.risk_category,
            "runtime_state": report.runtime_state,
            "preflight_disposition": report.preflight_disposition,
            "decision_source": report.decision_source,
            "approval_scope": report.approval_scope,
            "approved_by": report.approval.approved_by if report.approval else None,
            "triggered_rule_ids": [hit.rule_id for hit in report.triggered_rules],
            "request_summary": summary,
        },
        recorded_at=report.created_at,
    )
    return audit_path
