"""Turn-boundary prompt-budget compaction.

When the session history approaches the per-turn token budget configured by
``config.get_max_tokens_per_turn()``, compact older messages into a structured
continuity summary and archive the originals via
``SessionManager.compress_history`` (which already persists the compacted
messages and keeps ``compressed_context`` / ``compressed_archive_index`` so the
full history remains recoverable from ``load_archived_history``).
"""
from __future__ import annotations

from typing import Any

from config import get_max_tokens_per_turn
from graph.session_summary import generate_structured_summary

DEFAULT_BUDGET_RATIO = 0.8
MIN_MESSAGES_TO_COMPACT = 4


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


async def maybe_compact_turn_boundary(
    session_manager,
    session_id: str,
    llm,
    *,
    budget_ratio: float = DEFAULT_BUDGET_RATIO,
) -> dict[str, Any] | None:
    """Run one compaction pass if the session is near its per-turn budget.

    Returns a ``compaction_event`` payload on success, ``None`` when no
    compaction was needed or possible (budget disabled, too few messages,
    summary generation failed). The caller is responsible for wrapping the
    payload in its SSE envelope.
    """
    budget = get_max_tokens_per_turn()
    if budget <= 0:
        return None

    history = session_manager.load_session_for_agent(session_id)
    if estimate_history_tokens(history) < int(budget * budget_ratio):
        return None

    async with session_manager.get_or_create_compress_lock(session_id):
        raw_messages = session_manager.load_session(session_id)
        if len(raw_messages) < MIN_MESSAGES_TO_COMPACT:
            return None

        n = max(MIN_MESSAGES_TO_COMPACT, len(raw_messages) // 2)
        to_compact = raw_messages[:n]
        archived_tokens = estimate_history_tokens(to_compact)

        prior_archived = sum(
            batch.get("message_count", 0)
            for batch in session_manager.list_archived_history_batches(session_id)
        )

        try:
            summary = await generate_structured_summary(to_compact, llm)
        except Exception:
            return None

        archived_count, _ = session_manager.compress_history(session_id, summary, n)

    summary_tokens = _count_tokens(summary)
    saved_tokens = max(0, archived_tokens - summary_tokens)

    return {
        "type": "compaction_event",
        "from_turn": prior_archived,
        "to_turn": prior_archived + archived_count,
        "summary": summary,
        "saved_tokens": saved_tokens,
    }
