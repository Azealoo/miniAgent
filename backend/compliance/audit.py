"""Append-only audit helpers for compliance decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from artifacts.schemas import ComplianceReport

COMPLIANCE_AUDIT_DIR = Path("storage") / "compliance_audit"
COMPLIANCE_AUDIT_FILENAME = "compliance_decisions.jsonl"


def _request_summary(report: ComplianceReport) -> dict[str, object]:
    request_context = report.request_context
    message_hash = hashlib.sha256(
        request_context.user_message.encode("utf-8")
    ).hexdigest()
    attachment_hashes = [
        hashlib.sha256(item.encode("utf-8")).hexdigest()
        for item in request_context.attached_identifiers
    ]
    return {
        "message_sha256": message_hash,
        "attached_identifier_count": len(request_context.attached_identifiers),
        "attached_identifier_sha256": attachment_hashes,
        "selected_workflow": request_context.selected_workflow,
        "session_id": request_context.session_id,
    }


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
        "request_summary": _request_summary(report),
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return audit_path
