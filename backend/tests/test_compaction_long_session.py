"""Long-session compaction test (issue #64).

Simulates a 200-turn chat session running under a small token budget and
verifies that:

* ``maybe_compact_turn_boundary`` fires at least once,
* prompt history stays within the configured budget on every turn,
* the structured summary + archived batches satisfy a simple coherence
  rubric (header present, all five register sections populated, monotonic
  turn ranges, round-trippable archived messages).

The test is intentionally self-contained -- it redefines the ``_fake_llm``
and ``_structured_summary`` helpers rather than importing them from the
sibling ``test_compaction`` module.
"""
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


REGISTER_HEADINGS = (
    "Decisions and rationale:",
    "Results register:",
    "Evidence register:",
    "Compliance register:",
    "Open questions and next actions:",
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


def _register_sections_nonempty(summary: str) -> bool:
    """Each labelled register section must contain at least one body line."""
    for heading in REGISTER_HEADINGS:
        idx = summary.find(heading)
        if idx == -1:
            return False
        # Body is whatever sits between this heading and the next heading
        # (or end of summary).
        tail = summary[idx + len(heading):]
        next_heading_pos = len(tail)
        for other in REGISTER_HEADINGS:
            if other == heading:
                continue
            pos = tail.find(other)
            if pos != -1 and pos < next_heading_pos:
                next_heading_pos = pos
        body = tail[:next_heading_pos].strip()
        if not body:
            return False
    return True


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


@pytest.mark.asyncio
async def test_long_session_compaction_keeps_budget_and_stays_coherent(
    sm, monkeypatch
):
    budget = 5000
    turn_count = 200
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: budget)

    session_id = sm.create_session()
    llm = _fake_llm(_structured_summary("long session"))

    compaction_events: list[dict] = []
    per_turn_history_tokens: list[int] = []

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
        history_tokens = estimate_history_tokens(history)
        per_turn_history_tokens.append(history_tokens)
        assert history_tokens <= budget, (
            f"turn {turn_index}: prompt history {history_tokens} tokens "
            f"exceeds budget {budget}"
        )

    # --- (a) Compaction fired at least once on this run. ---------------------
    assert compaction_events, "compaction should fire at least once on a 200-turn run"

    # --- (b) Every recorded per-turn history size respected the budget. ------
    assert max(per_turn_history_tokens) <= budget

    # --- (c) Coherence rubric over every emitted compaction_event. -----------
    rubric_score = 0
    rubric_max = 0

    for event in compaction_events:
        rubric_max += 4

        # 1. Event shape.
        if event.get("type") == "compaction_event" and event.get("saved_tokens", -1) >= 0:
            rubric_score += 1

        # 2. Structured summary has the canonical header.
        summary = event.get("summary", "")
        if summary.startswith(STRUCTURED_SUMMARY_HEADER):
            rubric_score += 1

        # 3. All five register sections are present and non-empty.
        if _register_sections_nonempty(summary):
            rubric_score += 1

        # 4. Turn range is well-formed (from_turn < to_turn).
        if event.get("from_turn", 0) < event.get("to_turn", 0):
            rubric_score += 1

    # Archived turn ranges should be contiguous across successive events.
    rubric_max += 1
    contiguous = all(
        earlier["to_turn"] == later["from_turn"]
        for earlier, later in zip(compaction_events, compaction_events[1:])
    )
    if contiguous:
        rubric_score += 1

    assert rubric_score == rubric_max, (
        f"coherence rubric failed: {rubric_score}/{rubric_max} "
        f"(events={len(compaction_events)})"
    )

    # --- Archived batches round-trip cleanly. --------------------------------
    batches = sm.list_archived_history_batches(session_id)
    assert batches, "long-session run should produce at least one archive batch"

    total_archived = 0
    for batch in batches:
        archived = sm.load_archived_history(session_id, batch["archive_id"])
        assert archived, f"archive {batch['archive_id']} should be non-empty"
        for message in archived:
            assert message["role"] in {"user", "assistant"}
            assert isinstance(message["content"], str) and message["content"]
        total_archived += len(archived)

    remaining = sm.load_session(session_id)
    # Every user+assistant message is either still in the live session or
    # stored in an archive batch -- nothing should have been dropped.
    assert total_archived + len(remaining) == 2 * turn_count
