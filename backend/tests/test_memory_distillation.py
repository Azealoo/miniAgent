from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_types import parse_memory_document
from graph.session_manager import SessionManager
from runtime import memory_distillation
from runtime.memory_distillation import (
    clear_failed_distillations,
    distill_request_memory,
    distill_session,
    get_failed_distillations,
)


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


# --------------------------------------------------------------------- #
# Post-session distillation (distill_session)                           #
# --------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_failed_distillations():
    clear_failed_distillations()
    yield
    clear_failed_distillations()


def _split_frontmatter(content: str) -> tuple[dict, str]:
    assert content.startswith("---\n"), "expected YAML frontmatter"
    _, rest = content.split("---\n", 1)
    fm_text, body = rest.split("\n---\n", 1)
    return yaml.safe_load(fm_text), body


def _populate_two_turn_session(tmp_path):
    sm = SessionManager(base_dir=tmp_path)
    session_id = sm.create_session()

    sm.save_message(session_id, "user", "Summarize the BRCA1 follow-up.", request_id="turn-1")
    sm.save_message(
        session_id,
        "assistant",
        "Review the evidence card and rerun the DEG checklist for BRCA1.",
        tool_calls=[
            {
                "tool": "evidence_review",
                "input": '{"question":"BRCA1"}',
                "output": "Reviewed.",
                "result": {"structured_payload": {"review_status": "supported"}},
            }
        ],
        request_id="turn-1",
        blocks=[
            {
                "type": "retrieval",
                "query": "BRCA1 notes",
                "results": [
                    {
                        "text": "Follow-up lives in memory/project/brca1.md.",
                        "score": 0.9,
                        "source": "memory/project/brca1.md#follow-up",
                    }
                ],
            },
            _verification_block("Verifier: pass — aligned with project notes."),
            {
                "type": "text",
                "text": "Review the evidence card and rerun the DEG checklist for BRCA1.",
            },
        ],
    )

    sm.save_message(session_id, "user", "Now capture a quick draft.", request_id="turn-2")
    sm.save_message(
        session_id,
        "assistant",
        "Draft captured; awaiting verifier signoff.",
        request_id="turn-2",
        blocks=[{"type": "text", "text": "Draft captured; awaiting verifier signoff."}],
    )

    return sm, session_id


async def test_distill_session_writes_post_session_frontmatter(tmp_path):
    sm, session_id = _populate_two_turn_session(tmp_path)

    result = await distill_session(
        session_id, base_dir=tmp_path, session_manager=sm
    )

    assert result.outcome == "written"
    target = tmp_path / "memory" / "agent" / f"session-{session_id}.md"
    assert target.exists()

    frontmatter, body = _split_frontmatter(target.read_text(encoding="utf-8"))
    assert frontmatter["type"] == "session_distillation"
    assert frontmatter["session_id"] == session_id
    assert frontmatter["turn_ids"] == ["turn-1", "turn-2"]
    assert frontmatter["source"] == "post_session_hook"
    assert isinstance(frontmatter["written_at"], str)
    assert frontmatter["written_at"].endswith("+00:00")
    assert "name" in frontmatter and session_id in frontmatter["name"]
    assert "description" in frontmatter

    # Every turn shows up in the body with its request id as a heading.
    assert "## Turn turn-1" in body
    assert "## Turn turn-2" in body
    # Deterministic aggregation surfaces retrieval + evidence review + tool usage
    # for verified turn-1 and still records unverified turn-2 via user/assistant lines.
    assert "memory/project/brca1.md#follow-up" in body
    assert "Evidence review: supported" in body
    assert "evidence_review" in body


async def test_distill_session_is_idempotent_overwrite(tmp_path):
    sm, session_id = _populate_two_turn_session(tmp_path)

    first = await distill_session(
        session_id, base_dir=tmp_path, session_manager=sm
    )
    target = tmp_path / "memory" / "agent" / f"session-{session_id}.md"
    first_content = target.read_text(encoding="utf-8")

    second = await distill_session(
        session_id, base_dir=tmp_path, session_manager=sm
    )
    second_content = target.read_text(encoding="utf-8")

    assert first.outcome == "written"
    assert second.outcome == "written"
    assert first_content == second_content, "distill_session must be byte-idempotent"
    assert first_content.count("## Turn turn-1") == 1
    assert first_content.count("## Turn turn-2") == 1


async def test_distill_session_overwrites_prior_per_turn_file(tmp_path):
    """distill_request_memory during a session and distill_session at end
    target the same file; the post-session overwrite must fully replace any
    accumulated per-turn content (single-writer-at-end invariant)."""
    sm, session_id = _populate_two_turn_session(tmp_path)

    # Simulate distill_request_memory having run during the session.
    target = tmp_path / "memory" / "agent" / f"session-{session_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\ntype: project_fact\nname: prior\ndescription: prior\n---\n"
        "# Prior per-turn note\n\n## Turn turn-1\n- stale content\n",
        encoding="utf-8",
    )

    await distill_session(session_id, base_dir=tmp_path, session_manager=sm)

    content = target.read_text(encoding="utf-8")
    assert "stale content" not in content
    assert "# Post-Session Distillation" in content
    assert "type: session_distillation" in content


async def test_distill_session_handles_session_without_request_ids(tmp_path):
    sm = SessionManager(base_dir=tmp_path)
    session_id = sm.create_session()
    sm.save_message(session_id, "user", "Legacy turn with no request id.")

    result = await distill_session(
        session_id, base_dir=tmp_path, session_manager=sm
    )

    assert result.outcome == "written"
    target = tmp_path / "memory" / "agent" / f"session-{session_id}.md"
    frontmatter, body = _split_frontmatter(target.read_text(encoding="utf-8"))
    assert frontmatter["turn_ids"] == []
    assert "No turns with a persisted request id" in body


def test_fire_post_session_distillation_records_failure(tmp_path, monkeypatch):
    async def _exploding_distill(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(memory_distillation, "distill_session", _exploding_distill)

    memory_distillation.fire_post_session_distillation("00000000-0000-4000-8000-000000000001")

    assert "00000000-0000-4000-8000-000000000001" in get_failed_distillations()


def test_session_distillation_is_registered_typed_memory_type():
    from graph.memory_types import TYPED_MEMORY_TYPE_VALUES

    assert "session_distillation" in TYPED_MEMORY_TYPE_VALUES

    doc = parse_memory_document(
        "memory/agent/session-test.md",
        "---\n"
        "type: session_distillation\n"
        'name: "Post-session distillation for abc"\n'
        'description: "Consolidated durable facts."\n'
        "session_id: abc\n"
        "turn_ids: []\n"
        "written_at: 2026-01-01T00:00:00+00:00\n"
        "source: post_session_hook\n"
        "---\n"
        "body\n",
    )
    assert doc.metadata is not None
    assert doc.metadata.memory_type == "session_distillation"
