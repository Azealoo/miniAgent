"""Tests for the BioAPEX core schema pack."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts.naming import stable_artifact_name
from artifacts.schema_validation import validate_biocompute_payload_against_reference_schemas
from artifacts.schemas import (  # noqa: E402
    SCHEMA_PACK_VERSION,
    BioComputeArtifact,
    ComplianceReport,
    CountMatrix,
    DatasetManifest,
    DifferentialExpressionResults,
    DifferentialExpressionRun,
    EvidenceCard,
    EvidenceReviewArtifact,
    EntityGroundingArtifact,
    FastQCMetrics,
    FastQCRun,
    GroundedEntity,
    MultiQCMetrics,
    MultiQCRun,
    NormalizedCountMatrix,
    ProtocolRun,
    ProvenanceArtifact,
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
            "count_matrix": "json",
            "normalized_count_matrix": "json",
            "differential_expression_results": "json",
            "differential_expression_run": "json",
            "workflow_run": "json",
            "provenance": "json",
            "biocompute": "json",
            "evidence_card": "yaml",
            "evidence_review": "json",
            "entity_grounding": "json",
            "compliance_report": "json",
            "protocol_run": "yaml",
            "qa_report": "json",
        }.items():
            filename = stable_artifact_name(artifact_type)
            assert schema_format_for_artifact(artifact_type) == expected_format
            assert filename.endswith(".json") or filename.endswith(".yaml")

    def test_fastqc_artifact_types_use_json_schema_format(self):
        assert artifact_model_for_type("fastqc_run") is FastQCRun
        assert artifact_model_for_type("fastqc_metrics") is FastQCMetrics
        assert schema_format_for_artifact("fastqc_run") == "json"
        assert schema_format_for_artifact("fastqc_metrics") == "json"

    def test_multiqc_artifact_types_use_json_schema_format(self):
        assert artifact_model_for_type("multiqc_run") is MultiQCRun
        assert artifact_model_for_type("multiqc_metrics") is MultiQCMetrics
        assert schema_format_for_artifact("multiqc_run") == "json"
        assert schema_format_for_artifact("multiqc_metrics") == "json"

    def test_differential_expression_artifact_types_use_json_schema_format(self):
        assert artifact_model_for_type("count_matrix") is CountMatrix
        assert artifact_model_for_type("normalized_count_matrix") is NormalizedCountMatrix
        assert artifact_model_for_type("differential_expression_results") is DifferentialExpressionResults
        assert artifact_model_for_type("differential_expression_run") is DifferentialExpressionRun
        assert schema_format_for_artifact("count_matrix") == "json"
        assert schema_format_for_artifact("normalized_count_matrix") == "json"
        assert schema_format_for_artifact("differential_expression_results") == "json"
        assert schema_format_for_artifact("differential_expression_run") == "json"

    def test_provenance_artifact_type_uses_json_schema_format(self):
        assert artifact_model_for_type("provenance") is ProvenanceArtifact
        assert schema_format_for_artifact("provenance") == "json"

    def test_biocompute_artifact_type_uses_json_schema_format(self):
        assert artifact_model_for_type("biocompute") is BioComputeArtifact
        assert schema_format_for_artifact("biocompute") == "json"

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

    def test_grounded_entities_require_prefixed_stable_identifiers(self):
        payload = {
            "entity_type": "gene",
            "source_database": "ensembl",
            "stable_identifier": "ENSG00000141510",
            "preferred_label": "TP53",
            "aliases": ["TP53"],
            "species": "Homo sapiens",
            "taxon_id": "taxonomy:9606",
        }

        with pytest.raises(ValueError, match="stable_identifier"):
            GroundedEntity.model_validate(payload)

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

    def test_fastqc_artifacts_validate_structured_provenance_and_metrics(self):
        run_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "fastqc_run",
            "id": "fastqc-run-rnaseq-qc-de-raw-qc-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:00:00Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "fastqc_zip_archive",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc/sample1_R1_fastqc.zip",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "tool_version": "FastQC v0.12.1",
            "sequencing_layout": "paired_end",
            "sample_sheet_path": "backend/artifacts/examples/rnaseq/sample_sheet.tsv",
            "output_directory": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc",
            "command": ["fastqc", "--outdir", "artifacts/rnaseq-qc-de/.../fastqc", "sample1_R1.fastq.gz"],
            "parameters": {"extra_args": ["--quiet"], "input_count": 2},
            "input_files": [
                {
                    "sample_id": "sample1",
                    "read_label": "read1",
                    "path": "backend/artifacts/examples/rnaseq/sample1_R1.fastq.gz",
                    "sha256": "a" * 64,
                    "size_bytes": 123,
                    "row_number": 2,
                }
            ],
            "reports": [
                {
                    "sample_id": "sample1",
                    "read_label": "read1",
                    "html_report": {
                        "artifact_type": "fastqc_html_report",
                        "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc/sample1_R1_fastqc.html",
                        "run_id": "run-20260319T210000Z-deadbeef",
                    },
                    "zip_archive": {
                        "artifact_type": "fastqc_zip_archive",
                        "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc/sample1_R1_fastqc.zip",
                        "run_id": "run-20260319T210000Z-deadbeef",
                    },
                }
            ],
            "stdout_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc.stdout.txt",
            "stderr_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc.stderr.txt",
            "metrics_artifact": {
                "artifact_type": "fastqc_metrics",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc_metrics.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
        }
        metrics_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "fastqc_metrics",
            "id": "fastqc-metrics-rnaseq-qc-de-raw-qc-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:00:05Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "fastqc_run",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc_run.json",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "tool_version": "FastQC v0.12.1",
            "sequencing_layout": "paired_end",
            "sample_sheet_path": "backend/artifacts/examples/rnaseq/sample_sheet.tsv",
            "run_artifact": {
                "artifact_type": "fastqc_run",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc_run.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "sample_metrics": [
                {
                    "sample_id": "sample1",
                    "read_label": "read1",
                    "input_file": {
                        "artifact_type": "fastq",
                        "path": "backend/artifacts/examples/rnaseq/sample1_R1.fastq.gz",
                    },
                    "html_report": {
                        "artifact_type": "fastqc_html_report",
                        "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc/sample1_R1_fastqc.html",
                        "run_id": "run-20260319T210000Z-deadbeef",
                    },
                    "zip_archive": {
                        "artifact_type": "fastqc_zip_archive",
                        "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc/sample1_R1_fastqc.zip",
                        "run_id": "run-20260319T210000Z-deadbeef",
                    },
                    "total_sequences": 1200,
                    "sequences_flagged_as_poor_quality": 0,
                    "sequence_length": "75",
                    "percent_gc": 48.0,
                    "min_per_base_quality": 31.4,
                    "module_results": [
                        {
                            "module_id": "per-base-sequence-quality",
                            "module_name": "Per base sequence quality",
                            "status": "pass",
                        }
                    ],
                    "overall_status": "pass",
                }
            ],
            "aggregate_metrics": {
                "sequencing_layout": "paired_end",
                "sample_count": 1,
                "input_file_count": 1,
                "total_reads": 1200,
                "total_reads_millions": 0.0012,
                "min_per_base_quality": 31.4,
                "fastqc_pass_rate": 1.0,
                "module_status_counts": [
                    {
                        "module_id": "per-base-sequence-quality",
                        "module_name": "Per base sequence quality",
                        "pass_count": 1,
                        "warn_count": 0,
                        "fail_count": 0,
                    }
                ],
            },
        }

        run_document = validate_artifact_payload(run_payload)
        metrics_document = validate_artifact_payload(metrics_payload)

        assert isinstance(run_document, FastQCRun)
        assert run_document.reports[0].zip_archive.artifact_type == "fastqc_zip_archive"
        assert isinstance(metrics_document, FastQCMetrics)
        assert metrics_document.aggregate_metrics.fastqc_pass_rate == 1.0

    def test_multiqc_artifacts_validate_structured_provenance_and_metrics(self):
        run_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "multiqc_run",
            "id": "multiqc-run-rnaseq-qc-de-aggregated-qc-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:05:00Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "multiqc_html_report",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_report.html",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "tool_version": "multiqc, version 1.21",
            "sample_sheet_path": "backend/artifacts/examples/rnaseq/sample_sheet.tsv",
            "output_directory": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc",
            "input_directories": [
                "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/raw-qc/fastqc"
            ],
            "command": [
                "multiqc",
                "--outdir",
                "artifacts/rnaseq-qc-de/.../multiqc",
                "--filename",
                "multiqc_report.html",
                "--force",
                "artifacts/rnaseq-qc-de/.../fastqc",
            ],
            "parameters": {"extra_args": [], "input_count": 1, "report_filename": "multiqc_report.html"},
            "upstream_fastqc_run": {
                "artifact_type": "fastqc_run",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/fastqc_run.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "upstream_fastqc_metrics": {
                "artifact_type": "fastqc_metrics",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/fastqc_metrics.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "report_html": {
                "artifact_type": "multiqc_html_report",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_report.html",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "report_data_directory": {
                "artifact_type": "multiqc_data_directory",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_data",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "report_summary_data": {
                "artifact_type": "multiqc_summary_data",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_data/bioapex_multiqc_summary.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "stdout_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc.stdout.txt",
            "stderr_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc.stderr.txt",
            "metrics_artifact": {
                "artifact_type": "multiqc_metrics",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc_metrics.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
        }
        metrics_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "multiqc_metrics",
            "id": "multiqc-metrics-rnaseq-qc-de-aggregated-qc-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:05:05Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "multiqc_run",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc_run.json",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "tool_version": "multiqc, version 1.21",
            "sample_sheet_path": "backend/artifacts/examples/rnaseq/sample_sheet.tsv",
            "run_artifact": {
                "artifact_type": "multiqc_run",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc_run.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "upstream_fastqc_run": {
                "artifact_type": "fastqc_run",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/fastqc_run.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "upstream_fastqc_metrics": {
                "artifact_type": "fastqc_metrics",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/fastqc_metrics.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "report_html": {
                "artifact_type": "multiqc_html_report",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_report.html",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "report_data_directory": {
                "artifact_type": "multiqc_data_directory",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_data",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "report_summary_data": {
                "artifact_type": "multiqc_summary_data",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/aggregated-qc/multiqc/multiqc_data/bioapex_multiqc_summary.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "sample_names": ["control_rep1", "treated_rep1"],
            "report_modules": ["FastQC"],
            "sample_metrics": [
                {
                    "sample_id": "control_rep1",
                    "input_file_count": 2,
                    "total_reads": 2400000,
                    "total_reads_millions": 2.4,
                    "min_per_base_quality": 31.4,
                    "fastqc_status": "pass",
                }
            ],
            "aggregate_metrics": {
                "sample_count": 1,
                "input_file_count": 2,
                "total_reads": 2400000,
                "total_reads_millions": 2.4,
                "min_per_base_quality": 31.4,
                "fastqc_pass_rate": 1.0,
                "report_sample_count": 2,
                "report_module_count": 1,
                "report_modules": ["FastQC"],
            },
        }

        run_document = validate_artifact_payload(run_payload)
        metrics_document = validate_artifact_payload(metrics_payload)

        assert isinstance(run_document, MultiQCRun)
        assert run_document.report_html.artifact_type == "multiqc_html_report"
        assert isinstance(metrics_document, MultiQCMetrics)
        assert metrics_document.aggregate_metrics.report_sample_count == 2

    def test_differential_expression_artifacts_validate_structured_outputs(self):
        count_matrix_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "count_matrix",
            "id": "count-matrix-rnaseq-qc-de-quantification-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:10:00Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [],
            "engine_name": "bioapex_deterministic_quantification",
            "engine_version": "1.0.0",
            "matrix_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/quantification/gene_counts.tsv",
            "matrix_format": "tsv",
            "sample_sheet_path": "backend/artifacts/examples/rnaseq/sample_sheet.tsv",
            "condition_field": "condition",
            "batch_fields": ["batch"],
            "sample_ids": ["control_rep1", "treated_rep1"],
            "gene_ids": ["ENSG00000185745", "ENSG00000187608"],
            "library_sizes": {"control_rep1": 12000, "treated_rep1": 14000},
            "upstream_multiqc_run": {
                "artifact_type": "multiqc_run",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/multiqc_run.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "upstream_multiqc_metrics": {
                "artifact_type": "multiqc_metrics",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/multiqc_metrics.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
        }
        normalized_count_matrix_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "normalized_count_matrix",
            "id": "normalized-count-matrix-rnaseq-qc-de-differential-expression-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:12:00Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "count_matrix",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/count_matrix.json",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "engine_name": "bioapex_mean_centered_t_test",
            "engine_version": "1.0.0",
            "normalization_method": "median_library_size",
            "matrix_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/differential-expression/treated-vs-control.normalized_counts.tsv",
            "matrix_format": "tsv",
            "sample_ids": ["control_rep1", "treated_rep1"],
            "gene_count": 2,
            "library_size_factors": {"control_rep1": 0.95, "treated_rep1": 1.05},
            "source_count_matrix": {
                "artifact_type": "count_matrix",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/count_matrix.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
        }
        results_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "differential_expression_results",
            "id": "differential-expression-results-rnaseq-qc-de-differential-expression-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:12:10Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "count_matrix",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/count_matrix.json",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "engine_name": "bioapex_mean_centered_t_test",
            "engine_version": "1.0.0",
            "design": {
                "design_formula": "~ batch + condition",
                "modeled_factors": ["batch", "condition"],
                "batch_fields_expected": ["batch"],
                "batch_fields_modeled": ["batch"],
                "missing_batch_fields": [],
                "replicate_counts": {"control": 3, "treated": 3},
                "minimum_condition_replicates": 3,
            },
            "contrast": {
                "contrast_label": "treated-vs-control",
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            "source_count_matrix": {
                "artifact_type": "count_matrix",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/count_matrix.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "normalized_count_matrix": {
                "artifact_type": "normalized_count_matrix",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/normalized_count_matrix.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "results_path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/differential-expression/treated-vs-control.tsv",
            "result_format": "tsv",
            "tested_gene_count": 2,
            "significant_gene_count": 1,
            "significance_threshold": 0.05,
            "diagnostic_plots": [
                {
                    "artifact_type": "volcano_plot",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/differential-expression/treated-vs-control.volcano.svg",
                    "run_id": "run-20260319T210000Z-deadbeef",
                },
                {
                    "artifact_type": "mean_difference_plot",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/differential-expression/treated-vs-control.mean-difference.svg",
                    "run_id": "run-20260319T210000Z-deadbeef",
                },
            ],
            "warnings": [],
        }
        run_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "differential_expression_run",
            "id": "differential-expression-run-rnaseq-qc-de-differential-expression-run-20260319t210000z-deadbeef",
            "run_id": "run-20260319T210000Z-deadbeef",
            "created_at": "2026-03-19T21:12:15Z",
            "source_workflow": "rnaseq_qc_de",
            "related_artifacts": [
                {
                    "artifact_type": "differential_expression_results",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/differential_expression_results.json",
                    "run_id": "run-20260319T210000Z-deadbeef",
                }
            ],
            "engine_name": "bioapex_mean_centered_t_test",
            "engine_version": "1.0.0",
            "design": {
                "design_formula": "~ batch + condition",
                "modeled_factors": ["batch", "condition"],
                "batch_fields_expected": ["batch"],
                "batch_fields_modeled": ["batch"],
                "missing_batch_fields": [],
                "replicate_counts": {"control": 3, "treated": 3},
                "minimum_condition_replicates": 3,
            },
            "contrast": {
                "contrast_label": "treated-vs-control",
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            "parameters": {
                "significance_threshold": 0.05,
                "log2_effect_floor": 1.0,
                "normalization_method": "median_library_size",
            },
            "batch_adjustment_method": "mean_center_by_batch",
            "source_count_matrix": {
                "artifact_type": "count_matrix",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/count_matrix.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "normalized_count_matrix": {
                "artifact_type": "normalized_count_matrix",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/normalized_count_matrix.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "results_artifact": {
                "artifact_type": "differential_expression_results",
                "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/differential_expression_results.json",
                "run_id": "run-20260319T210000Z-deadbeef",
            },
            "diagnostic_plots": [
                {
                    "artifact_type": "volcano_plot",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/differential-expression/treated-vs-control.volcano.svg",
                    "run_id": "run-20260319T210000Z-deadbeef",
                },
                {
                    "artifact_type": "mean_difference_plot",
                    "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T210000Z-deadbeef/outputs/generated/differential-expression/treated-vs-control.mean-difference.svg",
                    "run_id": "run-20260319T210000Z-deadbeef",
                },
            ],
            "summary": {
                "tested_gene_count": 2,
                "significant_gene_count": 1,
                "upregulated_gene_count": 1,
                "downregulated_gene_count": 0,
                "maximum_absolute_log2_fold_change": 2.45,
                "top_upregulated_gene": "IFIT1",
                "top_downregulated_gene": None,
            },
            "warnings": [],
        }

        count_matrix_document = validate_artifact_payload(count_matrix_payload)
        normalized_count_matrix_document = validate_artifact_payload(normalized_count_matrix_payload)
        results_document = validate_artifact_payload(results_payload)
        run_document = validate_artifact_payload(run_payload)

        assert isinstance(count_matrix_document, CountMatrix)
        assert count_matrix_document.library_sizes["treated_rep1"] == 14000
        assert isinstance(normalized_count_matrix_document, NormalizedCountMatrix)
        assert normalized_count_matrix_document.gene_count == 2
        assert isinstance(results_document, DifferentialExpressionResults)
        assert results_document.diagnostic_plots[0].artifact_type == "volcano_plot"
        assert isinstance(run_document, DifferentialExpressionRun)
        assert run_document.summary.top_upregulated_gene == "IFIT1"

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
            "summary_metrics": [
                {
                    "stage": "aggregated_qc",
                    "metric_name": "fastqc_pass_rate",
                    "value": 0.95,
                    "source_artifact": {
                        "artifact_type": "multiqc_metrics",
                        "path": "artifacts/qc/run-1/multiqc_metrics.json",
                    },
                }
            ],
            "steps": [],
            "provenance_exports": [],
            "biocompute_exports": [],
            "warnings": ["QC thresholds should be reviewed before interpretation."],
            "warning_details": [],
        }

        run_document = WorkflowRun.model_validate(run_payload)

        assert run_document.qc_policies[0].policy_id == "scrna-default-qc"
        assert run_document.qc_policy_results[0].applied_assay_override == "perturb_seq"
        assert "Technical warnings" in run_document.qc_summary
        assert run_document.summary_metrics[0].metric_name == "fastqc_pass_rate"
        assert run_document.biocompute_exports == []

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
            "count_matrix.json": CountMatrix,
            "normalized_count_matrix.json": NormalizedCountMatrix,
            "differential_expression_results.json": DifferentialExpressionResults,
            "differential_expression_run.json": DifferentialExpressionRun,
            "run.json": WorkflowRun,
            "prov.json": ProvenanceArtifact,
            "biocompute.json": BioComputeArtifact,
            "evidence_card.yaml": EvidenceCard,
            "evidence_review.json": EvidenceReviewArtifact,
            "entity_grounding.json": EntityGroundingArtifact,
            "compliance_report.json": ComplianceReport,
            "protocol_run.yaml": ProtocolRun,
            "qa_report.json": QAReport,
        }

        for filename, expected_model in expected_types.items():
            document = load_artifact_document(EXAMPLES_DIR / filename)
            assert isinstance(document, expected_model)
            assert document.schema_version == SCHEMA_PACK_VERSION

    def test_biocompute_example_uses_extension_schema_and_public_xrefs(self):
        document = load_artifact_document(EXAMPLES_DIR / "biocompute.json")
        extension_schema_path = (
            Path(__file__).parent.parent
            / "artifacts"
            / "reference_schemas"
            / "biocompute_bioapex_extension.v1.schema.json"
        )
        extension_schema_payload = json.loads(extension_schema_path.read_text(encoding="utf-8"))

        assert document.error_domain.empirical_error
        assert document.error_domain.algorithmic_error
        assert len(document.extension_domain) == 1
        assert document.extension_domain[0].extension_schema == extension_schema_payload["$id"]
        assert document.description_domain.xref
        assert {xref.namespace for xref in document.description_domain.xref} == {"taxonomy"}
        assert all(
            isinstance(step.step_number, int) for step in document.description_domain.pipeline_steps
        )
        validate_biocompute_payload_against_reference_schemas(document.model_dump(mode="json"))

    def test_validate_artifact_payload_dispatches_by_artifact_type(self):
        document = load_artifact_document(EXAMPLES_DIR / "run.json")
        payload = document.model_dump(mode="json")

        parsed = validate_artifact_payload(payload)

        assert isinstance(parsed, WorkflowRun)
        assert artifact_model_for_type("workflow_run") is WorkflowRun
