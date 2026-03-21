import json
import sys
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from audit.store import append_chat_request_event, hash_text, query_audit_events
from workflow_runner import InternalDAGRunner
from workflow_specs import WORKFLOW_SPEC_VERSION, validate_workflow_spec_payload


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
        "allowed_parameter_overrides": list(provided_inputs),
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


async def _collect_sse_payloads(response) -> list[dict]:
    chunks: list[str] = []
    try:
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk.decode("utf-8"))
            else:
                chunks.append(chunk)
    finally:
        close_iterator = getattr(response.body_iterator, "aclose", None)
        if close_iterator is not None:
            await close_iterator()

    payloads: list[dict] = []
    for event in "".join(chunks).split("\n\n"):
        for line in event.split("\n"):
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))
    return payloads


@pytest.fixture
def isolated_audit_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.llm = MagicMock()

    for relpath in ("workspace", "memory", "skills", "knowledge", "jobs"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm


def test_audit_route_returns_redacted_chat_request(isolated_audit_state):
    from api.audit import list_audit_events

    append_chat_request_event(
        isolated_audit_state,
        session_id="session-audit-1",
        message="Review patient metadata table before analysis.",
        attached_identifiers=["patient_sheet.csv"],
        selected_workflow="rna-seq-qc",
    )

    response = list_audit_events(
        event_type="chat_request_received",
        session_id="session-audit-1",
        limit=10,
    )

    assert len(response["events"]) == 1
    event = response["events"][0]
    assert event["event_type"] == "chat_request_received"
    assert event["details"]["request_summary"]["message_sha256"] == hash_text(
        "Review patient metadata table before analysis."
    )
    assert "patient_sheet.csv" not in json.dumps(event)
    assert "Review patient metadata table before analysis." not in json.dumps(event)
    assert response["retention_policy"]["rotation_strategy"] == "daily_jsonl"
    assert response["retention_policy"]["automatic_deletion"] is False


@pytest.mark.asyncio
async def test_chat_logs_request_tool_and_compliance_events(isolated_audit_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "tool_start",
            "tool": "read_file",
            "input": "memory/MEMORY.md",
            "run_id": "tool-run-1",
        }
        yield {
            "type": "tool_end",
            "tool": "read_file",
            "output": "# Memory",
            "run_id": "tool-run-1",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "read_file",
                "summary": "# Memory",
                "structured_payload": {"path": "memory/MEMORY.md"},
                "artifact_refs": [{"path": str(isolated_audit_state / "memory" / "MEMORY.md")}],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {"requested_path": "memory/MEMORY.md"},
                "source_payload": None,
            },
        }
        yield {"type": "token", "content": "Done"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Read memory",
                session_id=session_id,
                stream=True,
            )
        )
        await _collect_sse_payloads(response)

    request_events = query_audit_events(
        isolated_audit_state,
        event_type="chat_request_received",
        session_id=session_id,
    )
    tool_events = query_audit_events(
        isolated_audit_state,
        event_type="tool_invoked",
        session_id=session_id,
        tool_name="read_file",
    )
    compliance_events = query_audit_events(
        isolated_audit_state,
        event_type="compliance_decision",
        session_id=session_id,
    )

    assert len(request_events) == 1
    assert request_events[0].details["request_summary"]["message_sha256"] == hash_text("Read memory")
    assert len(tool_events) == 1
    assert tool_events[0].outcome == "success"
    assert tool_events[0].artifact_paths == ["memory/MEMORY.md"]
    assert tool_events[0].details["tool_run_id"] == "tool-run-1"
    assert len(compliance_events) == 1
    assert compliance_events[0].outcome == "allow"


def test_save_file_logs_written_and_blocked_attempts(isolated_audit_state):
    from api.files import SaveRequest, save_file
    from fastapi import HTTPException

    response = save_file(SaveRequest(path="memory/MEMORY.md", content="# Updated\n"))
    assert response["saved"] is True

    with pytest.raises(HTTPException):
        save_file(SaveRequest(path="artifacts/demo/run.json", content="{}\n"))

    written_events = query_audit_events(
        isolated_audit_state,
        event_type="file_written",
        outcome="written",
    )
    blocked_events = query_audit_events(
        isolated_audit_state,
        event_type="file_written",
        outcome="blocked",
    )

    assert any(event.details["path"] == "memory/MEMORY.md" for event in written_events)
    assert any(event.details["path"] == "artifacts/demo/run.json" for event in blocked_events)


def test_save_file_succeeds_when_audit_write_fails(isolated_audit_state):
    from api.files import SaveRequest, save_file

    with patch("audit.store.audit_log_path", side_effect=OSError("disk full")):
        response = save_file(SaveRequest(path="memory/audit-fail-open.md", content="still saved\n"))

    assert response["saved"] is True
    assert (isolated_audit_state / "memory" / "audit-fail-open.md").read_text(encoding="utf-8") == "still saved\n"
    assert query_audit_events(
        isolated_audit_state,
        event_type="file_written",
        outcome="written",
    ) == []


