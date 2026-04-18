"""Turn-boundary prompt-budget compaction — four-phase progressive ladder.

As the session history approaches the per-turn token budget configured by
``config.get_max_tokens_per_turn()``, the oldest messages are archived via
``SessionManager.compress_history`` (which keeps ``compressed_context`` and
``compressed_archive_index`` so the full history stays recoverable from
``load_archived_history``).

Refining issue #82, compaction is now a four-rung ladder instead of a single
pass. Cheap rungs trigger early and skip the LLM so routine turns don't pay a
round-trip; the expensive rewrite only fires when the session is about to
blow the budget entirely.

========== =============  ========= ===========================================
Phase      Trigger ratio  Uses LLM  Scope of archived messages
========== =============  ========= ===========================================
snip       ≥ 0.60         no        oldest exchange (≈2 messages)
microcompact ≥ 0.75       no        oldest ~25% (floor 4)
collapse   ≥ 0.85         yes       oldest ~50% (current behavior)
autocompact ≥ 0.95        yes       entire live history
========== =============  ========= ===========================================

Evaluation is *descending* — the ladder selects the most aggressive phase
whose threshold is met, runs exactly that phase, and returns. The chosen
phase is both emitted on the ``compaction_event`` and persisted on the
session JSON as ``context_compression_phase``.
"""
from __future__ import annotations

from typing import Any

from config import get_max_tokens_per_turn
from graph.session_summary import (
    build_deterministic_summary,
    generate_structured_summary,
)

# Per-phase budget-ratio thresholds. Evaluated in descending order; the first
# phase whose threshold is met wins. Callers may override any subset via the
# ``phase_thresholds`` kwarg on :func:`maybe_compact_turn_boundary`.
PHASE_THRESHOLDS: dict[str, float] = {
    "snip": 0.60,
    "microcompact": 0.75,
    "collapse": 0.85,
    "autocompact": 0.95,
}

# Per-phase floor on how many live messages must exist before the phase can
# fire. Prevents the ladder from thrashing on nearly-empty sessions whose
# token counts are dominated by a single massive tool output.
PHASE_MIN_MESSAGES: dict[str, int] = {
    "snip": 2,
    "microcompact": 4,
    "collapse": 4,
    "autocompact": 2,
}

# Phases in descending-priority order. The first phase the session qualifies
# for runs; cheaper phases are skipped because a more aggressive one subsumes
# them.
PHASE_ORDER: tuple[str, ...] = ("autocompact", "collapse", "microcompact", "snip")

# Kept for backward compatibility with earlier callers that passed a single
# ``budget_ratio`` argument. Matches the old single-phase threshold (~0.80).
DEFAULT_BUDGET_RATIO = PHASE_THRESHOLDS["collapse"]
MIN_MESSAGES_TO_COMPACT = PHASE_MIN_MESSAGES["collapse"]


def _count_tokens(value: Any) -> int:
    from api.tokens import _count_optional_text

    return _count_optional_text(value)


def estimate_history_tokens(history: list[dict]) -> int:
    """Estimate the prompt-token load of a message list.

    Counts message content plus any attached tool-call ``input``/``output``
    strings so the estimate tracks what the executor will actually pay for.
    """
    total = 0
    for message in history:
        total += _count_tokens(message.get("content"))
        for call in message.get("tool_calls") or []:
            total += _count_tokens(call.get("input"))
            total += _count_tokens(call.get("output"))
    return total


def _select_phase(
    ratio: float,
    message_count: int,
    thresholds: dict[str, float],
) -> str | None:
    for phase in PHASE_ORDER:
        threshold = thresholds.get(phase, PHASE_THRESHOLDS[phase])
        if ratio < threshold:
            continue
        if message_count < PHASE_MIN_MESSAGES[phase]:
            continue
        return phase
    return None


def _messages_to_archive(phase: str, total: int) -> int:
    """How many of the oldest messages does *phase* archive?"""
    if phase == "snip":
        # Oldest single exchange — typically one user + one assistant message.
        return min(2, total)
    if phase == "microcompact":
        # Oldest ~25%, with the same floor the collapse phase uses so a tiny
        # session still produces a useful archive batch.
        return max(MIN_MESSAGES_TO_COMPACT, total // 4)
    if phase == "collapse":
        # Oldest 50% — matches the pre-ladder single-pass behavior.
        return max(MIN_MESSAGES_TO_COMPACT, total // 2)
    if phase == "autocompact":
        # Full rewrite: archive everything and leave just the summary.
        return total
    raise ValueError(f"Unknown compaction phase: {phase!r}")


async def _build_phase_summary(phase: str, messages: list[dict], llm) -> str | None:
    """Produce the summary string for *phase*, or ``None`` on LLM failure.

    ``snip`` and ``microcompact`` are deterministic — no LLM round-trip. The
    LLM phases catch and swallow any exception so a transient model error
    skips compaction this turn instead of breaking the user's request.
    """
    if phase in ("snip", "microcompact"):
        return build_deterministic_summary(messages)

    try:
        return await generate_structured_summary(messages, llm)
    except Exception:
        return None


async def maybe_compact_turn_boundary(
    session_manager,
    session_id: str,
    llm,
    *,
    budget_ratio: float | None = None,
    phase_thresholds: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Run one compaction pass if the session is near its per-turn budget.

    Evaluates the four-phase ladder from most-aggressive to cheapest and
    runs the first phase the session qualifies for. Returns a
    ``compaction_event`` payload (with a ``phase`` field naming the rung
    that fired) on success, or ``None`` when no compaction was needed or
    possible (budget disabled, too few messages, summary generation
    failed).

    ``budget_ratio`` is accepted for backward compatibility: when provided it
    overrides the ``collapse`` threshold so legacy callers that tuned a
    single ratio still affect the primary LLM rung. Prefer
    ``phase_thresholds`` for new code.
    """
    budget = get_max_tokens_per_turn()
    if budget <= 0:
        return None

    thresholds = dict(PHASE_THRESHOLDS)
    if phase_thresholds:
        thresholds.update(phase_thresholds)
    if budget_ratio is not None:
        thresholds["collapse"] = budget_ratio

    history = session_manager.load_session_for_agent(session_id)
    current_tokens = estimate_history_tokens(history)
    ratio = current_tokens / budget if budget > 0 else 0.0

    # Skip the lock acquisition on the cold path — the cheapest phase needs
    # at least ``snip``'s threshold, so anything below that is a no-op.
    if ratio < thresholds["snip"]:
        return None

    async with session_manager.get_or_create_compress_lock(session_id):
        raw_messages = session_manager.load_session(session_id)
        phase = _select_phase(ratio, len(raw_messages), thresholds)
        if phase is None:
            return None

        n = _messages_to_archive(phase, len(raw_messages))
        if n <= 0:
            return None

        to_compact = raw_messages[:n]
        archived_tokens = estimate_history_tokens(to_compact)

        prior_archived = sum(
            batch.get("message_count", 0)
            for batch in session_manager.list_archived_history_batches(session_id)
        )

        summary = await _build_phase_summary(phase, to_compact, llm)
        if summary is None:
            return None

        archived_count, _ = session_manager.compress_history(
            session_id, summary, n, phase=phase
        )

    summary_tokens = _count_tokens(summary)
    saved_tokens = max(0, archived_tokens - summary_tokens)

    return {
        "type": "compaction_event",
        "phase": phase,
        "from_turn": prior_archived,
        "to_turn": prior_archived + archived_count,
        "summary": summary,
        "saved_tokens": saved_tokens,
    }
