"""Tests for the internal DAG workflow runner MVP."""

import json
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import load_artifact_document, resolve_artifact_path  # noqa: E402
from artifacts.registry import rebuild_artifact_registry  # noqa: E402
from artifacts.schemas import SCHEMA_PACK_VERSION  # noqa: E402
from workflow_runner import InternalDAGRunner  # noqa: E402
from workflow_specs import WORKFLOW_SPEC_VERSION, validate_workflow_spec_payload  # noqa: E402


def _write_runner_module(base_dir: Path, module_name: str, source: str) -> str:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    runners_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for tests."""\n', encoding="utf-8")
    (runners_dir / f"{module_name}.py").write_text(source, encoding="utf-8")
    for loaded in (f"workflows.runners.{module_name}", "workflows.runners", "workflows"):
        sys.modules.pop(loaded, None)
    return f"workflows.runners.{module_name}"


def _runtime_contract(provided_inputs: list[str]) -> dict:
    return {
        "provided_inputs": provided_inputs,
        "allowed_parameter_overrides": [name for name in provided_inputs if name != "sample_id"],
        "generated_state": [
            "run_id",
            "created_at",
            "resolved_input_paths",
            "step_statuses",
            "artifact_paths",
        ],
        "state_artifact": "workflow_run",
        "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
    }


def _qa_report_output(source_step_id: str, source_output_name: str) -> dict:
    return {
        "name": "qa_report",
        "kind": "artifact",
        "artifact_type": "qa_report",
        "schema_ref": "artifact_schema:qa_report@1.0.0",
        "description": "Structured QA report for the workflow run.",
        "source": {
            "step_id": source_step_id,
            "output_name": source_output_name,
        },
    }


class TestInternalDAGRunner:
    def test_runner_executes_steps_in_dependency_order_and_persists_outputs(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "order_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "execution_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def prepare(inputs, context):
    _log(context, "prepare")
    return {"prepared_value": {"seed": inputs["seed"], "doubled": inputs["seed"] * 2}}


def summarize(inputs, context):
    _log(context, "summarize")
    doubled = inputs["prepared_value"]["doubled"]
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [f"doubled={doubled}"],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-order-demo",
                "version": "1.0.0",
                "name": "Runner Order Demo",
                "purpose": "Verify deterministic DAG execution and artifact persistence.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("summarize", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "prepare",
                        "label": "Prepare Values",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "prepare",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Prepared numeric payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "summarize",
                        "label": "Summarize Results",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "summarize",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "prepare",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["prepare"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(spec, {"seed": 7})

        assert result.run.lifecycle_status == "completed"
        assert [record.id for record in result.run.steps] == ["prepare", "summarize"]
        assert [record.status for record in result.run.steps] == ["completed", "completed"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == [
            "prepare",
            "summarize",
        ]

        persisted = load_artifact_document(result.artifact_path)
        assert persisted.lifecycle_status == "completed"
        assert persisted.outputs[0].artifact_type == "qa_report"
        assert resolve_artifact_path(tmp_path, persisted.outputs[0].path).exists()
        assert (result.run_dir / "outputs" / "generated" / "prepare" / "prepared_value.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "summarize" / "resolved_outputs.json").exists()
        assert (result.run_dir / "qa_report.json").exists()

    def test_runner_emits_structured_workflow_events_for_successful_run(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "stream_demo",
            """
def prepare(inputs, _context):
    return {"prepared_value": {"seed": inputs["seed"], "doubled": inputs["seed"] * 2}}


