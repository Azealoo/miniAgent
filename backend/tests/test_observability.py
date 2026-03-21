import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from observability import (  # noqa: E402
    append_metric_record,
    append_trace_record,
    build_observability_overview,
    chat_span_id,
    query_metric_records,
    query_trace_records,
    workflow_span_id,
)
from workflow_runner import InternalDAGRunner  # noqa: E402
from workflow_specs import WORKFLOW_SPEC_VERSION, validate_workflow_spec_payload  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    }


def test_observability_store_appends_queries_and_summarizes_records(tmp_path):
    append_metric_record(
        tmp_path,
        metric_name="chat_latency_seconds",
        metric_kind="duration",
        value=0.25,
        unit="seconds",
        request_id="request-1",
        session_id="session-1",
        trace_id="request-1",
        span_id=chat_span_id("request-1"),
        attributes={"latency_scope": "user_visible"},
    )
    append_metric_record(
        tmp_path,
        metric_name="failure_rate",
        metric_kind="rate",
        value=0.0,
        unit="ratio",
        run_id="run-1",
        workflow_id="demo-workflow",
        trace_id="trace-run-1",
        span_id=workflow_span_id("run-1"),
    )
    append_trace_record(
        tmp_path,
        trace_id="request-1",
        span_id=chat_span_id("request-1"),
        span_name="chat_turn",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        status="ok",
        request_id="request-1",
        session_id="session-1",
    )

    metrics = query_metric_records(tmp_path, request_id="request-1", limit=10)
    assert len(metrics) == 1
    assert metrics[0].metric_name == "chat_latency_seconds"
    traces = query_trace_records(tmp_path, request_id="request-1", limit=10)
    assert len(traces) == 1
    assert traces[0].span_name == "chat_turn"

    overview = build_observability_overview(tmp_path, days=1)
    assert overview["chat_responsiveness"]["user_visible_latency_seconds"]["count"] == 1
    assert overview["workflow_delivery"]["failure_rate"]["average"] == 0.0
    assert overview["dashboards"]


