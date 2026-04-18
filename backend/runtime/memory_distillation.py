from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit.store import append_file_written_event
from graph.memory_types import parse_memory_document
from graph.session_manager import SessionManager

logger = logging.getLogger(__name__)

_NOTE_MEMORY_TYPE = "project_fact"
_SESSION_DISTILLATION_TYPE = "session_distillation"
_SESSION_DISTILLATION_SOURCE = "post_session_hook"
_SESSION_DISTILLATION_NAME_TEMPLATE = "Post-session distillation for {session_id}"
_SESSION_DISTILLATION_DESCRIPTION_TEMPLATE = (
    "Consolidated durable facts distilled from every turn in session {session_id}."
)
_NOTE_NAME_TEMPLATE = "Session distillation {session_id}"
_NOTE_DESCRIPTION_TEMPLATE = (
    "Runtime-maintained distilled notes from verified turns in session {session_id}."
)
_NOTE_INTRO = (
    "# Runtime Session Distillation\n\n"
    "This runtime-owned note records verified turn summaries when the turn did not "
    "already write under `memory/` directly. Promote lasting user or project facts "
    "into `memory/user/` or `memory/project/` when a human-curated note is warranted."
)
_MAX_USER_MESSAGE_CHARS = 240
_MAX_ASSISTANT_SUMMARY_CHARS = 520
_MAX_VERIFICATION_CHARS = 220
_MAX_CUE_CHARS = 180
_MAX_RETRIEVAL_SOURCES = 4
_MAX_SESSION_CUES = 3


@dataclass(frozen=True)
class MemoryDistillationResult:
    outcome: str
    reason: str
    path: str | None = None


@dataclass(frozen=True)
class _DistilledTurn:
    user_message: str
    assistant_summary: str
    verification_summary: str
    evidence_review_status: str | None
    retrieval_sources: tuple[str, ...]
    session_cues: tuple[str, ...]


def distill_request_memory(
    *,
    base_dir: Path,
    session_manager: SessionManager,
    session_id: str,
    request_id: str,
    memory_indexer: Any | None = None,
) -> MemoryDistillationResult:
    messages = session_manager.load_request_messages(session_id, request_id)
    if not messages:
        return MemoryDistillationResult("skipped", "request_not_found")

    if _turn_wrote_memory_directly(messages):
        return MemoryDistillationResult("skipped", "memory_already_written")

    distilled_turn = _build_distilled_turn(
        messages=messages,
        session_manager=session_manager,
        session_id=session_id,
    )
    if distilled_turn is None:
        return MemoryDistillationResult("skipped", "turn_not_distillable")

    target = base_dir / "memory" / "agent" / f"session-{session_id}.md"
    relative_target = target.relative_to(base_dir).as_posix()

    try:
        existing_content = target.read_text(encoding="utf-8") if target.exists() else ""
    except OSError:
        append_file_written_event(
            base_dir,
            path=relative_target,
            source="memory_distillation",
            outcome="execution_failure",
            session_id=session_id,
            reason="note_unreadable",
        )
        return MemoryDistillationResult("failed", "note_unreadable", path=relative_target)

    new_content = _render_distillation_note(
        base_dir=base_dir,
        target=target,
        session_id=session_id,
        request_id=request_id,
        turn=distilled_turn,
        existing_content=existing_content,
    )
    if new_content is None:
        return MemoryDistillationResult("skipped", "request_already_distilled", path=relative_target)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
    except OSError:
        append_file_written_event(
            base_dir,
            path=relative_target,
            source="memory_distillation",
            outcome="execution_failure",
            session_id=session_id,
            reason="note_write_failed",
        )
        return MemoryDistillationResult("failed", "note_write_failed", path=relative_target)

    append_file_written_event(
        base_dir,
        path=relative_target,
        source="memory_distillation",
        outcome="written",
        byte_count=len(new_content.encode("utf-8")),
        session_id=session_id,
        reason=f"distilled request {request_id}",
    )

    if memory_indexer is not None and getattr(memory_indexer, "base_dir", None) == base_dir:
        try:
            # Incremental: only re-embeds the distilled file, not the whole corpus.
            memory_indexer._maybe_rebuild()
        except Exception:
            pass

    return MemoryDistillationResult("written", "distilled_verified_turn", path=relative_target)


