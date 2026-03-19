import json
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def isolated_chat_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.llm = MagicMock()

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm


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


def _stage_selected_workflow(base_dir: Path, *, include_manifest: bool = True) -> str | None:
    workflows_dir = base_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "workflows" / "rna-seq-qc.yaml", workflows_dir / "rna-seq-qc.yaml")

    if not include_manifest:
        return None

    manifest_relpath = "manifests/dataset_manifest.yaml"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml",
        manifest_path,
    )
    return manifest_relpath


@pytest.mark.asyncio
async def test_chat_stream_includes_structured_tool_result_and_persists_it(isolated_chat_state):
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
                "structured_payload": {"path": "memory/MEMORY.md", "content": "# Memory"},
                "artifact_refs": [{"path": "/tmp/memory/MEMORY.md", "label": "read_file_target"}],
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
            ChatRequest(message="Read memory", session_id=session_id, stream=True)
        )
        payloads = await _collect_sse_payloads(response)

    preflight_end = next(
        item
        for item in payloads
        if item["type"] == "tool_end" and item["tool"] == "compliance_preflight"
    )
    tool_start = next(
        item
        for item in payloads
        if item["type"] == "tool_start" and item["tool"] == "read_file"
    )
    tool_end = next(
        item
        for item in payloads
        if item["type"] == "tool_end" and item["tool"] == "read_file"
    )

    assert tool_start["run_id"] == "tool-run-1"
    assert tool_end["run_id"] == "tool-run-1"
    assert tool_end["result"]["tool_name"] == "read_file"
    assert tool_end["result"]["structured_payload"]["path"] == "memory/MEMORY.md"
    assert preflight_end["result"]["structured_payload"]["report"]["final_disposition"] == "allow"
    assert preflight_end["result"]["structured_payload"]["report"]["runtime_state"] == "allowed"
    assert preflight_end["result"]["structured_payload"]["audit_log_path"].endswith(
        "storage/compliance_audit/compliance_decisions.jsonl"
    )

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    tool_calls = assistant_messages[0]["tool_calls"]
    assert tool_calls[0]["tool"] == "compliance_preflight"
    assert tool_calls[1]["run_id"] == "tool-run-1"
    assert tool_calls[1]["result"]["tool_name"] == "read_file"


@pytest.mark.asyncio
async def test_chat_stream_includes_workflow_events_and_persists_them(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "workflow_start",
            "run_id": "run-20260319T120000Z-demo1234",
            "workflow_id": "rna-seq-qc",
            "workflow_name": "RNA-seq QC",
            "lifecycle_status": "created",
            "resumed": False,
            "run_record_path": "artifacts/rna-seq-qc/2026-03-19/run-20260319T120000Z-demo1234/run.json",
        }
        yield {
            "type": "workflow_step_start",
            "run_id": "run-20260319T120000Z-demo1234",
            "workflow_id": "rna-seq-qc",
            "step_id": "raw_qc",
            "step_label": "Run Raw QC",
            "status": "running",
            "executor_type": "python",
            "prerequisite_step_ids": [],
            "engine_name": None,
        }
        yield {
            "type": "workflow_artifact",
            "run_id": "run-20260319T120000Z-demo1234",
            "workflow_id": "rna-seq-qc",
            "scope": "step_output",
            "step_id": "raw_qc",
            "step_label": "Run Raw QC",
            "output_name": "qa_report",
            "artifact": {
                "artifact_type": "qa_report",
                "path": "artifacts/rna-seq-qc/2026-03-19/run-20260319T120000Z-demo1234/outputs/generated/raw_qc/qa_report.json",
                "id": "qa-report-demo",
                "run_id": "run-20260319T120000Z-demo1234",
            },
        }
        yield {
            "type": "workflow_step_end",
            "run_id": "run-20260319T120000Z-demo1234",
            "workflow_id": "rna-seq-qc",
            "step_id": "raw_qc",
            "step_label": "Run Raw QC",
            "status": "completed",
            "artifact_refs": [
                {
                    "artifact_type": "qa_report",
                    "path": "artifacts/rna-seq-qc/2026-03-19/run-20260319T120000Z-demo1234/outputs/generated/raw_qc/qa_report.json",
                    "id": "qa-report-demo",
                    "run_id": "run-20260319T120000Z-demo1234",
                }
            ],
            "warnings": [],
            "errors": [],
        }
        yield {
            "type": "workflow_done",
            "run_id": "run-20260319T120000Z-demo1234",
            "workflow_id": "rna-seq-qc",
            "lifecycle_status": "completed",
            "run_record_path": "artifacts/rna-seq-qc/2026-03-19/run-20260319T120000Z-demo1234/run.json",
            "completed_steps": 1,
            "total_steps": 1,
            "warning_count": 0,
        }
        yield {"type": "token", "content": "Workflow finished"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(message="Run the RNA-seq workflow", session_id=session_id, stream=True)
        )
        payloads = await _collect_sse_payloads(response)

    workflow_payloads = [item for item in payloads if item["type"].startswith("workflow_")]
    assert [item["type"] for item in workflow_payloads] == [
        "workflow_start",
        "workflow_step_start",
        "workflow_artifact",
        "workflow_step_end",
        "workflow_done",
    ]
    assert workflow_payloads[0]["contract_version"] == "workflow_event.v1"
    assert workflow_payloads[-1]["lifecycle_status"] == "completed"

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["workflow_events"][0]["type"] == "workflow_start"
    assert assistant_messages[0]["workflow_events"][-1]["type"] == "workflow_done"