def test_workflow_runner_records_observability_metrics_traces_and_summary_metrics(tmp_path):
    review_source_path = tmp_path / "inputs" / "review_source.json"
    review_source_path.parent.mkdir(parents=True, exist_ok=True)
    review_source_path.write_text(
        (REPO_ROOT / "backend" / "artifacts" / "examples" / "evidence_review.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    module_name = _write_runner_module(
        tmp_path,
        "observability_demo",
        """
import json
import time
from pathlib import Path

def emit_review(inputs, _context):
    time.sleep(0.05)
    review_payload = json.loads(Path(inputs["review_source"]).read_text(encoding="utf-8"))
    return {"review": review_payload}
""",
    )

    spec = validate_workflow_spec_payload(
        {
            "schema_version": WORKFLOW_SPEC_VERSION,
            "kind": "workflow_spec",
            "workflow_id": "observability-demo",
            "version": "1.0.0",
            "name": "Observability Demo",
            "purpose": "Verify structured observability emission for workflow runs.",
            "engine": "internal_dag_runner_v1",
            "required_inputs": [
                {
                    "name": "review_source",
                    "kind": "artifact",
                    "artifact_type": "evidence_review",
                    "schema_ref": "artifact_schema:evidence_review@1.0.0",
                    "description": "Source evidence review artifact for the test workflow.",
                }
            ],
            "optional_inputs": [],
            "runtime": _runtime_contract(["review_source"]),
            "outputs": [
                {
                    "name": "review_output",
                    "kind": "artifact",
                    "artifact_type": "evidence_review",
                    "schema_ref": "artifact_schema:evidence_review@1.0.0",
                    "description": "Persisted evidence review output.",
                    "source": {
                        "step_id": "review",
                        "output_name": "review",
                    },
                }
            ],
            "qc_gates": [],
            "compliance_hooks": [],
            "steps": [
                {
                    "id": "review",
                    "label": "Emit Review",
                    "executor": {
                        "executor_type": "python",
                        "module": module_name,
                        "function": "emit_review",
                    },
                    "inputs": [
                        {
                            "name": "review_source",
                            "source": {
                                "source_type": "workflow_input",
                                "input_name": "review_source",
                            },
                        }
                    ],
                    "outputs": [
                        {
                            "name": "review",
                            "kind": "artifact",
                            "artifact_type": "evidence_review",
                            "schema_ref": "artifact_schema:evidence_review@1.0.0",
                            "description": "Evidence review artifact emitted for observability coverage tests.",
                        }
                    ],
                    "prerequisites": [],
                    "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                    "failure_policy": "fail_workflow",
                }
            ],
        }
    )

    result = InternalDAGRunner(tmp_path).run(
        spec,
        {"review_source": review_source_path.relative_to(tmp_path).as_posix()},
        request_id="request-observability-1",
    )

    metrics = query_metric_records(tmp_path, run_id=result.run.run_id, limit=50)
    metric_names = {record.metric_name for record in metrics}
    assert {
        "workflow_duration_seconds",
        "step_duration_seconds",
        "failure_rate",
        "block_rate",
        "qc_pass_rate",
        "evidence_coverage_rate",
    }.issubset(metric_names)

    evidence_metric = next(record for record in metrics if record.metric_name == "evidence_coverage_rate")
    assert evidence_metric.value == 1.0
    assert evidence_metric.request_id == "request-observability-1"
    step_duration_metric = next(record for record in metrics if record.metric_name == "step_duration_seconds")
    workflow_duration_metric = next(record for record in metrics if record.metric_name == "workflow_duration_seconds")
    assert step_duration_metric.value > 0.0
    assert workflow_duration_metric.value > 0.0

    traces = query_trace_records(tmp_path, run_id=result.run.run_id, limit=20)
    assert any(record.span_name == "workflow_run" for record in traces)
    assert any(record.span_name == "workflow_step" for record in traces)
    assert any(record.span_name == "workflow_run" and record.duration_seconds > 0.0 for record in traces)
    assert any(record.span_name == "workflow_step" and record.duration_seconds > 0.0 for record in traces)

    summary_metrics = {(metric.stage, metric.metric_name) for metric in result.run.summary_metrics}
    assert ("observability", "workflow_duration_seconds") in summary_metrics
    assert ("observability", "evidence_coverage_rate") in summary_metrics


def test_sync_observability_summary_metrics_preserves_terminal_duration_on_rerun(tmp_path):
    review_source_path = tmp_path / "inputs" / "review_source.json"
    review_source_path.parent.mkdir(parents=True, exist_ok=True)
    review_source_path.write_text(
        (REPO_ROOT / "backend" / "artifacts" / "examples" / "evidence_review.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    module_name = _write_runner_module(
        tmp_path,
        "observability_preserve_duration",
        """
import json
import time
from pathlib import Path

def emit_review(inputs, _context):
    time.sleep(0.05)
    review_payload = json.loads(Path(inputs["review_source"]).read_text(encoding="utf-8"))
    return {"review": review_payload}
""",
    )

    spec = validate_workflow_spec_payload(
        {
            "schema_version": WORKFLOW_SPEC_VERSION,
            "kind": "workflow_spec",
            "workflow_id": "observability-preserve-duration",
            "version": "1.0.0",
            "name": "Observability Preserve Duration",
            "purpose": "Verify terminal observability metrics stay stable on re-sync.",
            "engine": "internal_dag_runner_v1",
            "required_inputs": [
                {
                    "name": "review_source",
                    "kind": "artifact",
                    "artifact_type": "evidence_review",
                    "schema_ref": "artifact_schema:evidence_review@1.0.0",
                    "description": "Source evidence review artifact for the test workflow.",
                }
            ],
            "optional_inputs": [],
            "runtime": _runtime_contract(["review_source"]),
            "outputs": [
                {
                    "name": "review_output",
                    "kind": "artifact",
                    "artifact_type": "evidence_review",
                    "schema_ref": "artifact_schema:evidence_review@1.0.0",
                    "description": "Persisted evidence review output.",
                    "source": {
                        "step_id": "review",
                        "output_name": "review",
                    },
                }
            ],
            "qc_gates": [],
            "compliance_hooks": [],
            "steps": [
                {
                    "id": "review",
                    "label": "Emit Review",
                    "executor": {
                        "executor_type": "python",
                        "module": module_name,
                        "function": "emit_review",
                    },
                    "inputs": [
                        {
                            "name": "review_source",
                            "source": {
                                "source_type": "workflow_input",
                                "input_name": "review_source",
                            },
                        }
                    ],
                    "outputs": [
                        {
                            "name": "review",
                            "kind": "artifact",
                            "artifact_type": "evidence_review",
                            "schema_ref": "artifact_schema:evidence_review@1.0.0",
                            "description": "Evidence review artifact emitted for observability coverage tests.",
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
    result = runner.run(
        spec,
        {"review_source": review_source_path.relative_to(tmp_path).as_posix()},
    )
    original_run = result.run.model_copy(deep=True)
    original_duration = next(
        metric.value
        for metric in original_run.summary_metrics
        if metric.metric_name == "workflow_duration_seconds"
    )

    time.sleep(1.1)
    rerun_synced = runner._sync_observability_summary_metrics(original_run)
    rerun_duration = next(
        metric.value
        for metric in rerun_synced.summary_metrics
        if metric.metric_name == "workflow_duration_seconds"
    )

    assert original_run.lifecycle_status in {"completed", "failed", "blocked"}
    assert original_duration > 0.0
    assert rerun_duration == original_duration