def _build_distilled_turn(
    *,
    messages: list[dict[str, Any]],
    session_manager: SessionManager,
    session_id: str,
) -> _DistilledTurn | None:
    user_message = ""
    latest_assistant_summary = ""
    latest_verification_summary = ""
    latest_evidence_review_status: str | None = None
    retrieval_sources: list[str] = []
    seen_sources: set[str] = set()
    verification_passed = False

    for message in messages:
        role = message.get("role")
        if role == "user" and not user_message:
            user_message = _truncate_inline(message.get("content", ""), _MAX_USER_MESSAGE_CHARS)
            continue

        if role != "assistant":
            continue

        content = _truncate_inline(message.get("content", ""), _MAX_ASSISTANT_SUMMARY_CHARS)
        if content:
            latest_assistant_summary = content

        for block in message.get("blocks", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "verification" and block.get("verdict") == "pass":
                verification_passed = True
                latest_verification_summary = _truncate_inline(
                    block.get("summary", ""),
                    _MAX_VERIFICATION_CHARS,
                )
            if block.get("type") == "retrieval":
                results = block.get("results")
                if not isinstance(results, list):
                    continue
                for result in results:
                    if len(retrieval_sources) >= _MAX_RETRIEVAL_SOURCES:
                        break
                    if not isinstance(result, dict):
                        continue
                    source = result.get("source")
                    if not isinstance(source, str) or not source or source in seen_sources:
                        continue
                    retrieval_sources.append(source)
                    seen_sources.add(source)

        for tool_call in message.get("tool_calls", []):
            if not isinstance(tool_call, dict):
                continue
            if tool_call.get("tool") != "evidence_review":
                continue
            result = tool_call.get("result")
            if not isinstance(result, dict):
                continue
            structured_payload = result.get("structured_payload")
            if not isinstance(structured_payload, dict):
                continue
            review_status = structured_payload.get("review_status")
            if isinstance(review_status, str) and review_status.strip():
                latest_evidence_review_status = review_status.strip()

    if not verification_passed or not latest_assistant_summary:
        return None

    return _DistilledTurn(
        user_message=user_message,
        assistant_summary=latest_assistant_summary,
        verification_summary=latest_verification_summary or "Verifier marked this turn as pass.",
        evidence_review_status=latest_evidence_review_status,
        retrieval_sources=tuple(retrieval_sources),
        session_cues=_latest_session_cues(session_manager, session_id),
    )


def _turn_wrote_memory_directly(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        for tool_call in message.get("tool_calls", []):
            if not isinstance(tool_call, dict) or tool_call.get("tool") != "write_file":
                continue
            result = tool_call.get("result")
            if not isinstance(result, dict):
                continue
            if str(result.get("outcome") or result.get("status") or "").lower() not in {
                "success",
                "written",
            }:
                continue
            structured_payload = result.get("structured_payload")
            if not isinstance(structured_payload, dict):
                continue
            path = structured_payload.get("path")
            if isinstance(path, str) and path.startswith("memory/"):
                return True
    return False


def _latest_session_cues(
    session_manager: SessionManager,
    session_id: str,
) -> tuple[str, ...]:
    continuity = session_manager.get_session_continuity(session_id)
    if not continuity:
        return ()

    latest = continuity[-1]
    cues: list[str] = []
    seen: set[str] = set()
    for field in (
        "decisions_and_rationale",
        "results_register",
        "open_questions_and_next_actions",
    ):
        values = latest.get(field)
        if not isinstance(values, list):
            continue
        for value in values:
            cleaned = _truncate_inline(str(value), _MAX_CUE_CHARS)
            if not cleaned or cleaned in seen:
                continue
            cues.append(cleaned)
            seen.add(cleaned)
            if len(cues) >= _MAX_SESSION_CUES:
                return tuple(cues)
    return tuple(cues)


def _render_distillation_note(
    *,
    base_dir: Path,
    target: Path,
    session_id: str,
    request_id: str,
    turn: _DistilledTurn,
    existing_content: str,
) -> str | None:
    relative_target = target.relative_to(base_dir).as_posix()
    parsed_existing = parse_memory_document(relative_target, existing_content)
    existing_body = parsed_existing.body if existing_content.strip() else ""
    if not existing_body and existing_content.strip():
        existing_body = existing_content.strip()

    turn_marker = f"## Turn {request_id}"
    if turn_marker in existing_body:
        return None

    body_parts: list[str] = []
    trimmed_body = existing_body.strip()
    if trimmed_body:
        body_parts.append(trimmed_body)
    else:
        body_parts.append(_NOTE_INTRO)
    body_parts.append(_render_turn_entry(request_id=request_id, turn=turn))
    body = "\n\n".join(part.rstrip() for part in body_parts if part.strip()).rstrip() + "\n"
    return _frontmatter(session_id) + body


def _render_turn_entry(*, request_id: str, turn: _DistilledTurn) -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [f"## Turn {request_id}", f"- Distilled at: {timestamp}"]
    if turn.user_message:
        lines.append(f"- User message: {turn.user_message}")
    lines.append(f"- Assistant conclusion: {turn.assistant_summary}")
    lines.append(f"- Verification: {turn.verification_summary}")
    if turn.evidence_review_status:
        lines.append(f"- Evidence review: {turn.evidence_review_status}")
    if turn.retrieval_sources:
        lines.append("- Retrieved sources:")
        lines.extend(f"  - {source}" for source in turn.retrieval_sources)
    if turn.session_cues:
        lines.append("- Prior session cues:")
        lines.extend(f"  - {cue}" for cue in turn.session_cues)
    return "\n".join(lines)


def _frontmatter(session_id: str) -> str:
    name = _NOTE_NAME_TEMPLATE.format(session_id=session_id)
    description = _NOTE_DESCRIPTION_TEMPLATE.format(session_id=session_id)
    return (
        "---\n"
        f"type: {_NOTE_MEMORY_TYPE}\n"
        f"name: {_json_scalar(name)}\n"
        f"description: {_json_scalar(description)}\n"
        "---\n"
    )


def _truncate_inline(value: Any, limit: int) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _json_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------- #
# Post-session distillation                                             #
# --------------------------------------------------------------------- #

# Session ids whose post-session distillation failed. Exposed via the debug
# endpoint (GET /api/debug/failed-distillations) for manual inspection. The
# set is intentionally in-memory; persistence / retry is out of scope.
_failed_distillations: set[str] = set()


def get_failed_distillations() -> list[str]:
    """Return a stable, sorted copy of the failed-distillation session ids."""
    return sorted(_failed_distillations)


def record_failed_distillation(session_id: str) -> None:
    _failed_distillations.add(session_id)


def clear_failed_distillations() -> None:
    """Clear the in-memory failure set. Primarily for tests."""
    _failed_distillations.clear()


@dataclass(frozen=True)
class _SessionTurnEntry:
    turn_id: str
    user_message: str
    assistant_summary: str
    verification_summary: str
    verification_verdict: str | None
    evidence_review_status: str | None
    retrieval_sources: tuple[str, ...]
    tools_used: tuple[str, ...]


async def distill_session(
    session_id: str,
    *,
    _llm_summarize: bool = False,
    base_dir: Path | None = None,
    session_manager: SessionManager | None = None,
) -> MemoryDistillationResult:
    """Deterministically aggregate every turn in *session_id* into a
    single durable-facts file at ``memory/agent/session-<id>.md``.

    The file is overwritten on every call; running twice with unchanged
    session state produces a byte-identical file (``written_at`` is derived
    from the session's stored ``updated_at`` timestamp).

    Returns a :class:`MemoryDistillationResult`. Raises ``RuntimeError``
    only when ``base_dir`` / ``session_manager`` cannot be resolved; all
    other I/O errors surface as ``MemoryDistillationResult("failed", ...)``
    so fire-and-forget callers can treat them uniformly.

    ``_llm_summarize`` is reserved as a hook for a future LLM rewrite path
    and is ignored in v1.
    """
    del _llm_summarize  # reserved hook; v1 uses deterministic aggregation only

    if base_dir is None or session_manager is None:
        from graph.agent import agent_manager

        if base_dir is None:
            base_dir = agent_manager.base_dir
        if session_manager is None:
            session_manager = agent_manager.session_manager

    if base_dir is None or session_manager is None:
        raise RuntimeError(
            "distill_session requires base_dir and session_manager (agent_manager not initialised)"
        )

    target = base_dir / "memory" / "agent" / f"session-{session_id}.md"
    relative_target = target.relative_to(base_dir).as_posix()

    try:
        messages = session_manager.load_session(session_id)
        session_updated_at = session_manager.get_session_meta(session_id).get("updated_at", 0.0)
    except ValueError:
        # Invalid session id — treat as "no such session"; don't write a file.
        return MemoryDistillationResult("skipped", "invalid_session_id")

    turn_entries = _build_session_turn_entries(messages)
    turn_ids = [entry.turn_id for entry in turn_entries]

    written_at = _deterministic_timestamp(session_updated_at)
    new_content = _render_session_distillation_note(
        session_id=session_id,
        turn_ids=turn_ids,
        turn_entries=turn_entries,
        written_at=written_at,
    )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
    except OSError:
        try:
            append_file_written_event(
                base_dir,
                path=relative_target,
                source="session_distillation",
                outcome="execution_failure",
                session_id=session_id,
                reason="note_write_failed",
            )
        except Exception:
            # Audit log failure must never mask the underlying error. The caller
            # still receives the "failed" MemoryDistillationResult.
            pass
        return MemoryDistillationResult("failed", "note_write_failed", path=relative_target)

    try:
        append_file_written_event(
            base_dir,
            path=relative_target,
            source="session_distillation",
            outcome="written",
            byte_count=len(new_content.encode("utf-8")),
            session_id=session_id,
            reason="post_session_hook",
        )
    except Exception:
        pass

    return MemoryDistillationResult("written", "session_distilled", path=relative_target)


def fire_post_session_distillation(
    session_id: str,
    *,
    base_dir: Path | None = None,
    session_manager: SessionManager | None = None,
) -> None:
    """Fire-and-forget wrapper around :func:`distill_session`.

    Schedules on the running event loop when there is one (via
    ``asyncio.create_task``) and attaches a done callback that records
    failures without raising. Falls back to ``asyncio.run`` when no loop
    is running (tests, synchronous callers); failures there are caught and
    recorded the same way.

    ``base_dir`` / ``session_manager`` are forwarded to :func:`distill_session`
    when provided. Callers that already hold these references (e.g.
    :class:`~graph.session_manager.SessionManager.delete_session`) should
    pass them explicitly so the distillation works even before
    ``agent_manager`` is initialised.

    Never raises. Failures are surfaced through
    :func:`get_failed_distillations`.
    """
    def _coroutine():
        return distill_session(
            session_id,
            base_dir=base_dir,
            session_manager=session_manager,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        # No running loop — run inline so the failure path can still
        # record into _failed_distillations deterministically.
        try:
            asyncio.run(_coroutine())
        except Exception as exc:  # noqa: BLE001 — fire-and-forget surface
            logger.error(
                "post_session_distillation_failed",
                extra={"session_id": session_id, "error": repr(exc)},
            )
            _failed_distillations.add(session_id)
        return

    task = loop.create_task(_coroutine())

    def _on_done(task_ref: asyncio.Task) -> None:
        try:
            exc = task_ref.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            return
        logger.error(
            "post_session_distillation_failed",
            extra={"session_id": session_id, "error": repr(exc)},
        )
        _failed_distillations.add(session_id)

    task.add_done_callback(_on_done)


# --------------------------------------------------------------------- #
# Session turn aggregation                                              #
# --------------------------------------------------------------------- #


def _build_session_turn_entries(
    messages: list[dict[str, Any]],
) -> list[_SessionTurnEntry]:
    """Group *messages* by ``request_id`` preserving first-seen order
    and collapse each group into a deterministic :class:`_SessionTurnEntry`.
    Messages without a ``request_id`` are skipped (they predate the
    runtime's request tracking)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []

    for message in messages:
        request_id = message.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            continue
        if request_id not in grouped:
            grouped[request_id] = []
            order.append(request_id)
        grouped[request_id].append(message)

    entries: list[_SessionTurnEntry] = []
    for request_id in order:
        entry = _summarize_turn(request_id, grouped[request_id])
        if entry is not None:
            entries.append(entry)
    return entries


def _summarize_turn(
    turn_id: str,
    messages: list[dict[str, Any]],
) -> _SessionTurnEntry | None:
    user_message = ""
    assistant_summary = ""
    verification_summary = ""
    verification_verdict: str | None = None
    evidence_review_status: str | None = None
    retrieval_sources: list[str] = []
    seen_sources: set[str] = set()
    tools_used: list[str] = []
    seen_tools: set[str] = set()

    for message in messages:
        role = message.get("role")
        if role == "user" and not user_message:
            user_message = _truncate_inline(message.get("content", ""), _MAX_USER_MESSAGE_CHARS)
            continue
        if role != "assistant":
            continue

        content = _truncate_inline(message.get("content", ""), _MAX_ASSISTANT_SUMMARY_CHARS)
        if content:
            assistant_summary = content

        for block in message.get("blocks", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "verification":
                verdict = block.get("verdict")
                if isinstance(verdict, str) and verdict:
                    verification_verdict = verdict
                    verification_summary = _truncate_inline(
                        block.get("summary", ""),
                        _MAX_VERIFICATION_CHARS,
                    )
            elif block.get("type") == "retrieval":
                results = block.get("results")
                if not isinstance(results, list):
                    continue
                for result in results:
                    if len(retrieval_sources) >= _MAX_RETRIEVAL_SOURCES:
                        break
                    if not isinstance(result, dict):
                        continue
                    source = result.get("source")
                    if not isinstance(source, str) or not source or source in seen_sources:
                        continue
                    retrieval_sources.append(source)
                    seen_sources.add(source)

        for tool_call in message.get("tool_calls", []):
            if not isinstance(tool_call, dict):
                continue
            tool_name = tool_call.get("tool")
            if isinstance(tool_name, str) and tool_name and tool_name not in seen_tools:
                tools_used.append(tool_name)
                seen_tools.add(tool_name)
            if tool_name == "evidence_review":
                result = tool_call.get("result")
                if not isinstance(result, dict):
                    continue
                payload = result.get("structured_payload")
                if not isinstance(payload, dict):
                    continue
                status = payload.get("review_status")
                if isinstance(status, str) and status.strip():
                    evidence_review_status = status.strip()

    if not user_message and not assistant_summary:
        return None

    return _SessionTurnEntry(
        turn_id=turn_id,
        user_message=user_message,
        assistant_summary=assistant_summary,
        verification_summary=verification_summary,
        verification_verdict=verification_verdict,
        evidence_review_status=evidence_review_status,
        retrieval_sources=tuple(retrieval_sources),
        tools_used=tuple(tools_used),
    )


def _render_session_distillation_note(
    *,
    session_id: str,
    turn_ids: list[str],
    turn_entries: list[_SessionTurnEntry],
    written_at: str,
) -> str:
    frontmatter = _render_session_distillation_frontmatter(
        session_id=session_id,
        turn_ids=turn_ids,
        written_at=written_at,
    )

    header = (
        "# Post-Session Distillation\n\n"
        "Consolidated durable facts from every turn in this session. "
        "Regenerated on session end or explicit `/end` trigger; one session = "
        "one consolidated block."
    )

    if not turn_entries:
        body = header + "\n\n_No turns with a persisted request id were recorded._\n"
        return frontmatter + body

    parts = [header]
    for entry in turn_entries:
        parts.append(_render_session_turn_entry(entry))
    body = "\n\n".join(part.rstrip() for part in parts if part.strip()).rstrip() + "\n"
    return frontmatter + body


def _render_session_turn_entry(entry: _SessionTurnEntry) -> str:
    lines = [f"## Turn {entry.turn_id}"]
    if entry.user_message:
        lines.append(f"- User message: {entry.user_message}")
    if entry.assistant_summary:
        lines.append(f"- Assistant conclusion: {entry.assistant_summary}")
    if entry.verification_verdict:
        verification_line = f"- Verification: {entry.verification_verdict}"
        if entry.verification_summary:
            verification_line += f" — {entry.verification_summary}"
        lines.append(verification_line)
    if entry.evidence_review_status:
        lines.append(f"- Evidence review: {entry.evidence_review_status}")
    if entry.tools_used:
        lines.append(f"- Tools used: {', '.join(entry.tools_used)}")
    if entry.retrieval_sources:
        lines.append("- Retrieved sources:")
        lines.extend(f"  - {source}" for source in entry.retrieval_sources)
    return "\n".join(lines)


def _render_session_distillation_frontmatter(
    *,
    session_id: str,
    turn_ids: list[str],
    written_at: str,
) -> str:
    name = _SESSION_DISTILLATION_NAME_TEMPLATE.format(session_id=session_id)
    description = _SESSION_DISTILLATION_DESCRIPTION_TEMPLATE.format(session_id=session_id)
    lines = [
        "---",
        f"type: {_SESSION_DISTILLATION_TYPE}",
        f"name: {_json_scalar(name)}",
        f"description: {_json_scalar(description)}",
        f"session_id: {_json_scalar(session_id)}",
    ]
    if turn_ids:
        lines.append("turn_ids:")
        lines.extend(f"  - {_json_scalar(turn_id)}" for turn_id in turn_ids)
    else:
        lines.append("turn_ids: []")
    lines.append(f"written_at: {_json_scalar(written_at)}")
    lines.append(f"source: {_SESSION_DISTILLATION_SOURCE}")
    lines.append("---\n")
    return "\n".join(lines)


def _deterministic_timestamp(session_updated_at: float) -> str:
    """Derive the distillation timestamp from the session's ``updated_at``
    so that two back-to-back calls produce byte-identical output. Falls
    back to epoch 0 when the session has no recorded update time."""
    if not isinstance(session_updated_at, (int, float)) or session_updated_at <= 0:
        session_updated_at = 0.0
    return (
        datetime.fromtimestamp(session_updated_at, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )
