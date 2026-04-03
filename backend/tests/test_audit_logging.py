import sys
from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from audit.store import query_audit_events


@pytest.fixture
def isolated_audit_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm
    original_memory_indexer = agent_manager.memory_indexer

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.llm = MagicMock()
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("workspace", "memory", "skills", "knowledge", "jobs"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm
        agent_manager.memory_indexer = original_memory_indexer


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


def test_save_file_rebuilds_memory_index_for_nested_memory_write(isolated_audit_state):
    from api.files import SaveRequest, save_file
    from graph.agent import agent_manager

    response = save_file(
        SaveRequest(path="memory/project/notes.md", content="# Project note\n")
    )

    assert response["saved"] is True
    agent_manager.memory_indexer.rebuild_index.assert_called_once()


def test_save_file_logs_invalid_typed_memory_write(isolated_audit_state):
    from api.files import SaveRequest, save_file
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        save_file(
            SaveRequest(
                path="memory/project/bad-note.md",
                content=(
                    "---\n"
                    "type: unsupported_type\n"
                    "name: Bad note\n"
                    "description: Invalid type should be rejected.\n"
                    "---\n"
                    "# Body\nShould not save.\n"
                ),
            )
        )

    assert exc_info.value.status_code == 400

    invalid_events = query_audit_events(
        isolated_audit_state,
        event_type="file_written",
        outcome="invalid_input",
    )

    assert any(
        event.details["path"] == "memory/project/bad-note.md"
        and "Typed memory frontmatter type must be one of" in event.details["reason"]
        for event in invalid_events
    )


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