def test_write_file_tool_logs_written_and_blocked_attempts(isolated_audit_state):
    from tools.write_file_tool import WriteFileTool

    tool = WriteFileTool(root_dir=str(isolated_audit_state))
    summary, artifact = tool._run("memory/notes.txt", "hello world")
    assert "Wrote memory/notes.txt" in summary
    assert artifact["status"] == "success"

    blocked_summary, blocked_artifact = tool._run("../secret.txt", "nope")
    assert blocked_artifact["outcome"] == "blocked"
    assert "Path traversal" in blocked_summary

    events = query_audit_events(
        isolated_audit_state,
        event_type="file_written",
        tool_name="write_file",
        limit=10,
    )

    assert any(event.outcome == "written" and event.details["path"] == "memory/notes.txt" for event in events)
    assert any(event.outcome == "blocked" and "Path traversal" in event.details["reason"] for event in events)


def test_slurm_submission_logs_job_event(isolated_audit_state):
    from tools.slurm_tool import SlurmTool

    script = isolated_audit_state / "jobs" / "demo.sh"
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")

    completed = MagicMock()
    completed.stdout = "Submitted batch job 12345\n"
    completed.stderr = ""
    completed.returncode = 0

    tool = SlurmTool(base_dir=str(isolated_audit_state))
    with patch("tools.slurm_tool.subprocess.run", return_value=completed):
        summary, artifact = tool._run(
            action="submit",
            script_path="jobs/demo.sh",
            run_id="run-20260320T120000Z-deadbeef",
            resource_request={"cpus": 4, "memory": "32G", "wall_time": "02:00:00"},
        )

    events = query_audit_events(
        isolated_audit_state,
        event_type="job_submitted",
        job_id="12345",
    )

    assert "Submitted Slurm job 12345" in summary
    assert artifact["structured_payload"]["job_id"] == "12345"
    assert len(events) == 1
    assert events[0].run_id == "run-20260320T120000Z-deadbeef"
    assert events[0].details["resource_request"]["cpus"] == 4
    assert events[0].external_systems == ["slurm"]


def test_job_submission_logs_session_id_when_available(isolated_audit_state):
    from tools.slurm_tool import submit_slurm_job

    script = isolated_audit_state / "jobs" / "session-demo.sh"
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")

    completed = MagicMock()
    completed.stdout = "Submitted batch job 67890\n"
    completed.stderr = ""
    completed.returncode = 0

    with patch("tools.slurm_tool.subprocess.run", return_value=completed):
        operation = submit_slurm_job(
            base_dir=isolated_audit_state,
            session_id="session-slurm-1",
            run_id="run-20260320T120000Z-deadbeef",
            run_relative_dir=PurePosixPath("artifacts/slurm/2026-03-20/run-20260320T120000Z-deadbeef"),
            script_path="jobs/session-demo.sh",
            resource_request={"cpus": 1, "memory": "2G", "wall_time": "00:10:00"},
        )

    events = query_audit_events(
        isolated_audit_state,
        event_type="job_submitted",
        job_id="67890",
    )

    assert operation.artifact.job_id == "67890"
    assert len(events) == 1
    assert events[0].session_id == "session-slurm-1"


def test_workflow_run_logs_start_finish_and_provenance_export(isolated_audit_state):
    module_name = _write_runner_module(
        isolated_audit_state,
        "audit_demo",
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
            "workflow_id": "audit-workflow-demo",
            "version": "1.0.0",
            "name": "Audit Workflow Demo",
            "purpose": "Verify workflow audit logging.",
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

    result = InternalDAGRunner(isolated_audit_state).run(
        spec,
        {"seed": 7},
        session_id="session-workflow-1",
    )

    workflow_events = query_audit_events(
        isolated_audit_state,
        workflow_id="audit-workflow-demo",
        limit=20,
    )

    started = next(event for event in workflow_events if event.event_type == "workflow_started")
    finished = next(event for event in workflow_events if event.event_type == "workflow_finished")
    export_events = [event for event in workflow_events if event.event_type == "export_generated"]
    provenance_event = next(
        event for event in export_events if event.details.get("export_type") == "provenance_bundle"
    )

    assert result.run.lifecycle_status == "completed"
    assert started.session_id == "session-workflow-1"
    assert started.run_id == result.run.run_id
    assert finished.session_id == "session-workflow-1"
    assert finished.outcome == "completed"
    assert finished.artifact_paths[0].endswith("/run.json")
    assert provenance_event.session_id == "session-workflow-1"
    assert any(path.endswith("/prov.json") for path in provenance_event.artifact_paths)
