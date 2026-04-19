"""Tests for ``runtime.compaction.maybe_compact_turn_boundary``."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session_manager import SessionManager
from graph.session_summary import STRUCTURED_SUMMARY_HEADER
from runtime import compaction as compaction_module
from runtime.compaction import (
    estimate_history_tokens,
    maybe_compact_turn_boundary,
)


def _structured_summary(label: str) -> str:
    return (
        f"{STRUCTURED_SUMMARY_HEADER}\n"
        "Decisions and rationale:\n"
        f"- {label} decision\n\n"
        "Results register:\n"
        f"- {label} result\n\n"
        "Evidence register:\n"
        f"- PMID:12345 linked to {label}\n\n"
        "Compliance register:\n"
        f"- {label} compliance note\n\n"
        "Open questions and next actions:\n"
        f"- Follow up on {label}\n"
    )


def _fake_llm(summary_text: str):
    mock = MagicMock()
    mock.bind = MagicMock(return_value=mock)

    mock_resp = MagicMock()
    mock_resp.content = summary_text

    async def fake_ainvoke(msgs):
        return mock_resp

    mock.ainvoke = fake_ainvoke
    mock.bind.return_value.ainvoke = fake_ainvoke
    return mock


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


@pytest.mark.asyncio
async def test_below_budget_returns_none(sm, monkeypatch):
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 5000)

    session_id = sm.create_session()
    for i in range(4):
        sm.save_message(session_id, "user" if i % 2 == 0 else "assistant", f"m{i}")

    event = await maybe_compact_turn_boundary(sm, session_id, _fake_llm("unused"))
    assert event is None


@pytest.mark.asyncio
async def test_disabled_budget_returns_none(sm, monkeypatch):
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 0)

    session_id = sm.create_session()
    for i in range(40):
        sm.save_message(session_id, "user", "words " * 200)

    event = await maybe_compact_turn_boundary(sm, session_id, _fake_llm("unused"))
    assert event is None


@pytest.mark.asyncio
async def test_200_turn_session_stays_under_budget_and_archives_remain_readable(
    sm, monkeypatch
):
    budget = 5000
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: budget)

    session_id = sm.create_session()
    llm = _fake_llm(_structured_summary("synthetic"))

    compaction_events: list[dict] = []
    turn_count = 200

    for turn_index in range(turn_count):
        sm.save_message(
            session_id,
            "user",
            f"User turn #{turn_index}: " + ("alpha beta gamma " * 6),
            request_id=f"req-{turn_index}",
        )
        sm.save_message(
            session_id,
            "assistant",
            f"Assistant turn #{turn_index}: " + ("delta epsilon zeta " * 6),
            request_id=f"req-{turn_index}",
        )

        event = await maybe_compact_turn_boundary(sm, session_id, llm)
        if event is not None:
            compaction_events.append(event)

        history = sm.load_session_for_agent(session_id)
        assert estimate_history_tokens(history) <= budget, (
            f"turn {turn_index}: prompt history "
            f"{estimate_history_tokens(history)} tokens exceeds budget {budget}"
        )

    # Compaction must fire at least once on a 200-turn run constrained to a
    # 5k-token budget.
    assert compaction_events, "compaction_event should fire at least once"

    for event in compaction_events:
        assert event["type"] == "compaction_event"
        assert event["from_turn"] < event["to_turn"]
        assert event["summary"].startswith(STRUCTURED_SUMMARY_HEADER)
        assert event["saved_tokens"] >= 0
        assert event["phase"] in {"snip", "microcompact", "collapse", "autocompact"}

    # Archived ranges are monotonically increasing and non-overlapping.
    for earlier, later in zip(compaction_events, compaction_events[1:]):
        assert earlier["to_turn"] == later["from_turn"]

    # Every archived batch is still readable and the messages round-trip.
    batches = sm.list_archived_history_batches(session_id)
    assert batches

    total_archived = 0
    for batch in batches:
        archived = sm.load_archived_history(session_id, batch["archive_id"])
        assert archived
        for message in archived:
            assert message["role"] in {"user", "assistant"}
            assert isinstance(message["content"], str) and message["content"]
        total_archived += len(archived)

    remaining = sm.load_session(session_id)
    assert total_archived + len(remaining) == 2 * turn_count


@pytest.mark.asyncio
async def test_compaction_event_reports_running_turn_range(sm, monkeypatch):
    budget = 2000
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: budget)

    session_id = sm.create_session()
    llm = _fake_llm(_structured_summary("range check"))

    # Fill enough to cross 0.8 * budget with content-heavy messages.
    for i in range(40):
        sm.save_message(
            session_id,
            "user" if i % 2 == 0 else "assistant",
            "tokens " * 30,
            request_id=f"req-{i}",
        )

    first = await maybe_compact_turn_boundary(sm, session_id, llm)
    assert first is not None
    assert first["from_turn"] == 0
    assert first["to_turn"] > 0

    # Keep pushing until compaction triggers again.
    second = None
    for i in range(40, 200):
        sm.save_message(
            session_id,
            "user" if i % 2 == 0 else "assistant",
            "tokens " * 30,
            request_id=f"req-{i}",
        )
        second = await maybe_compact_turn_boundary(sm, session_id, llm)
        if second is not None:
            break

    assert second is not None
    assert second["from_turn"] == first["to_turn"]
    assert second["to_turn"] > second["from_turn"]