@pytest.mark.asyncio
async def test_chat_stream_runs_selected_workflow_without_agent_stream(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    manifest_relpath = _stage_selected_workflow(isolated_chat_state)
    assert manifest_relpath is not None

    async def unexpected_astream(_message, _history):
        if False:
            yield {}
        raise AssertionError("selected workflow chat should bypass agent_manager.astream")

    with patch.object(agent_manager, "astream", unexpected_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Run the RNA-seq QC workflow with min_genes=250",
                session_id=session_id,
                stream=True,
                attached_identifiers=[manifest_relpath],
                selected_workflow="rna-seq-qc",
            )
        )
        payloads = await _collect_sse_payloads(response)

    workflow_payloads = [item for item in payloads if item["type"].startswith("workflow_")]
    assert workflow_payloads[0]["type"] == "workflow_start"
    assert workflow_payloads[-1]["type"] == "workflow_done"
    assert workflow_payloads[-1]["lifecycle_status"] == "completed"
    assert any(
        item["type"] == "workflow_step_start" and item["step_id"] == "preflight_check"
        for item in workflow_payloads
    )
    assert any(
        item["type"] == "workflow_step_end"
        and item["step_id"] == "summarize_qc"
        and item["status"] == "completed"
        for item in workflow_payloads
    )
    assert any(
        item["type"] == "workflow_artifact"
        and item["artifact"]["artifact_type"] == "qa_report"
        for item in workflow_payloads
    )
    assert any(
        item["type"] == "token"
        and "Workflow RNA Seq QC completed successfully." in item["content"]
        and "Completed steps: 2/2." in item["content"]
        for item in payloads
    )

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert any(call["tool"] == "compliance_preflight" for call in assistant_messages[0]["tool_calls"])
    assert assistant_messages[0]["workflow_events"][0]["type"] == "workflow_start"
    assert assistant_messages[0]["workflow_events"][-1]["lifecycle_status"] == "completed"


@pytest.mark.asyncio
async def test_chat_stream_blocks_selected_workflow_without_required_inputs(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    _stage_selected_workflow(isolated_chat_state, include_manifest=False)

    async def unexpected_astream(_message, _history):
        if False:
            yield {}
        raise AssertionError("selected workflow chat should bypass agent_manager.astream")

    with patch.object(agent_manager, "astream", unexpected_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Run the RNA-seq QC workflow",
                session_id=session_id,
                stream=True,
                selected_workflow="rna-seq-qc",
            )
        )
        payloads = await _collect_sse_payloads(response)

    workflow_payloads = [item for item in payloads if item["type"].startswith("workflow_")]
    assert [item["type"] for item in workflow_payloads] == [
        "workflow_start",
        "workflow_blocked",
        "workflow_done",
    ]
    assert workflow_payloads[1]["reason"].startswith(
        "Missing required workflow inputs: dataset_manifest."
    )
    assert workflow_payloads[-1]["lifecycle_status"] == "blocked"
    blocked_run_record = isolated_chat_state / workflow_payloads[0]["run_record_path"]
    assert blocked_run_record.exists()
    assert blocked_run_record == isolated_chat_state / workflow_payloads[-1]["run_record_path"]
    assert any(
        item["type"] == "token"
        and "Workflow RNA Seq QC blocked before execution:" in item["content"]
        for item in payloads
    )

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["workflow_events"][1]["type"] == "workflow_blocked"
    assert "blocked before execution" in assistant_messages[0]["content"]
