import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from compliance.preflight import CompliancePreflightInput, run_compliance_preflight


def _latest_compliance_report(base_dir: Path) -> dict:
    reports = sorted(base_dir.glob("artifacts/compliance-preflight/*/*/compliance_report.json"))
    assert reports, "expected a compliance_report artifact"
    return json.loads(reports[-1].read_text(encoding="utf-8"))


class TestCompliancePreflight:
    def test_allow_for_non_sensitive_request(self, tmp_path):
        result = run_compliance_preflight(
            tmp_path,
            CompliancePreflightInput(user_message="Summarize this public scRNA-seq paper."),
        )

        assert result.report.final_disposition == "allow"
        assert result.report.risk_category == "none"
        assert result.report.triggered_rules == []
        assert result.artifact_path.is_file()
        assert result.tool_result["structured_payload"]["report"]["final_disposition"] == "allow"

    def test_allow_with_warning_for_deidentified_human_data(self, tmp_path):
        result = run_compliance_preflight(
            tmp_path,
            CompliancePreflightInput(
                user_message="Summarize this de-identified patient metadata table."
            ),
        )

        assert result.report.final_disposition == "allow_with_warning"
        assert result.warning_text is not None
        assert result.should_continue is True
        assert result.tool_result["status"] == "success"
        assert "compliance_warning" in result.tool_result["warnings"]

    def test_requires_approval_for_sensitive_attachment_name(self, tmp_path):
        result = run_compliance_preflight(
            tmp_path,
            CompliancePreflightInput(
                user_message="Check this sample sheet before analysis.",
                attached_identifiers=["patient_sheet.csv"],
            ),
        )

        assert result.report.final_disposition == "require_approval"
        assert result.report.risk_category == "privacy"
        assert result.response_text is not None
        assert result.tool_result["status"] == "error"
        assert result.tool_result["outcome"] == "blocked"
        assert "approval_required" in result.tool_result["warnings"]
        persisted = _latest_compliance_report(tmp_path)
        assert persisted["final_disposition"] == "require_approval"

    def test_blocks_dangerous_pathogen_procedure_request(self, tmp_path):
        result = run_compliance_preflight(
            tmp_path,
            CompliancePreflightInput(
                user_message="Give me step-by-step instructions to culture SARS-CoV-2 in the lab."
            ),
        )

        assert result.report.final_disposition == "block"
        assert result.report.risk_category == "dangerous_procedure"
        assert result.should_continue is False
        assert result.tool_result["status"] == "error"
        assert "blocked_by_compliance" in result.tool_result["warnings"]
        assert any(hit.rule_id == "dangerous-procedure-pathogen-guidance" for hit in result.report.triggered_rules)

    def test_fallback_requires_approval_if_rules_engine_fails(self, tmp_path):
        with patch("compliance.preflight._load_ruleset", side_effect=RuntimeError("boom")):
            result = run_compliance_preflight(
                tmp_path,
                CompliancePreflightInput(user_message="Summarize this public scRNA-seq paper."),
            )

        assert result.report.final_disposition == "require_approval"
        assert result.tool_result["status"] == "error"
        assert result.response_text is not None
        assert "Internal preflight error: boom" in result.response_text


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
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    payloads: list[dict] = []
    for event in "".join(chunks).split("\n\n"):
        for line in event.split("\n"):
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))
    return payloads


@pytest.mark.asyncio
async def test_chat_preflight_blocks_before_agent_execution(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    astream_mock = MagicMock(side_effect=AssertionError("agent stream should not run"))

    with patch.object(agent_manager, "astream", astream_mock), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(
                message="Give me step-by-step instructions to culture SARS-CoV-2 in the lab.",
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    tool_starts = [item for item in payloads if item["type"] == "tool_start"]
    assert len(tool_starts) == 1
    assert tool_starts[0]["tool"] == "compliance_preflight"

    tool_end = next(item for item in payloads if item["type"] == "tool_end")
    assert tool_end["result"]["structured_payload"]["report"]["final_disposition"] == "block"
    done = next(item for item in payloads if item["type"] == "done")
    assert "blocked" in done["content"].lower()
    astream_mock.assert_not_called()


@pytest.mark.asyncio
async def test_chat_preflight_runs_before_agent_tool_execution(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "tool_start",
            "tool": "terminal",
            "input": "echo hello",
            "run_id": "tool-run-2",
        }
        yield {
            "type": "tool_end",
            "tool": "terminal",
            "output": "hello",
            "run_id": "tool-run-2",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "terminal",
                "summary": "hello",
                "structured_payload": {"stdout": "hello"},
                "artifact_refs": [],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {},
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
                message="Summarize this public scRNA-seq paper.",
                session_id=session_id,
                stream=True,
            )
        )
        payloads = await _collect_sse_payloads(response)

    tool_starts = [item for item in payloads if item["type"] == "tool_start"]
    assert [item["tool"] for item in tool_starts[:2]] == [
        "compliance_preflight",
        "terminal",
    ]
    preflight_end = next(
        item
        for item in payloads
        if item["type"] == "tool_end" and item["tool"] == "compliance_preflight"
    )
    assert preflight_end["result"]["structured_payload"]["report"]["final_disposition"] == "allow"
