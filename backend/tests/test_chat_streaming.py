import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import HTTPException
from starlette.requests import Request

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


def _request(
    path: str,
    *,
    method: str = "POST",
    host: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
            "client": (host, 12345),
        }
    )


def _stage_selected_workflow(
    base_dir: Path,
    *,
    include_manifest: bool = True,
    include_array_input: bool = False,
) -> str | None:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    report_templates_dir = workflows_dir / "report_templates"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    runners_dir.mkdir(parents=True, exist_ok=True)
    report_templates_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for chat tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for chat tests."""\n', encoding="utf-8")
    shutil.copy2(REPO_ROOT / "workflows" / "rna-seq-qc.yaml", workflows_dir / "rna-seq-qc.yaml")
    shutil.copy2(REPO_ROOT / "workflows" / "runners" / "rna_seq_qc.py", runners_dir / "rna_seq_qc.py")
    shutil.copy2(
        REPO_ROOT / "workflows" / "report_templates" / "rna_seq_qc_summary.md.j2",
        report_templates_dir / "rna_seq_qc_summary.md.j2",
    )
    if include_array_input:
        spec_path = workflows_dir / "rna-seq-qc.yaml"
        spec_payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        assert isinstance(spec_payload, dict)
        optional_inputs = spec_payload.setdefault("optional_inputs", [])
        assert isinstance(optional_inputs, list)
        optional_inputs.append(
            {
                "name": "checklist_ids",
                "kind": "metadata",
                "data_type": "array",
                "default": [],
                "description": "Optional checklist identifiers for selected workflow chat tests.",
            }
        )
        runtime = spec_payload.setdefault("runtime", {})
        assert isinstance(runtime, dict)
        provided_inputs = runtime.setdefault("provided_inputs", [])
        assert isinstance(provided_inputs, list)
        provided_inputs.append("checklist_ids")
        spec_path.write_text(yaml.safe_dump(spec_payload, sort_keys=False), encoding="utf-8")

    if not include_manifest:
        return None

    manifest_relpath = "manifests/dataset_manifest.yaml"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml",
        manifest_path,
    )
    for relpath in (
        "data/norman/sample_sheet.tsv",
        "data/norman/counts.h5ad",
        "data/norman/metadata.tsv",
    ):
        target = base_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("placeholder\n", encoding="utf-8")
    return manifest_relpath


def _stage_protocol_skill(base_dir: Path, skill_name: str = "demo_protocol") -> str:
    skill_path = base_dir / "backend" / "skills" / skill_name / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        """---
name: demo_protocol
description: Demo protocol
---

# Demo Protocol

## Steps