def summarize(inputs, _context):
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [f"doubled={inputs['prepared_value']['doubled']}"],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-stream-demo",
                "version": "1.0.0",
                "name": "Runner Stream Demo",
                "purpose": "Verify workflow lifecycle event emission for successful runs.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("summarize", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "prepare",
                        "label": "Prepare Values",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "prepare",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Prepared numeric payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "summarize",
                        "label": "Summarize Results",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "summarize",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "prepare",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["prepare"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 11}, event_callback=events.append)

        assert result.run.lifecycle_status == "completed"
        assert [event["type"] for event in events] == [
            "workflow_start",
            "workflow_artifact",
            "workflow_step_start",
            "workflow_artifact",
            "workflow_step_end",
            "workflow_step_start",
            "workflow_artifact",
            "workflow_step_end",
            "workflow_artifact",
            "workflow_done",
        ]
        assert events[0]["contract_version"] == "workflow_event.v1"
        assert events[1]["scope"] == "run_record"
        assert events[3]["artifact"]["artifact_type"] == "workflow_value"
        assert events[6]["artifact"]["artifact_type"] == "qa_report"
        assert events[8]["scope"] == "workflow_output"
        assert events[-1]["lifecycle_status"] == "completed"
        assert events[-1]["completed_steps"] == 2
        assert events[-1]["total_steps"] == 2

    def test_runner_propagates_failures_to_descendants(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "failure_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "execution_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def explode(_inputs, context):
    _log(context, "explode")
    raise RuntimeError("boom")


def never(_inputs, context):
    _log(context, "never")
    return {"qa_report": {"overall_status": "passed", "failed_checks": [], "warnings": [], "missing_artifacts": [], "recommended_remediation": [], "checklist_artifacts": []}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-failure-demo",
                "version": "1.0.0",
                "name": "Runner Failure Demo",
                "purpose": "Verify failure propagation through explicit prerequisites.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("never", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "explode",
                        "label": "Explode",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "explode",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Unreachable prepared payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "never",
                        "label": "Never Execute",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "never",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "explode",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["explode"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(spec, {"seed": 7})

        assert result.run.lifecycle_status == "failed"
        assert [record.status for record in result.run.steps] == ["failed", "blocked"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == ["explode"]
        assert "boom" in result.run.steps[0].errors[0]
        assert "Blocked by prerequisite explode" in result.run.steps[1].errors[0]

    def test_runner_resumes_from_persisted_state_without_rerunning_completed_steps(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "resume_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "execution_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def prepare(inputs, context):
    _log(context, "prepare")
    return {"prepared_value": {"seed": inputs["seed"], "doubled": inputs["seed"] * 2}}


def summarize(inputs, context):
    _log(context, "summarize")
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [f"doubled={inputs['prepared_value']['doubled']}"],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-resume-demo",
                "version": "1.0.0",
                "name": "Runner Resume Demo",
                "purpose": "Verify pause and resume behavior from persisted state.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("summarize", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "prepare",
                        "label": "Prepare Values",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "prepare",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Prepared numeric payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "summarize",
                        "label": "Summarize Results",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "summarize",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "prepare",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["prepare"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        paused = runner.run(spec, {"seed": 5}, step_limit=1)

        assert paused.run.lifecycle_status == "waiting"
        assert [record.status for record in paused.run.steps] == ["completed", "created"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == ["prepare"]

        resumed = runner.run(spec, run_dir=paused.run_dir)

        assert resumed.resumed is True
        assert resumed.run.lifecycle_status == "completed"
        assert [record.status for record in resumed.run.steps] == ["completed", "completed"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == [
            "prepare",
            "summarize",
        ]

    def test_runner_executes_external_engine_steps_and_persists_value_outputs(self, tmp_path):
        command = " ".join(
            [
                shlex.quote(sys.executable),
                "-c",
                shlex.quote(
                    "import os, sys; print(sys.argv[1]); print(os.environ['BIOAPEX_INPUT_SAMPLE_ID'])"
                ),
                "{sample_id}",
            ]
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "external-engine-demo",
                "version": "1.0.0",
                "name": "External Engine Demo",
                "purpose": "Verify the external command executor path for the workflow runner.",
                "engine": "external_workflow_adapter_v1",
                "required_inputs": [
                    {
                        "name": "sample_id",
                        "kind": "metadata",
                        "data_type": "string",
                        "description": "Sample identifier forwarded to the launch command.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["sample_id"]),
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Captured external execution bundle.",
                        "source": {
                            "step_id": "launch_job",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch_job",
                        "label": "Launch External Job",
                        "executor": {
                            "executor_type": "external_engine",
                            "engine_name": "command",
                            "entrypoint": "workflows/engines/demo/main.sh",
                            "command": command,
                        },
                        "inputs": [
                            {
                                "name": "sample_id",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "sample_id",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Structured external command result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(spec, {"sample_id": "sample-001"})

        assert result.run.lifecycle_status == "completed"
        assert result.run.steps[0].status == "completed"
        assert result.run.outputs[0].artifact_type == "workflow_value"

        output_path = resolve_artifact_path(tmp_path, result.run.outputs[0].path)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["value"]["returncode"] == 0
        assert payload["value"]["argv"][-1] == "sample-001"
        assert payload["value"]["stdout"].splitlines() == ["sample-001", "sample-001"]
        assert "BIOAPEX_INPUT_SAMPLE_ID" in payload["value"]["environment_keys"]

    def test_runner_blocks_before_execution_when_qc_gate_fails(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "qc_gate_demo",
            """
import json


def launch(_inputs, context):
    path = context.base_dir / "execution_log.json"
    path.write_text(json.dumps(["launch"]), encoding="utf-8")
    return {"submission_bundle": {"status": "submitted"}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "qc-gate-demo",
                "version": "1.0.0",
                "name": "QC Gate Demo",
                "purpose": "Verify that before_execution QC gates block execution when inputs are absent.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest required by a QC preflight gate.",
                    }
                ],
                "runtime": {
                    "provided_inputs": ["seed", "dataset_manifest"],
                    "allowed_parameter_overrides": ["seed"],
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
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [
                    {
                        "id": "dataset-manifest-required",
                        "label": "Dataset manifest is required before launch",
                        "when": "before_execution",
                        "target": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                        "failure_policy": "block",
                        "description": "Block execution until the manifest is available.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 1})

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "created"
        assert "QC gate dataset-manifest-required failed" in result.run.warnings[0]
        assert not (tmp_path / "execution_log.json").exists()

    def test_runner_blocks_before_execution_when_required_compliance_hook_stops_run(self, tmp_path, monkeypatch):
        module_name = _write_runner_module(
            tmp_path,
            "compliance_hook_demo",
            """
import json


def launch(_inputs, context):
    path = context.base_dir / "execution_log.json"
    path.write_text(json.dumps(["launch"]), encoding="utf-8")
    return {"submission_bundle": {"status": "submitted"}}
""",
        )
        manifest_path = tmp_path / "manifests" / "dataset_manifest.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("dataset_id: ds-1\n", encoding="utf-8")

        def _blocked_preflight(_base_dir, _payload):
            artifact_relpath = "artifacts/compliance-preflight/2026-03-19/run-20260319T000000Z-abcdef12/compliance_report.json"
            artifact_path = tmp_path / artifact_relpath
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                report=SimpleNamespace(
                    id="compliance-report-demo",
                    run_id="run-20260319T000000Z-abcdef12",
                ),
                artifact_relpath=artifact_relpath,
                tool_summary="Approval required before execution can continue.",
                warning_text=None,
                should_continue=False,
            )

        monkeypatch.setattr("compliance.preflight.run_compliance_preflight", _blocked_preflight)

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "compliance-hook-demo",
                "version": "1.0.0",
                "name": "Compliance Hook Demo",
                "purpose": "Verify that required compliance hooks block execution before any step runs.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest passed into the compliance hook.",
                    }
                ],
                "optional_inputs": [],
                "runtime": {
                    "provided_inputs": ["dataset_manifest"],
                    "allowed_parameter_overrides": [],
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
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [],
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
                        "description": "Run required compliance screening before execution.",
                    }
                ],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
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
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"dataset_manifest": "manifests/dataset_manifest.yaml"})

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "created"
        assert not (tmp_path / "execution_log.json").exists()
        assert any(ref.artifact_type == "compliance_report" for ref in result.run.related_artifacts)
        assert "Compliance hook privacy-preflight blocked execution" in result.run.warnings[0]

    def test_runner_emits_blocked_and_done_events_for_blocked_preflight(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "blocked_stream_demo",
            """
def launch(inputs, _context):
    return {"submission_bundle": {"dataset_manifest": inputs["dataset_manifest"]}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "blocked-stream-demo",
                "version": "1.0.0",
                "name": "Blocked Stream Demo",
                "purpose": "Verify blocked workflow event emission before step execution.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest required by the gate.",
                    }
                ],
                "optional_inputs": [],
                "runtime": {
                    "provided_inputs": ["dataset_manifest"],
                    "allowed_parameter_overrides": [],
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
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [
                    {
                        "id": "dataset-manifest-required",
                        "label": "Dataset manifest required",
                        "when": "before_execution",
                        "target": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                        "failure_policy": "block",
                        "description": "Block execution while required manifest info is missing.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
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
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec,
            {"dataset_manifest": "manifests/missing-dataset-manifest.yaml"},
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert [event["type"] for event in events] == [
            "workflow_start",
            "workflow_artifact",
            "workflow_blocked",
            "workflow_done",
        ]
        assert events[2]["blocking_source"] == "qc_gate"
        assert events[2]["stage"] == "before_execution"
        assert "dataset-manifest-required" in events[2]["reason"]
        assert events[3]["lifecycle_status"] == "blocked"

    def test_blocked_dataset_intake_failures_preserve_structured_issue_details(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "blocked_step_demo",
            """
from dataset_intake import ensure_valid_dataset_intake_manifest


def validate(inputs, context):
    ensure_valid_dataset_intake_manifest(context.base_dir, inputs["dataset_manifest"])
""",
        )
        manifest_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-blocked-step-v1",
            "run_id": "run-20260319T000000Z-deadbeef",
            "created_at": "2026-03-19T00:00:00Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "blocked-step-demo",
                "experiment_type": "scrna_seq",
                "condition_summary": "single-condition pilot",
                "analysis_kind": "descriptive",
                "timepoints": ["baseline"],
                "factors": ["condition"],
            },
            "source_files": ["data/counts.h5ad"],
        }
        manifest_path = tmp_path / "manifests" / "dataset_manifest.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
        source_file = tmp_path / "data" / "counts.h5ad"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("placeholder\n", encoding="utf-8")

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "blocked-step-warning-demo",
                "version": "1.0.0",
                "name": "Blocked Step Warning Demo",
                "purpose": "Verify blocked step failures preserve the blocking reason on the run record.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest passed into the dataset intake gate.",
                    }
                ],
                "optional_inputs": [],
                "runtime": {
                    "provided_inputs": ["dataset_manifest"],
                    "allowed_parameter_overrides": [],
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
                        "name": "blocked_payload",
                        "kind": "value",
                        "description": "Unreached output reserved for spec validation.",
                        "source": {
                            "step_id": "preflight_check",
                            "output_name": "blocked_payload",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "preflight_check",
                        "label": "Validate Dataset Intake",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "validate",
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
                                "name": "blocked_payload",
                                "kind": "value",
                                "description": "Unreached output reserved for spec validation.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "block_workflow",
                    }
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec,
            {"dataset_manifest": "manifests/dataset_manifest.yaml"},
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "blocked"
        assert len(result.run.warnings) == 1
        assert "sample_sheet_path" in result.run.warnings[0]
        assert result.run.steps[0].errors == result.run.warnings
        assert result.run.warning_details[0].field_path == "sample_sheet_path"
        assert result.run.warning_details[0].code == "missing_field"
        assert result.run.steps[0].error_details[0].field_path == "sample_sheet_path"
        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["issue_details"][0]["field_path"] == "sample_sheet_path"
        assert blocked_event["issue_details"][0]["code"] == "missing_field"
        step_end_event = next(event for event in events if event["type"] == "workflow_step_end")
        assert step_end_event["error_details"][0]["field_path"] == "sample_sheet_path"
        assert step_end_event["error_details"][0]["code"] == "missing_field"
        run_document = load_artifact_document(result.artifact_path)
        assert run_document.warning_details[0].field_path == "sample_sheet_path"
        assert run_document.steps[0].error_details[0].field_path == "sample_sheet_path"

    def test_runner_uses_slugified_workflow_identity_in_workflow_run_artifact(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "slug_demo",
            """
def launch(inputs, _context):
    return {"submission_bundle": {"seed": inputs["seed"]}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "demo_workflow",
                "version": "1.0.0",
                "name": "Slug Demo",
                "purpose": "Verify workflow run documents use the path slug expected by the registry.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 2})
        snapshot = rebuild_artifact_registry(tmp_path)

        assert result.run.workflow.slug == "demo-workflow"
        workflow_run_record = next(record for record in snapshot.records if record.artifact_type == "workflow_run")
        assert workflow_run_record.status == "valid"

    def test_runner_does_not_materialize_publish_ready_artifacts_when_before_publish_blocks(self, tmp_path, monkeypatch):
        module_name = _write_runner_module(
            tmp_path,
            "before_publish_demo",
            """
def emit(_inputs, _context):
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )

        def _blocked_preflight(_base_dir, _payload):
            artifact_relpath = "artifacts/compliance-preflight/2026-03-19/run-20260319T000000Z-abcdef12/compliance_report.json"
            artifact_path = tmp_path / artifact_relpath
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                report=SimpleNamespace(
                    id="compliance-report-before-publish",
                    run_id="run-20260319T000000Z-abcdef12",
                ),
                artifact_relpath=artifact_relpath,
                tool_summary="Publish review failed.",
                warning_text=None,
                should_continue=False,
            )

        monkeypatch.setattr("compliance.preflight.run_compliance_preflight", _blocked_preflight)

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "before-publish-demo",
                "version": "1.0.0",
                "name": "Before Publish Demo",
                "purpose": "Verify that required before_publish hooks stop stable output publication.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("emit", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [
                    {
                        "id": "publish-review",
                        "stage": "before_publish",
                        "tool": "compliance_preflight",
                        "required": True,
                        "inputs": [
                            {
                                "name": "qa_report",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "emit",
                                    "output_name": "qa_report",
                                },
                            }
                        ],
                        "description": "Block publication until compliance review passes.",
                    }
                ],
                "steps": [
                    {
                        "id": "emit",
                        "label": "Emit QA Report",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "emit",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 3})

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "completed"
        assert (result.run_dir / "outputs" / "generated" / "emit" / "qa_report.json").exists()
        assert not (result.run_dir / "qa_report.json").exists()
        assert result.run.outputs[0].path.endswith("outputs/generated/emit/qa_report.json")
