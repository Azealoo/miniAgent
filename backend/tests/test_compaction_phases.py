"""Per-phase tests for the four-phase compaction ladder (issue #82).

Covers:

* each phase fires at its documented budget-ratio threshold,
* the cheap phases (``snip``, ``microcompact``) never call the LLM,
* the expensive phases (``collapse``, ``autocompact``) use the structured
  LLM summary path,
* the session's ``context_compression_phase`` metadata tracks the most
  recent rung, and
* the ``compaction_event`` payload carries the chosen ``phase`` so a UI
  consumer can surface it without replaying session state.

The ladder is evaluated descending — the most aggressive phase whose
threshold is met wins — so each test configures thresholds + token counts
that force exactly one phase to trigger.
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
    PHASE_THRESHOLDS,
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


class _TrackingLLM:
    """Mimics the llm surface ``generate_structured_summary`` uses.

    Counts ainvoke calls so the cheap phases can assert the LLM was never
    hit. Any call returns ``summary_text`` wrapped in a mock response.
    """

    def __init__(self, summary_text: str) -> None:
        self.summary_text = summary_text
        self.calls = 0

    def bind(self, *_args, **_kwargs) -> "_TrackingLLM":
        return self

    async def ainvoke(self, _messages):
        self.calls += 1
        response = MagicMock()
        response.content = self.summary_text
        return response


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


def _fill_session(sm: SessionManager, session_id: str, turns: int, words: int) -> None:
    """Seed *turns* user+assistant pairs. Each message has ``words`` tokens of filler."""
    filler = ("alpha beta gamma delta epsilon " * (max(1, words // 5))).strip()
    for i in range(turns):
        sm.save_message(
            session_id,
            "user" if i % 2 == 0 else "assistant",
            f"turn {i}: PMID:{1000 + i} path=/data/run-{i}.tsv {filler}",
            request_id=f"req-{i}",
        )


async def _run_at_ratio(
    sm: SessionManager,
    session_id: str,
    llm: _TrackingLLM,
    *,
    target_ratio: float,
) -> dict | None:
    """Pin ``estimate_history_tokens`` so the budget ratio is exactly *target_ratio*."""
    budget = 10_000
    synthetic_tokens = int(budget * target_ratio)

    def _fake_estimate(_history):
        return synthetic_tokens

    import runtime.compaction as mod

    original = mod.estimate_history_tokens
    mod.estimate_history_tokens = _fake_estimate  # type: ignore[assignment]
    try:
        return await maybe_compact_turn_boundary(sm, session_id, llm)
    finally:
        mod.estimate_history_tokens = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_snip_phase_fires_at_six_tenths_and_skips_llm(sm, monkeypatch):
    """Phase 1/4: cheap ``snip`` triggers at ~60% and never calls the LLM."""
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 10_000)

    session_id = sm.create_session()
    _fill_session(sm, session_id, turns=5, words=5)

    llm = _TrackingLLM(_structured_summary("unused"))
    event = await _run_at_ratio(sm, session_id, llm, target_ratio=PHASE_THRESHOLDS["snip"])

    assert event is not None
    assert event["phase"] == "snip"
    assert event["type"] == "compaction_event"
    assert event["from_turn"] == 0
    assert event["to_turn"] == 2  # oldest exchange only
    assert llm.calls == 0, "snip must never call the LLM"
    assert sm.get_context_compression_phase(session_id) == "snip"


@pytest.mark.asyncio
async def test_microcompact_phase_fires_at_three_quarters_and_skips_llm(sm, monkeypatch):
    """Phase 2/4: ``microcompact`` triggers at ~75% and is still LLM-free."""
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 10_000)

    session_id = sm.create_session()
    _fill_session(sm, session_id, turns=10, words=10)

    llm = _TrackingLLM(_structured_summary("unused"))
    event = await _run_at_ratio(
        sm, session_id, llm, target_ratio=PHASE_THRESHOLDS["microcompact"]
    )

    assert event is not None
    assert event["phase"] == "microcompact"
    # Microcompact archives roughly the oldest quarter with a floor of 4.
    assert event["from_turn"] == 0
    assert 4 <= event["to_turn"] < 20  # 20 total messages in the session
    assert llm.calls == 0, "microcompact must never call the LLM"
    assert sm.get_context_compression_phase(session_id) == "microcompact"


@pytest.mark.asyncio
async def test_collapse_phase_uses_llm_and_archives_oldest_half(sm, monkeypatch):
    """Phase 3/4: ``collapse`` matches the pre-ladder single-pass behavior."""
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 10_000)

    session_id = sm.create_session()
    _fill_session(sm, session_id, turns=10, words=12)
    raw_count = len(sm.load_session(session_id))

    llm = _TrackingLLM(_structured_summary("collapse run"))
    event = await _run_at_ratio(
        sm, session_id, llm, target_ratio=PHASE_THRESHOLDS["collapse"]
    )

    assert event is not None
    assert event["phase"] == "collapse"
    assert event["summary"].startswith(STRUCTURED_SUMMARY_HEADER)
    assert llm.calls == 1, "collapse must call the LLM exactly once"
    # Roughly half the live messages are archived.
    assert event["to_turn"] == raw_count // 2
    assert sm.get_context_compression_phase(session_id) == "collapse"


@pytest.mark.asyncio
async def test_autocompact_phase_archives_full_history_and_leaves_summary_only(
    sm, monkeypatch
):
    """Phase 4/4: ``autocompact`` is the full rewrite that keeps only the summary."""
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 10_000)

    session_id = sm.create_session()
    _fill_session(sm, session_id, turns=8, words=40)
    raw_count = len(sm.load_session(session_id))
    assert raw_count > 0

    llm = _TrackingLLM(_structured_summary("autocompact run"))
    event = await _run_at_ratio(
        sm, session_id, llm, target_ratio=PHASE_THRESHOLDS["autocompact"]
    )

    assert event is not None
    assert event["phase"] == "autocompact"
    assert event["from_turn"] == 0
    assert event["to_turn"] == raw_count
    # Nothing should remain in the live message list after a full rewrite.
    assert sm.load_session(session_id) == []
    # But the compressed summary persists and is recoverable.
    assert sm.get_compressed_context(session_id).startswith(STRUCTURED_SUMMARY_HEADER)
    assert sm.get_context_compression_phase(session_id) == "autocompact"
    assert llm.calls == 1, "autocompact must call the LLM exactly once"


@pytest.mark.asyncio
async def test_ladder_picks_most_aggressive_applicable_phase(sm, monkeypatch):
    """When multiple thresholds are met, the highest rung wins and runs once."""
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 10_000)

    session_id = sm.create_session()
    _fill_session(sm, session_id, turns=12, words=15)

    llm = _TrackingLLM(_structured_summary("highest wins"))
    # A ratio of 0.98 crosses every threshold; the ladder must still emit
    # exactly one event tagged ``autocompact``.
    event = await _run_at_ratio(sm, session_id, llm, target_ratio=0.98)

    assert event is not None
    assert event["phase"] == "autocompact"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_below_snip_threshold_does_nothing(sm, monkeypatch):
    """Any ratio below the ``snip`` floor leaves the session untouched."""
    monkeypatch.setattr(compaction_module, "get_max_tokens_per_turn", lambda: 10_000)

    session_id = sm.create_session()
    _fill_session(sm, session_id, turns=6, words=5)

    llm = _TrackingLLM(_structured_summary("never"))
    event = await _run_at_ratio(sm, session_id, llm, target_ratio=0.50)

    assert event is None
    assert llm.calls == 0
    assert sm.get_context_compression_phase(session_id) is None
    # Nothing archived.
    assert sm.list_archived_history_batches(session_id) == []