1. Label the collection tubes for each sample.
2. Add lysis buffer to each labeled tube.
3. Incubate the tubes for the required hold time.
""",
        encoding="utf-8",
    )
    return skill_path.relative_to(base_dir).as_posix()


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
    assert tool_calls[1]["tool"] == "evidence_review_gate"
    assert tool_calls[2]["run_id"] == "tool-run-1"
    assert tool_calls[2]["result"]["tool_name"] == "read_file"


@pytest.mark.asyncio
async def test_chat_blocks_non_local_clients_without_bearer_token(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    with pytest.raises(HTTPException) as exc_info:
        await chat(
            ChatRequest(message="Read memory", session_id=session_id, stream=True),
            _request("/api/chat", host="10.0.0.8"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_allows_non_local_clients_with_execution_bearer_token(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    config_path = isolated_chat_state / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "production_hardening": {
                    "api": {
                        "allow_loopback_without_auth": False,
                        "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "Done"}
        yield {"type": "done"}

    headers = [(b"authorization", b"Bearer execution-token")]
    with patch("config._CONFIG_FILE", config_path), patch.dict(
        os.environ,
        {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
        clear=False,
    ), patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(message="Read memory", session_id=session_id, stream=True),
            _request("/api/chat", host="10.0.0.8", headers=headers),
        )
        payloads = await _collect_sse_payloads(response)

    assert any(item["type"] == "done" for item in payloads)


@pytest.mark.asyncio
async def test_chat_stream_records_observability_request_id_metrics_and_trace(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager
    from observability import query_metric_records, query_trace_records

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "Observable response."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(message="Observe this turn", session_id=session_id, stream=True)
        )
        payloads = await _collect_sse_payloads(response)

    done = next(item for item in payloads if item["type"] == "done")
    request_id = done["request_id"]
    assert request_id

    metrics = query_metric_records(isolated_chat_state, request_id=request_id, limit=10)
    assert {record.metric_name for record in metrics} == {"chat_latency_seconds"}
    assert {record.attributes["latency_scope"] for record in metrics} == {
        "user_visible",
        "backend_execution",
    }
    traces = query_trace_records(isolated_chat_state, request_id=request_id, limit=10)
    assert len(traces) == 1
    assert traces[0].span_name == "chat_turn"

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    user_messages = [msg for msg in history if msg["role"] == "user"]
    assert assistant_messages[0]["request_id"] == request_id
    assert user_messages[0]["request_id"] == request_id


@pytest.mark.asyncio
async def test_chat_requires_evidence_review_before_streaming_answer_tokens(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "Unreviewed preamble that should be withheld."}
        yield {
            "type": "tool_start",
            "tool": "evidence_review",
            "input": '{"question":"Summarize the evidence for TP53 stress response"}',
            "run_id": "tool-run-review-1",
        }
        yield {
            "type": "tool_end",
            "tool": "evidence_review",
            "output": "Reviewed 1 evidence card(s); support status: supported; confidence: medium.",
            "run_id": "tool-run-review-1",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "evidence_review",
                "summary": "Reviewed 1 evidence card(s); support status: supported; confidence: medium.",
                "structured_payload": {
                    "question": "Summarize the evidence for TP53 stress response",
                    "review_status": "supported",
                    "confidence": "medium",
                    "unsupported_claims_present": False,
                    "evidence_included": [
                        {
                            "artifact_type": "evidence_card",
                            "path": "artifacts/literature-retrieval/demo/evidence_card.yaml",
                        }
                    ],
                    "evidence_excluded": [],
                    "limitations": [],
                    "unresolved_conflicts": [],
                    "source_facts": [
                        {
                            "statement": "TP53 mediates a stress response.",
                            "claim_id": "claim-1",
                        }
                    ],
                    "synthesized_conclusions": [
                        {
                            "statement": "Retrieved evidence supports a medium-confidence conclusion.",
                            "support_status": "supported",
                            "confidence": "medium",
                        }
                    ],
                },
                "artifact_refs": [
                    {
                        "path": "artifacts/evidence-review/demo/evidence_review.json",
                        "artifact_type": "evidence_review",
                    }
                ],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {"review_status": "supported"},
                "source_payload": None,
            },
        }
        yield {"type": "token", "content": "Reviewed answer only."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Summarize the evidence for TP53 stress response",
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    token_text = " ".join(item["content"] for item in payloads if item["type"] == "token")
    assert "Unreviewed preamble" not in token_text
    assert "Reviewed answer only." in token_text

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["content"] == "Reviewed answer only."
    assert assistant_messages[0]["tool_calls"][1]["tool"] == "evidence_review_gate"
    assert assistant_messages[0]["tool_calls"][2]["tool"] == "evidence_review"


@pytest.mark.asyncio
async def test_chat_withholds_answer_when_required_review_never_completes(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "TP53 definitely controls stress response."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="What is the evidence for TP53 stress response?",
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    token_text = " ".join(item["content"] for item in payloads if item["type"] == "token")
    assert "TP53 definitely controls stress response." not in token_text
    assert "Evidence review is required before BioAPEX can provide a substantive answer" in token_text

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert "unsupported claims are being withheld" in assistant_messages[0]["content"]
    assert assistant_messages[0]["tool_calls"][1]["tool"] == "evidence_review_gate"


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
            "warnings": ["sample metadata normalized"],
            "warning_details": [
                {
                    "code": "normalized_metadata",
                    "field_path": "design.condition_summary",
                    "message": "Normalized whitespace in manifest metadata.",
                    "path": None,
                }
            ],
            "errors": [],
            "error_details": [],
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
    assert workflow_payloads[3]["warning_details"][0]["code"] == "normalized_metadata"
    workflow_request_ids = {item["request_id"] for item in workflow_payloads}
    assert len(workflow_request_ids) == 1

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["workflow_events"][0]["type"] == "workflow_start"
    assert assistant_messages[0]["workflow_events"][-1]["type"] == "workflow_done"
    assert assistant_messages[0]["workflow_events"][3]["warning_details"][0]["field_path"] == "design.condition_summary"
    assert {
        item["request_id"] for item in assistant_messages[0]["workflow_events"]
    } == workflow_request_ids


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
    workflow_request_ids = {item["request_id"] for item in workflow_payloads}
    assert workflow_payloads[0]["type"] == "workflow_start"
    assert workflow_payloads[-1]["type"] == "workflow_done"
    assert workflow_payloads[-1]["lifecycle_status"] == "completed"
    assert len(workflow_request_ids) == 1
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
    assert {
        item["request_id"] for item in assistant_messages[0]["workflow_events"]
    } == workflow_request_ids


@pytest.mark.asyncio
async def test_chat_stream_selected_workflow_carries_array_metadata_inputs(isolated_chat_state):
    from artifacts import load_artifact_document
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    manifest_relpath = _stage_selected_workflow(
        isolated_chat_state,
        include_array_input=True,
    )
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
                message=(
                    "Run the RNA-seq QC workflow with "
                    "checklist_ids=[miqe_qpcr_completeness, arrive_animal_study_reporting]"
                ),
                session_id=session_id,
                stream=True,
                attached_identifiers=[manifest_relpath],
                selected_workflow="rna-seq-qc",
            )
        )
        payloads = await _collect_sse_payloads(response)

    workflow_done = next(item for item in payloads if item["type"] == "workflow_done")
    run_document = load_artifact_document(isolated_chat_state / workflow_done["run_record_path"])

    assert run_document.lifecycle_status == "completed"
    assert run_document.parameters["checklist_ids"] == [
        "miqe_qpcr_completeness",
        "arrive_animal_study_reporting",
    ]


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
    workflow_request_ids = {item["request_id"] for item in workflow_payloads}
    assert [item["type"] for item in workflow_payloads] == [
        "workflow_start",
        "workflow_blocked",
        "workflow_done",
    ]
    assert len(workflow_request_ids) == 1
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
    assert {
        item["request_id"] for item in assistant_messages[0]["workflow_events"]
    } == workflow_request_ids


@pytest.mark.asyncio
async def test_chat_stream_routes_protocol_requests_to_protocol_executor(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    _stage_protocol_skill(isolated_chat_state)

    async def unexpected_astream(_message, _history):
        if False:
            yield {}
        raise AssertionError("protocol execution chat should bypass agent_manager.astream")

    with patch.object(agent_manager, "astream", unexpected_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Walk me through this protocol step by step using demo_protocol for sample-001.",
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    tool_starts = [item for item in payloads if item["type"] == "tool_start"]
    assert [item["tool"] for item in tool_starts] == [
        "compliance_preflight",
        "protocol_executor",
    ]
    assert not any(
        item["type"] == "tool_end" and item["tool"] == "evidence_review_gate"
        for item in payloads
    )
    protocol_end = next(
        item for item in payloads if item["type"] == "tool_end" and item["tool"] == "protocol_executor"
    )
    assert protocol_end["result"]["status"] == "success"
    assert protocol_end["result"]["structured_payload"]["source"]["kind"] == "skill"
    protocol_run_path = protocol_end["result"]["structured_payload"]["protocol_run"]["artifact_path"]
    assert (isolated_chat_state / protocol_run_path).is_file()
    assert any(
        item["type"] == "token"
        and "Protocol execution mode started from `demo_protocol`." in item["content"]
        for item in payloads
    )

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert [call["tool"] for call in assistant_messages[0]["tool_calls"]] == [
        "compliance_preflight",
        "protocol_executor",
    ]


@pytest.mark.asyncio
async def test_chat_stream_blocks_protocol_execution_without_explicit_source(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def unexpected_astream(_message, _history):
        if False:
            yield {}
        raise AssertionError("protocol execution chat should bypass agent_manager.astream")

    with patch.object(agent_manager, "astream", unexpected_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Walk me through this protocol step by step.",
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    protocol_end = next(
        item for item in payloads if item["type"] == "tool_end" and item["tool"] == "protocol_executor"
    )
    assert protocol_end["result"]["status"] == "error"
    assert protocol_end["result"]["outcome"] == "invalid_input"
    assert protocol_end["result"]["structured_payload"]["source"]["kind"] == "request_note"
    assert any(
        item["type"] == "token"
        and "no explicit source protocol or skill was provided" in item["content"].lower()
        for item in payloads
    )
    assert not any(
        item["type"] == "tool_end" and item["tool"] == "evidence_review_gate"
        for item in payloads
    )


@pytest.mark.asyncio
async def test_chat_stream_blocks_unreadable_protocol_source_file(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    binary_relpath = "backend/artifacts/examples/binary_protocol.bin"
    binary_path = isolated_chat_state / binary_relpath
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_bytes(b"\xff\xfe\x00\x01")

    async def unexpected_astream(_message, _history):
        if False:
            yield {}
        raise AssertionError("protocol execution chat should bypass agent_manager.astream")

    with patch.object(agent_manager, "astream", unexpected_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message=(
                    "Walk me through this protocol step by step using "
                    f"{binary_relpath}."
                ),
                attached_identifiers=[binary_relpath],
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    protocol_end = next(
        item for item in payloads if item["type"] == "tool_end" and item["tool"] == "protocol_executor"
    )
    assert protocol_end["result"]["status"] == "error"
    assert protocol_end["result"]["outcome"] == "invalid_input"
    assert protocol_end["result"]["structured_payload"]["source"]["kind"] == "document"
    assert protocol_end["result"]["structured_payload"]["source"]["readable"] is False
    assert protocol_end["result"]["structured_payload"]["source"]["read_error"] == "unicode_decode_error"
    assert any(
        item["type"] == "token"
        and "could not be decoded as utf-8 text" in item["content"].lower()
        for item in payloads
    )
    assert not any(
        item["type"] == "tool_end" and item["tool"] == "evidence_review_gate"
        for item in payloads
    )


@pytest.mark.asyncio
async def test_chat_protocol_requests_still_stop_at_compliance_before_protocol_executor(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    _stage_protocol_skill(isolated_chat_state)

    async def unexpected_astream(_message, _history):
        if False:
            yield {}
        raise AssertionError("blocked protocol execution should bypass agent_manager.astream")

    with patch.object(agent_manager, "astream", unexpected_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message=(
                    "Walk me through this protocol step by step using demo_protocol to "
                    "culture SARS-CoV-2 in the lab."
                ),
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    assert [item["tool"] for item in payloads if item["type"] == "tool_start"] == ["compliance_preflight"]
    assert not any(
        item["type"] == "tool_end" and item["tool"] == "protocol_executor"
        for item in payloads
    )

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert [call["tool"] for call in assistant_messages[0]["tool_calls"]] == ["compliance_preflight"]
    assert "blocked" in assistant_messages[0]["content"].lower()
