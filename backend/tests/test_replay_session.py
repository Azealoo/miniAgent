"""Tests for ``backend.scripts.replay_session``.

Covers:
- Successful replay of a recorded two-turn session exits 0 with no diff.
- A mutated recording produces diffs, exits 1, and writes a report.
- Helper-agent turns (plan + verification) re-derive plan/verification blocks.
- A missing session file exits 2.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _fresh_replay_module():
    # The module stashes BACKEND_ROOT on sys.path at import time and is safe
    # to import repeatedly.
    module = importlib.import_module("scripts.replay_session")
    return importlib.reload(module)


@pytest.fixture
def isolated_agent_manager(monkeypatch, tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    monkeypatch.setattr(agent_manager, "base_dir", tmp_path, raising=False)
    monkeypatch.setattr(
        agent_manager, "session_manager", SessionManager(base_dir=tmp_path), raising=False
    )
    monkeypatch.setattr(agent_manager, "llm", MagicMock(), raising=False)
    monkeypatch.setattr(agent_manager, "memory_indexer", None, raising=False)
    return agent_manager


def _seed_recorded_session(
    session_id: str,
    archive_dir: Path,
    messages: list[dict],
) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{session_id}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "title": "recorded",
                "created_at": 1.0,
                "updated_at": 2.0,
                "compressed_context": "",
                "compressed_archive_index": [],
                "messages": messages,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _simple_two_turn_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": "Summarize status.",
            "request_id": "rec-req-1",
        },
        {
            "role": "assistant",
            "content": "All good.",
            "request_id": "rec-req-1",
            "blocks": [{"type": "text", "text": "All good."}],
        },
        {
            "role": "user",
            "content": "Read memory.",
            "request_id": "rec-req-2",
        },
        {
            "role": "assistant",
            "content": "Done",
            "request_id": "rec-req-2",
            "blocks": [
                {
                    "type": "tool_use",
                    "tool": "read_file",
                    "input": "memory/MEMORY.md",
                    "run_id": "rec-run-1",
                },
                {
                    "type": "tool_result",
                    "tool": "read_file",
                    "output": "# Memory",
                    "run_id": "rec-run-1",
                    "result": {
                        "status": "success",
                        "tool_name": "read_file",
                        "summary": "# Memory",
                    },
                },
                {"type": "text", "text": "Done"},
            ],
        },
    ]


def test_replay_matches_recording_exits_zero(tmp_path, isolated_agent_manager):
    replay = _fresh_replay_module()
    session_id = "11111111-1111-1111-1111-111111111111"
    archive = tmp_path / "archive"
    _seed_recorded_session(session_id, archive, _simple_two_turn_messages())

    out_dir = tmp_path / "out"
    rc = replay.main(
        [
            session_id,
            "--archive-dir",
            str(archive),
            "--output-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    reports = list((out_dir / session_id).glob("*/diff.json"))
    assert len(reports) == 1
    diff = json.loads(reports[0].read_text(encoding="utf-8"))
    assert diff == []


def test_replay_detects_drift_exits_one(tmp_path, isolated_agent_manager):
    replay = _fresh_replay_module()
    session_id = "22222222-2222-2222-2222-222222222222"
    archive = tmp_path / "archive"

    # Inject drift: the recorded `content` string diverges from what its
    # blocks would produce. Replay reconstructs events from blocks, so the
    # replayed message will carry the block-derived content and diff against
    # the recorded content field.
    recorded_messages = copy.deepcopy(_simple_two_turn_messages())
    recorded_messages[1]["content"] = "content that diverges from the block text"
    _seed_recorded_session(session_id, archive, recorded_messages)

    out_dir = tmp_path / "out"
    rc = replay.main(
        [
            session_id,
            "--archive-dir",
            str(archive),
            "--output-dir",
            str(out_dir),
        ]
    )

    assert rc == 1
    diff_path = next((out_dir / session_id).glob("*/diff.json"))
    diff = json.loads(diff_path.read_text(encoding="utf-8"))
    assert diff, "expected non-empty diff for mutated recording"


def test_allow_diff_forces_zero_exit(tmp_path, isolated_agent_manager):
    replay = _fresh_replay_module()
    session_id = "33333333-3333-3333-3333-333333333333"
    archive = tmp_path / "archive"
    recorded_messages = copy.deepcopy(_simple_two_turn_messages())
    recorded_messages[1]["content"] = "content that diverges from the block text"
    _seed_recorded_session(session_id, archive, recorded_messages)

    out_dir = tmp_path / "out"
    rc = replay.main(
        [
            session_id,
            "--archive-dir",
            str(archive),
            "--output-dir",
            str(out_dir),
            "--allow-diff",
        ]
    )
    assert rc == 0


def test_missing_session_file_exits_two(tmp_path, isolated_agent_manager, capsys):
    replay = _fresh_replay_module()
    rc = replay.main(
        [
            "44444444-4444-4444-4444-444444444444",
            "--archive-dir",
            str(tmp_path / "does-not-exist"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    assert rc == 2


def test_helper_agent_blocks_replay_as_tool_ends(tmp_path, isolated_agent_manager):
    replay = _fresh_replay_module()
    session_id = "55555555-5555-5555-5555-555555555555"
    archive = tmp_path / "archive"

    plan_result = {
        "contract_version": "tool_result.v1",
        "tool_name": "plan_agent",
        "summary": "Planner produced 1 step.",
        "structured_payload": {
            "agent_type": "plan",
            "plan": {"goal": "do a thing", "steps": [{"step_id": "s1", "intent": "x"}]},
            "tool_trace": [],
        },
        "artifact_refs": [],
        "warnings": [],
        "status": "success",
        "outcome": "success",
        "error": None,
        "metadata": {},
        "source_payload": None,
    }
    messages = [
        {"role": "user", "content": "Plan it.", "request_id": "rec-req-1"},
        {
            "role": "assistant",
            "content": "Done",
            "request_id": "rec-req-1",
            "blocks": [
                {
                    "type": "tool_use",
                    "tool": "plan_agent",
                    "input": "plan",
                    "run_id": "plan-run-1",
                },
                {
                    "type": "tool_result",
                    "tool": "plan_agent",
                    "output": "Planner produced 1 step.",
                    "run_id": "plan-run-1",
                    "result": plan_result,
                },
                {
                    "type": "plan",
                    "event": "created",
                    "summary": "Planner produced 1 step.",
                    "plan": {
                        "goal": "do a thing",
                        "steps": [{"step_id": "s1", "intent": "x"}],
                    },
                    "run_id": "plan-run-1",
                    "tool_trace": [],
                },
                {"type": "text", "text": "Done"},
            ],
        },
    ]
    _seed_recorded_session(session_id, archive, messages)

    out_dir = tmp_path / "out"
    rc = replay.main(
        [
            session_id,
            "--archive-dir",
            str(archive),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0, (
        "plan block should be re-derived from the plan_agent tool_end, not "
        "emitted twice or dropped"
    )

    sse_path = next((out_dir / session_id).glob("*/sse.jsonl"))
    lines = [
        json.loads(line)
        for line in sse_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(line["type"] == "plan_created" for line in lines), (
        "QueryEngine should have re-derived a plan_created event during replay"
    )
