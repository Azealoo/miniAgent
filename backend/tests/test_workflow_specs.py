"""Tests for typed workflow spec contracts."""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import load_artifact_document  # noqa: E402
from workflow_specs import (  # noqa: E402
    WORKFLOW_SPEC_VERSION,
    WorkflowSpecDocument,
    load_workflow_spec,
    validate_workflow_spec_payload,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / "workflows"
EXAMPLES_DIR = REPO_ROOT / "backend" / "artifacts" / "examples"


def _base_payload() -> dict:
    return {
        "schema_version": WORKFLOW_SPEC_VERSION,
        "kind": "workflow_spec",
        "workflow_id": "rna-seq-qc",
        "version": "1.0.0",
        "name": "RNA Seq QC",
        "purpose": "Run explicit RNA-seq QC from dataset intake to structured QA output.",
        "engine": "internal_dag_runner_v1",
        "required_inputs": [
            {
                "name": "dataset_manifest",
                "kind": "artifact",
                "artifact_type": "dataset_manifest",
                "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                "description": "Validated dataset intake artifact.",
            }
        ],
        "optional_inputs": [
            {
                "name": "min_genes",
                "kind": "parameter",
                "data_type": "integer",
                "default": 200,
                "description": "Minimum genes threshold for QC summaries.",
            }
        ],
        "runtime": {
            "provided_inputs": ["dataset_manifest", "min_genes"],
            "allowed_parameter_overrides": ["min_genes"],
            "generated_state": [
                "run_id",
                "created_at",
                "resolved_input_paths",
                "step_statuses",
                "artifact_paths",
            ],
            "state_artifact": "workflow_run",
            "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
        },
        "outputs": [
            {
                "name": "qa_report",
                "kind": "artifact",
                "artifact_type": "qa_report",
                "schema_ref": "artifact_schema:qa_report@1.0.0",
                "description": "Structured QA report for downstream review.",
                "source": {"step_id": "summarize_qc", "output_name": "qa_report"},
            }
        ],
        "qc_gates": [
            {
                "id": "dataset-manifest-required",
                "label": "Dataset manifest must be present",
                "when": "before_execution",
                "target": {
                    "source_type": "workflow_input",
                    "input_name": "dataset_manifest",
                },
                "failure_policy": "block",
                "description": "Block execution when the required manifest is missing.",
            }
        ],
        "compliance_hooks": [
            {
                "id": "privacy-preflight",
                "stage": "before_execution",
                "tool": "compliance_preflight",
                "required": True,
                "inputs": [
                    {
                        "name": "dataset_manifest",
                        "source": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                    }
                ],
                "description": "Run deterministic compliance screening before execution.",
            }
        ],
        "steps": [
            {
                "id": "preflight_check",
                "label": "Validate dataset manifest",
                "executor": {
                    "executor_type": "python",
                    "module": "workflows.runners.rna_seq_qc",
                    "function": "validate_manifest",
                },
                "inputs": [
                    {
                        "name": "dataset_manifest",
                        "source": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                    }
                ],
                "outputs": [
                    {
                        "name": "validated_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Validated manifest passed to downstream steps.",
                    }
                ],
                "prerequisites": [],
                "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                "failure_policy": "fail_workflow",
            },
            {
                "id": "summarize_qc",
                "label": "Summarize QC metrics",
                "executor": {
                    "executor_type": "tool",
                    "tool_name": "slurm_tool",
                },
                "inputs": [
                    {
                        "name": "dataset_manifest",
                        "source": {
                            "source_type": "step_output",
                            "step_id": "preflight_check",
                            "output_name": "validated_manifest",
                        },
                    },
                    {
                        "name": "min_genes",
                        "source": {
                            "source_type": "workflow_input",
                            "input_name": "min_genes",
                        },
                    },
                ],
                "outputs": [
                    {
                        "name": "qa_report",
                        "kind": "artifact",
                        "artifact_type": "qa_report",
                        "schema_ref": "artifact_schema:qa_report@1.0.0",
                        "description": "Structured QA report emitted for review.",
                    }
                ],
                "prerequisites": ["preflight_check"],
                "retry_policy": {"max_attempts": 2, "backoff_seconds": 30},
                "failure_policy": "fail_workflow",
            },
        ],
    }


class TestWorkflowSpecs:
    def test_example_workflow_specs_validate_from_disk(self):
        example_paths = sorted(WORKFLOWS_DIR.glob("*.yaml"))
        assert example_paths, "expected authored workflow specs under workflows/"

        for path in example_paths:
            document = load_workflow_spec(path)
            assert isinstance(document, WorkflowSpecDocument)
            assert document.schema_version == WORKFLOW_SPEC_VERSION

    def test_authored_rnaseq_workflow_skeleton_declares_required_stages_and_outputs(self):
        document = load_workflow_spec(WORKFLOWS_DIR / "rnaseq_qc_de.yaml")

        assert document.workflow_id == "rnaseq_qc_de"
        assert [step.id for step in document.steps] == [
            "dataset_intake",
            "raw_qc",
            "aggregated_qc",
            "quantification",
            "differential_expression",
            "report_bundle",
        ]
        assert [definition.name for definition in document.required_inputs] == [
            "dataset_manifest",
            "condition_field",
            "baseline_condition",
            "comparison_condition",
        ]
        assert [output.name for output in document.outputs] == [
            "quantification_bundle",
            "differential_expression_bundle",
            "report_bundle_manifest",
            "qa_report",
        ]
        assert [hook.stage for hook in document.compliance_hooks] == ["before_execution"]
        assert {gate.id for gate in document.qc_gates} == {
            "dataset-manifest-required",
            "raw-qc-floor",
            "aggregated-qc-floor",
        }
        assert document.qc_gates[1].policy is not None
        assert document.qc_gates[1].policy.required_upstream_tools == ["fastqc"]
        assert document.qc_gates[1].policy.checks[0].metric_name == "min_per_base_quality"
        assert document.qc_gates[2].policy is not None
        assert document.qc_gates[2].policy.required_upstream_tools == ["fastqc", "multiqc"]
        assert document.qc_gates[2].policy.checks[0].metric_name == "fastqc_pass_rate"

    def test_rnaseq_example_manifest_and_workflow_plan_align_with_authored_contract(self):
        manifest = load_artifact_document(EXAMPLES_DIR / "rnaseq_dataset_manifest.yaml")
        workflow_plan = json.loads((EXAMPLES_DIR / "rnaseq_workflow_plan.json").read_text(encoding="utf-8"))
        workflow_spec = yaml.safe_load((WORKFLOWS_DIR / "rnaseq_qc_de.yaml").read_text(encoding="utf-8"))

        assert manifest.assay_type == "bulk_rna_seq"
        assert manifest.design.analysis_kind == "comparative"
        assert manifest.assay_extensions["workflow_stub"]["raw_qc"]["min_per_base_quality"] == 32.4
        assert manifest.assay_extensions["workflow_stub"]["aggregated_qc"]["fastqc_pass_rate"] == 1.0

        assert workflow_plan["artifact_type"] == "workflow_plan"
        assert workflow_plan["workflow_id"] == workflow_spec["workflow_id"] == "rnaseq_qc_de"
        assert [step["id"] for step in workflow_plan["steps"]] == [
            "dataset_intake",
            "compliance_preflight",
            "raw_qc",
            "aggregated_qc",
            "quantification",
            "differential_expression",
            "report_bundle",
        ]
        assert workflow_plan["inputs"]["dataset_manifest"] == "backend/artifacts/examples/rnaseq_dataset_manifest.yaml"
        assert workflow_plan["expected_outputs"][1]["path"].endswith(
            "outputs/generated/differential-expression/differential_expression_bundle.json"
        )
        assert workflow_plan["expected_outputs"][2]["path"].endswith(
            "outputs/generated/report-bundle/report_bundle_manifest.json"
        )

    def test_step_output_bindings_require_declared_prerequisite(self):
        payload = _base_payload()
        payload["steps"][1]["prerequisites"] = []

        with pytest.raises(ValueError, match="without declaring that step as a prerequisite"):
            validate_workflow_spec_payload(payload)

    def test_step_output_bindings_require_declared_outputs(self):
        payload = _base_payload()
        payload["steps"][1]["inputs"][0]["source"]["output_name"] = "missing_output"

        with pytest.raises(ValueError, match="undeclared step output"):
            validate_workflow_spec_payload(payload)

    def test_runtime_contract_requires_required_inputs_and_parameter_only_overrides(self):
        payload = _base_payload()
        payload["runtime"]["provided_inputs"] = ["min_genes"]

        with pytest.raises(ValueError, match="must include all required inputs"):
            validate_workflow_spec_payload(payload)

        payload = _base_payload()
        payload["runtime"]["allowed_parameter_overrides"] = ["dataset_manifest"]

        with pytest.raises(ValueError, match="parameter inputs"):
            validate_workflow_spec_payload(payload)

    def test_workflow_specs_fail_fast_on_cyclic_dependencies(self):
        payload = _base_payload()
        payload["steps"][0]["prerequisites"] = ["summarize_qc"]

        with pytest.raises(ValueError, match="contain a cycle"):
            validate_workflow_spec_payload(payload)

    def test_workflow_outputs_must_match_source_step_artifact_type(self):
        payload = _base_payload()
        payload["outputs"][0]["artifact_type"] = "workflow_run"
        payload["outputs"][0]["schema_ref"] = "artifact_schema:workflow_run@1.0.0"

        with pytest.raises(ValueError, match="same artifact_type"):
            validate_workflow_spec_payload(payload)

    def test_workflow_specs_reject_unsupported_schema_versions(self):
        payload = _base_payload()
        payload["schema_version"] = "9.9.9"

        with pytest.raises(ValueError, match="Unsupported workflow spec schema_version"):
            validate_workflow_spec_payload(payload)

    def test_before_execution_compliance_hooks_may_only_consume_workflow_inputs(self):
        payload = _base_payload()
        payload["compliance_hooks"][0]["inputs"] = [
            {
                "name": "validated_manifest",
                "source": {
                    "source_type": "step_output",
                    "step_id": "preflight_check",
                    "output_name": "validated_manifest",
                },
            }
        ]

        with pytest.raises(ValueError, match="before_execution' may only consume workflow inputs"):
            validate_workflow_spec_payload(payload)

    def test_after_step_compliance_hooks_can_consume_the_target_step_output(self):
        payload = _base_payload()
        payload["compliance_hooks"].append(
            {
                "id": "publish-review",
                "stage": "after_step",
                "tool": "compliance_preflight",
                "required": True,
                "step_id": "summarize_qc",
                "inputs": [
                    {
                        "name": "qa_report",
                        "source": {
                            "source_type": "step_output",
                            "step_id": "summarize_qc",
                            "output_name": "qa_report",
                        },
                    }
                ],
                "description": "Review the QA artifact emitted by the summarize step.",
            }
        )

        document = validate_workflow_spec_payload(payload)

        assert document.compliance_hooks[-1].step_id == "summarize_qc"

    def test_qc_gates_accept_inline_policy_definitions(self):
        payload = _base_payload()
        payload["qc_gates"].append(
            {
                "id": "evaluate-scrna-policy",
                "label": "Evaluate reusable single-cell QC policy",
                "when": "after_step",
                "target": {
                    "source_type": "step_output",
                    "step_id": "summarize_qc",
                    "output_name": "qa_report",
                },
                "failure_policy": "block",
                "policy": {
                    "policy_id": "scrna-default-qc",
                    "label": "Single-cell default QC policy",
                    "version": "1.0.0",
                    "assay_type": "scrna_seq",
                    "required_upstream_tools": ["multiqc"],
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
                                }
                            ],
                        }
                    ],
                },
                "description": "Evaluate a reusable single-cell QC policy after summarization.",
            }
        )

        document = validate_workflow_spec_payload(payload)

        assert document.qc_gates[-1].policy is not None
        assert document.qc_gates[-1].policy.policy_id == "scrna-default-qc"

    def test_python_executors_reject_invalid_module_paths(self):
        payload = _base_payload()
        payload["steps"][0]["executor"]["module"] = "workflows.runners.bad-module"

        with pytest.raises(ValueError, match="valid Python dotted identifiers"):
            validate_workflow_spec_payload(payload)

    def test_python_executors_reject_invalid_function_names(self):
        payload = _base_payload()
        payload["steps"][0]["executor"]["function"] = "run-job"

        with pytest.raises(ValueError, match="valid Python identifier"):
            validate_workflow_spec_payload(payload)
