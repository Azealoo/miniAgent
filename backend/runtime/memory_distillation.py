from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit.store import append_file_written_event
from graph.memory_types import parse_memory_document
from graph.session_manager import SessionManager

_NOTE_MEMORY_TYPE = "project_fact"
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
            memory_indexer.rebuild_index()
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
