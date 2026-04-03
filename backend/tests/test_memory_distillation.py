from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_types import parse_memory_document
from graph.session_manager import SessionManager
from runtime.memory_distillation import distill_request_memory


def _verification_block(summary: str = "Verifier verdict: pass. Looks good.") -> dict:
    return {
        "type": "verification",
        "summary": summary,
        "verdict": "pass",
        "verification": {
            "verdict": "pass",
            "summary": "Looks good.",
        },
    }


def test_distill_request_memory_writes_runtime_owned_note_from_verified_turn(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path)
    session_id = session_manager.create_session()
    request_id = "request-1"

    data = session_manager._read(session_id)
    data["compressed_context"] = "Follow up on the QC report before rerunning the BRCA1 analysis."
    session_manager._write(session_id, data)

    session_manager.save_message(
        session_id,
        "user",
        "What should we do next for the BRCA1 follow-up?",
        request_id=request_id,
    )
    session_manager.save_message(
        session_id,
        "assistant",
        "Review the evidence card first, then rerun the DEG checklist for BRCA1 follow-up.",
        tool_calls=[
            {
                "tool": "evidence_review",
                "input": '{"question":"BRCA1 follow-up"}',
                "output": "Reviewed evidence.",
                "result": {
                    "structured_payload": {"review_status": "supported"},
                },
            }
        ],
        request_id=request_id,
        blocks=[
            {
                "type": "retrieval",
                "query": "Find BRCA1 notes",
                "results": [
                    {
                        "text": "BRCA1 follow-up notes say to check the evidence card first.",
                        "score": 0.91,
                        "source": "memory/project/brca1.md#follow-up",
                    }
                ],
            },
            _verification_block(),
            {
                "type": "text",
                "text": "Review the evidence card first, then rerun the DEG checklist for BRCA1 follow-up.",
            },
        ],
    )

    result = distill_request_memory(
        base_dir=tmp_path,
        session_manager=session_manager,
        session_id=session_id,
        request_id=request_id,
    )

    assert result.outcome == "written"
    assert result.path == f"memory/agent/session-{session_id}.md"
    target = tmp_path / "memory" / "agent" / f"session-{session_id}.md"
    content = target.read_text(encoding="utf-8")
    parsed = parse_memory_document("memory/agent/test.md", content)
    assert parsed.metadata is not None
    assert parsed.metadata.memory_type == "project_fact"
    assert f"## Turn {request_id}" in parsed.body
    assert "Evidence review: supported" in parsed.body
    assert "memory/project/brca1.md#follow-up" in parsed.body
    assert "Follow up on the QC report before rerunning the BRCA1 analysis." in parsed.body


def test_distill_request_memory_leaves_memory_index_file_unchanged(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path)
    session_id = session_manager.create_session()
    request_id = "request-index"

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    index_path = memory_dir / "MEMORY.md"
    original_index = "# Long-term Memory\n\nIndex only.\n"
    index_path.write_text(original_index, encoding="utf-8")

    session_manager.save_message(
        session_id,
        "user",
        "Capture the verified follow-up.",
        request_id=request_id,
    )
    session_manager.save_message(
        session_id,
        "assistant",
        "Verified follow-up: review the runbook before the next rerun.",
        request_id=request_id,
        blocks=[
            _verification_block(),
            {
                "type": "text",
                "text": "Verified follow-up: review the runbook before the next rerun.",
            },
        ],
    )

    result = distill_request_memory(
        base_dir=tmp_path,
        session_manager=session_manager,
        session_id=session_id,
        request_id=request_id,
    )

    assert result.outcome == "written"
    assert result.path == f"memory/agent/session-{session_id}.md"
    assert index_path.read_text(encoding="utf-8") == original_index
    assert (tmp_path / result.path).exists()


def test_distill_request_memory_skips_turns_that_already_wrote_memory_directly(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path)
    session_id = session_manager.create_session()
    request_id = "request-2"

    session_manager.save_message(
        session_id,
        "user",
        "Save this memory note.",
        request_id=request_id,
    )
    session_manager.save_message(
        session_id,
        "assistant",
        "Saved the memory note directly.",
        tool_calls=[
            {
                "tool": "write_file",
                "input": "memory/project/brca1.md",
                "output": "Wrote memory/project/brca1.md (42 characters).",
                "result": {
                    "status": "success",
                    "outcome": "success",
                    "structured_payload": {"path": "memory/project/brca1.md"},
                },
            }
        ],
        request_id=request_id,
        blocks=[
            _verification_block(),
            {"type": "text", "text": "Saved the memory note directly."},
        ],
    )

    result = distill_request_memory(
        base_dir=tmp_path,
        session_manager=session_manager,
        session_id=session_id,
        request_id=request_id,
    )

    assert result.outcome == "skipped"
    assert result.reason == "memory_already_written"
    assert not (tmp_path / "memory" / "agent" / f"session-{session_id}.md").exists()


def test_distill_request_memory_skips_duplicate_request_entries(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path)
    session_id = session_manager.create_session()
    request_id = "request-3"

    session_manager.save_message(
        session_id,
        "user",
        "Summarize the verified plan.",
        request_id=request_id,
    )
    session_manager.save_message(
        session_id,
        "assistant",
        "The verified plan is to inspect the runbook and then update the checklist.",
        request_id=request_id,
        blocks=[
            _verification_block(),
            {
                "type": "text",
                "text": "The verified plan is to inspect the runbook and then update the checklist.",
            },
        ],
    )

    first = distill_request_memory(
        base_dir=tmp_path,
        session_manager=session_manager,
        session_id=session_id,
        request_id=request_id,
    )
    second = distill_request_memory(
        base_dir=tmp_path,
        session_manager=session_manager,
        session_id=session_id,
        request_id=request_id,
    )

    assert first.outcome == "written"
    assert second.outcome == "skipped"
    assert second.reason == "request_already_distilled"

    content = (tmp_path / "memory" / "agent" / f"session-{session_id}.md").read_text(
        encoding="utf-8"
    )
    assert content.count(f"## Turn {request_id}") == 1


def test_distill_request_memory_skips_unverified_turns(tmp_path):
    session_manager = SessionManager(base_dir=tmp_path)
    session_id = session_manager.create_session()
    request_id = "request-4"

    session_manager.save_message(
        session_id,
        "user",
        "Give me a quick draft.",
        request_id=request_id,
    )
    session_manager.save_message(
        session_id,
        "assistant",
        "Here is a draft without verifier signoff.",
        request_id=request_id,
        blocks=[{"type": "text", "text": "Here is a draft without verifier signoff."}],
    )

    result = distill_request_memory(
        base_dir=tmp_path,
        session_manager=session_manager,
        session_id=session_id,
        request_id=request_id,
    )

    assert result.outcome == "skipped"
    assert result.reason == "turn_not_distillable"
