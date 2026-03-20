"""Tests for the BioAPEX core schema pack."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts.naming import stable_artifact_name
from artifacts.schemas import (  # noqa: E402
    SCHEMA_PACK_VERSION,
    ComplianceReport,
    DatasetManifest,
    EvidenceCard,
    ProtocolRun,
    QAReport,
    WorkflowRun,
    artifact_model_for_type,
    load_artifact_document,
    schema_format_for_artifact,
    validate_artifact_payload,
)
from qc_policy import QCPolicyDefinition, evaluate_qc_policy  # noqa: E402


EXAMPLES_DIR = Path(__file__).parent.parent / "artifacts" / "examples"


class TestArtifactSchemas:
    def test_schema_format_mapping_matches_reserved_filenames(self):
        for artifact_type, expected_format in {
            "dataset_manifest": "yaml",
            "workflow_run": "json",
            "evidence_card": "yaml",
            "compliance_report": "json",
            "protocol_run": "yaml",
            "qa_report": "json",
        }.items():
            filename = stable_artifact_name(artifact_type)
            assert schema_format_for_artifact(artifact_type) == expected_format
            assert filename.endswith(".json") or filename.endswith(".yaml")

    def test_dataset_manifest_rejects_absolute_source_paths(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "sample_sheet_path": "data/sample_sheet.tsv",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "test-study",
                "experiment_type": "scrna_seq",
                "condition_summary": "test summary",
                "timepoints": ["baseline"],
                "factors": ["condition"],
            },
            "source_files": ["/tmp/manifest.tsv"],
        }

        with pytest.raises(ValueError, match="relative"):
            DatasetManifest.model_validate(payload)

    def test_workflow_run_requires_canonical_run_id(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "workflow_run",
            "id": "workflow-run-test-v1",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "internal-dag-runner",
            "related_artifacts": [],
            "run_id": "not-a-run-id",
            "workflow": {"name": "test", "slug": "test"},
            "lifecycle_status": "created",
            "qc_status": "pending",
            "engine": "internal_dag_runner_v1",
            "parameters": {},
            "environment": {},
            "inputs": [],
            "outputs": [],
        }

        with pytest.raises(ValueError, match="run_id"):
            WorkflowRun.model_validate(payload)

    def test_evidence_cards_require_prefixed_stable_identifiers(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "evidence_card",
            "id": "evidence-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "literature-retrieval",
            "related_artifacts": [],
            "source_database": "pubmed",
            "stable_identifier": "12345678",
            "title": "test title",
            "claims": [{"id": "claim-1", "statement": "test", "confidence": "medium"}],
            "confidence": "medium",
            "limitations": ["small sample size"],
            "cached_raw_payload_path": "backend/knowledge/cache/pubmed/12345678.md",
        }

        with pytest.raises(ValueError, match="stable_identifier"):
            EvidenceCard.model_validate(payload)

    def test_compliance_reports_keep_disposition_and_block_state_consistent(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "compliance_report",
            "id": "compliance-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_tool": "guide_risk_precheck",
            "related_artifacts": [],
            "request_context": {
                "user_message": "Review the patient sheet before analysis.",
                "attached_identifiers": ["patient_sheet.csv"],
                "selected_workflow": "scrna-seq-qc",
            },
            "risk_category": "privacy",
            "triggered_rules": [
                {
                    "rule_id": "privacy-sample-sheet",
                    "category": "privacy",
                    "trigger_text": "sample sheet contains direct identifiers",
                    "severity": "high",
                    "recommended_action": "block",
                }
            ],
            "runtime_state": "blocked",
            "decision_source": "deterministic_rules",
            "preflight_disposition": "block",
            "block_status": "not_blocked",
            "human_approval_required": False,
            "final_disposition": "block",
        }

        with pytest.raises(ValueError, match="block_status"):
            ComplianceReport.model_validate(payload)

    def test_compliance_reports_require_approval_record_for_approved_override(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "compliance_report",
            "id": "compliance-test-approved-override-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_tool": "guide_risk_precheck",
            "related_artifacts": [],
            "request_context": {
                "user_message": "Review the patient sheet before analysis.",
                "attached_identifiers": ["patient_sheet.csv"],
                "selected_workflow": "scrna-seq-qc",
                "session_id": "session-approved-override",
            },
            "risk_category": "privacy",
            "triggered_rules": [
                {
                    "rule_id": "privacy-sample-sheet",
                    "category": "privacy",
                    "trigger_text": "patient_sheet.csv",
                    "severity": "high",
                    "recommended_action": "require_approval",
                }
            ],
            "runtime_state": "approved_override",
            "decision_source": "human_override",
            "preflight_disposition": "require_approval",
            "block_status": "not_blocked",
            "human_approval_required": True,
            "approval_scope": "message",
            "approval": None,
            "final_disposition": "allow",
        }

        with pytest.raises(ValueError, match="approval record"):
            ComplianceReport.model_validate(payload)

    def test_protocol_runs_require_completed_at_when_completed(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "protocol_run",
            "id": "protocol-run-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "protocol-executor",
            "source_agent": "protocol-executor",
            "related_artifacts": [],
            "protocol_source": {
                "artifact_type": "protocol_document",
                "path": "backend/knowledge/protocols/test.md",
                "id": "test-protocol-v1",
            },
            "operator": "operator-1",
            "sample_ids": ["sample-001"],
            "materials": [],
            "reagent_lots": [],
            "equipment": [],
            "started_at": "2026-03-18T19:30:00Z",
            "completion_state": "completed",
            "deviations": [],
            "assumptions": [],
        }

        with pytest.raises(ValueError, match="completed_at"):
            ProtocolRun.model_validate(payload)

    def test_qa_reports_require_failure_context_for_blocked_status(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "qa_report",
            "id": "qa-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "qa-review",
            "source_agent": "qa-reviewer",
            "related_artifacts": [],
            "overall_status": "blocked",
            "failed_checks": [],
            "warnings": [],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }

        with pytest.raises(ValueError, match="failed_checks or missing_artifacts"):
            QAReport.model_validate(payload)

    def test_artifacts_require_run_id_and_workflow_or_tool_header_fields(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-test-v1",
            "created_at": "2026-03-18T19:30:00Z",
            "source_agent": "dataset-agent",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "sample_sheet_path": "data/sample_sheet.tsv",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "test-study",
                "experiment_type": "scrna_seq",
                "condition_summary": "test summary",
                "timepoints": ["baseline"],
                "factors": ["condition"],
            },
            "source_files": ["data/test.tsv"],
        }

        with pytest.raises(ValueError, match="run_id"):
            DatasetManifest.model_validate(payload)

        payload["run_id"] = "run-20260318T193000Z-deadbeef"

        with pytest.raises(ValueError, match="source_workflow or source_tool"):
            DatasetManifest.model_validate(payload)

    def test_dataset_manifest_allows_missing_analysis_ready_reference_fields_for_backward_compatibility(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "sample_sheet_path": "data/sample_sheet.tsv",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "test-study",
                "experiment_type": "scrna_seq",
                "condition_summary": "test summary",
                "timepoints": ["baseline"],
                "factors": ["condition"],
            },
            "source_files": ["data/test.tsv"],
        }

        parsed = DatasetManifest.model_validate(payload)
        assert parsed.reference_build is None
        assert parsed.reference_resource is None

    def test_dataset_manifest_allows_missing_analysis_ready_design_fields_for_backward_compatibility(self):
        payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-test-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "sample_sheet_path": "data/sample_sheet.tsv",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "test-study",
                "experiment_type": "scrna_seq",
                "condition_summary": "test summary",
                "analysis_kind": "comparative",
            },
            "source_files": ["data/test.tsv"],
        }

        parsed = DatasetManifest.model_validate(payload)
        assert parsed.design.analysis_kind == "comparative"
        assert parsed.design.condition_fields is None
        assert parsed.design.batch_fields is None

    def test_dataset_manifest_accepts_embedded_qc_policy_and_workflow_run_persists_evaluation_summary(self):
        manifest_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-qc-policy-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "perturb_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "sample_sheet_path": "data/sample_sheet.tsv",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "qc-policy-study",
                "experiment_type": "perturb_seq",
                "condition_summary": "single-cell perturbation pilot",
                "analysis_kind": "comparative",
                "condition_fields": ["perturbation"],
                "batch_fields": ["donor"],
                "timepoints": ["baseline"],
                "factors": ["perturbation", "donor"],
            },
            "source_files": ["data/test.tsv"],
            "qc_policy": {
                "policy_id": "scrna-default-qc",
                "label": "Single-cell default QC policy",
                "version": "1.0.0",
                "assay_type": "scrna_seq",
                "required_upstream_tools": ["fastqc", "multiqc"],
                "checks": [
                    {
                        "id": "median-genes-per-cell",
                        "label": "Median genes per cell",
                        "metric_name": "median_genes_per_cell",
                        "category": "technical",
                        "comparison": "minimum",
                        "pass_threshold": 300,
                        "warn_threshold": 200,
                    }
                ],
                "assay_overrides": [
                    {
                        "assay_type": "perturb_seq",
                        "check_overrides": [
                            {
                                "check_id": "median-genes-per-cell",
                                "pass_threshold": 350,
                                "warn_threshold": 250,
                            }
                        ],
                    }
                ],
            },
            "assay_extensions": {
                "qc_evidence": {
                    "upstream_tools": ["fastqc", "multiqc"],
                    "metrics": [
                        {
                            "metric_name": "median_genes_per_cell",
                            "observed_value": 412,
                            "source_artifact": {
                                "artifact_type": "qa_report",
                                "path": "artifacts/qc/run-1/qa_report.json",
                            },
                        }
                    ],
                }
            },
        }
        manifest = DatasetManifest.model_validate(manifest_payload)

        assert manifest.qc_policy is not None
        assert manifest.qc_policy.policy_id == "scrna-default-qc"
        assert manifest.qc_policy.assay_overrides[0].assay_type == "perturb_seq"

        run_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "workflow_run",
            "id": "workflow-run-qc-policy-v1",
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "rna-seq-qc",
            "related_artifacts": [],
            "workflow": {"name": "RNA Seq QC", "slug": "rna-seq-qc"},
            "lifecycle_status": "completed",
            "qc_status": "warning",
            "engine": "internal_dag_runner_v1",
            "parameters": {},
            "environment": {},
            "inputs": [],
            "outputs": [],
            "qc_policies": [manifest.qc_policy.model_dump(mode="json")],
            "qc_policy_results": [
                {
                    "policy_id": "scrna-default-qc",
                    "label": "Single-cell default QC policy",
                    "version": "1.0.0",
                    "assay_type": "perturb_seq",
                    "applied_assay_override": "perturb_seq",
                    "gate_id": "evaluate-scrna-policy",
                    "stage": "after_step",
                    "required_upstream_tools": ["fastqc", "multiqc"],
                    "missing_upstream_tools": [],
                    "overall_status": "warn",
                    "checks": [
                        {
                            "check_id": "median-genes-per-cell",
                            "label": "Median genes per cell",
                            "metric_name": "median_genes_per_cell",
                            "category": "technical",
                            "status": "warn",
                            "observed_value": 260,
                            "threshold": ">= 350 pass; >= 250 warn",
                            "source_artifact": {
                                "artifact_type": "qa_report",
                                "path": "artifacts/qc/run-1/qa_report.json",
                            },
                            "message": "median_genes_per_cell=260 did not meet >= 350.",
                        }
                    ],
                    "summary": "Single-cell default QC policy [warn] Technical warnings: median_genes_per_cell=260 did not meet >= 350.",
                }
            ],
            "qc_summary": "Single-cell default QC policy [warn] Technical warnings: median_genes_per_cell=260 did not meet >= 350.",
            "steps": [],
            "provenance_exports": [],
            "warnings": ["QC thresholds should be reviewed before interpretation."],
            "warning_details": [],
        }

        run_document = WorkflowRun.model_validate(run_payload)

        assert run_document.qc_policies[0].policy_id == "scrna-default-qc"
        assert run_document.qc_policy_results[0].applied_assay_override == "perturb_seq"
        assert "Technical warnings" in run_document.qc_summary

    def test_qc_policy_summary_distinguishes_batch_and_design_failures_from_warnings(self):
        policy = QCPolicyDefinition.model_validate(
            {
                "policy_id": "summary-demo-qc",
                "label": "Summary Demo QC",
                "version": "1.0.0",
                "checks": [
                    {
                        "id": "donor-balance",
                        "label": "Donor balance",
                        "metric_name": "donor_balance_ratio",
                        "category": "batch_effect",
                        "comparison": "minimum",
                        "pass_threshold": 0.8,
                        "warn_threshold": 0.6,
                    },
                    {
                        "id": "replicate-count",
                        "label": "Replicate count",
                        "metric_name": "replicate_count",
                        "category": "experimental_design",
                        "comparison": "minimum",
                        "pass_threshold": 3,
                        "warn_threshold": 2,
                    },
                ],
            }
        )

        evaluation = evaluate_qc_policy(
            policy,
            {
                "upstream_tools": [],
                "metrics": [
                    {"metric_name": "donor_balance_ratio", "observed_value": 0.5},
                    {"metric_name": "replicate_count", "observed_value": 1},
                ],
            },
        )

        assert evaluation.overall_status == "fail"
        assert "Batch-effect failures" in evaluation.summary
        assert "Experimental-design failures" in evaluation.summary

    def test_example_artifacts_validate_from_disk(self):
        expected_types = {
            "dataset_manifest.yaml": DatasetManifest,
            "rnaseq_dataset_manifest.yaml": DatasetManifest,
            "run.json": WorkflowRun,
            "evidence_card.yaml": EvidenceCard,
            "compliance_report.json": ComplianceReport,
            "protocol_run.yaml": ProtocolRun,
            "qa_report.json": QAReport,
        }

        for filename, expected_model in expected_types.items():
            document = load_artifact_document(EXAMPLES_DIR / filename)
            assert isinstance(document, expected_model)
            assert document.schema_version == SCHEMA_PACK_VERSION

    def test_validate_artifact_payload_dispatches_by_artifact_type(self):
        document = load_artifact_document(EXAMPLES_DIR / "run.json")
        payload = document.model_dump(mode="json")

        parsed = validate_artifact_payload(payload)

        assert isinstance(parsed, WorkflowRun)
        assert artifact_model_for_type("workflow_run") is WorkflowRun
