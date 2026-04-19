from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from langchain_core.messages import HumanMessage, SystemMessage

COMPRESSED_CONTEXT_SEPARATOR = "\n---\n"
STRUCTURED_SUMMARY_HEADER = "[Scientific Continuity Summary v1]"
MAX_SUMMARY_CHARS = 2000

_SECTION_SPECS = (
    ("decisions_and_rationale", "Decisions and rationale"),
    ("results_register", "Results register"),
    ("evidence_register", "Evidence register"),
    ("compliance_register", "Compliance register"),
    ("open_questions_and_next_actions", "Open questions and next actions"),
)
_HEADING_ALIASES = {
    "decisions and rationale": "decisions_and_rationale",
    "decisions rationale": "decisions_and_rationale",
    "decisions and reasoning": "decisions_and_rationale",
    "decision and rationale": "decisions_and_rationale",
    "decisions": "decisions_and_rationale",
    "rationale": "decisions_and_rationale",
    "decision rationale": "decisions_and_rationale",
    "results register": "results_register",
    "results": "results_register",
    "result register": "results_register",
    "evidence register": "evidence_register",
    "evidence": "evidence_register",
    "compliance register": "compliance_register",
    "compliance": "compliance_register",
    "compliance and safety": "compliance_register",
    "compliance safety": "compliance_register",
    "safety and compliance": "compliance_register",
    "safety compliance": "compliance_register",
    "safety": "compliance_register",
    "open questions and next actions": "open_questions_and_next_actions",
    "open questions next actions": "open_questions_and_next_actions",
    "open questions and actions": "open_questions_and_next_actions",
    "next actions": "open_questions_and_next_actions",
    "open questions": "open_questions_and_next_actions",
    "next steps": "open_questions_and_next_actions",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*\S)\s*$")
_HEADING_PREFIX_RE = re.compile(r"^\s*#+\s*")
_HEADING_NUMBER_RE = re.compile(r"^\s*(?:section\s+)?\d+[\).\:-]?\s*")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_PMID_RE = re.compile(r"\bPMID\s*[:#]?\s*\d+\b", re.IGNORECASE)
_RUN_ID_RE = re.compile(r"\brun[-_][A-Za-z0-9._:-]+\b", re.IGNORECASE)
_STABLE_ID_RE = re.compile(r"\b(?:GSE|GSM|SRR|ERR|PRJNA|DOI[:/]|PMC)\S+\b", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:/[\w.\-]+)+(?:/[\w.\-]+)*")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_RISK_LINE_RE = re.compile(r"\b(blocked|approved|denied|allowed|unsafe|risk)\b", re.IGNORECASE)


@dataclass
class ScientificContinuitySummary:
    decisions_and_rationale: list[str] = field(default_factory=list)
    results_register: list[str] = field(default_factory=list)
    evidence_register: list[str] = field(default_factory=list)
    compliance_register: list[str] = field(default_factory=list)
    open_questions_and_next_actions: list[str] = field(default_factory=list)
    source_format: str = "structured"
    legacy_summary: str = ""

    def has_structured_content(self) -> bool:
        return any(getattr(self, field_name) for field_name, _ in _SECTION_SPECS)


def append_compressed_summary(existing: str, summary: str) -> str:
    existing = existing.strip()
    summary = summary.strip()
    if not existing:
        return summary
    if not summary:
        return existing
    return f"{existing}{COMPRESSED_CONTEXT_SEPARATOR}{summary}"


def split_compressed_context(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [chunk.strip() for chunk in text.split(COMPRESSED_CONTEXT_SEPARATOR) if chunk.strip()]


def parse_compressed_context(text: str) -> list[ScientificContinuitySummary]:
    return [parse_summary_block(chunk) for chunk in split_compressed_context(text)]


def parse_summary_block(text: str) -> ScientificContinuitySummary:
    normalized = text.strip()
    if not normalized:
        return ScientificContinuitySummary()

    summary = ScientificContinuitySummary()
    current_field: str | None = None
    saw_structured_marker = False
    saw_known_section = False
    preamble: list[str] = []

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == STRUCTURED_SUMMARY_HEADER:
            saw_structured_marker = True
            continue

        heading = _match_heading(line)
        if heading:
            current_field = heading
            saw_known_section = True
            continue

        item = _strip_bullet(line)
        if current_field:
            section_items = getattr(summary, current_field)
            if _BULLET_RE.match(line) or not section_items:
                section_items.append(item)
            else:
                section_items[-1] = f"{section_items[-1]} {item}".strip()
        else:
            preamble.append(item)

    if saw_known_section or saw_structured_marker:
        if preamble:
            summary.decisions_and_rationale.append(" ".join(preamble))
        return summary

    return ScientificContinuitySummary(
        results_register=[normalized],
        source_format="legacy",
        legacy_summary=normalized,
    )


def serialize_summary(summary: ScientificContinuitySummary) -> str:
    lines = [STRUCTURED_SUMMARY_HEADER]
    for field_name, title in _SECTION_SPECS:
        lines.append(f"{title}:")
        items = [item.strip() for item in getattr(summary, field_name) if item.strip()]
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- None recorded.")
        lines.append("")
    return "\n".join(lines).strip()


def normalize_generated_summary(model_output: str) -> str:
    parsed = parse_summary_block(model_output)
    if parsed.source_format == "legacy":
        parsed = ScientificContinuitySummary(results_register=[parsed.legacy_summary])
    return enforce_summary_size_limit(parsed)


def format_messages_for_summary(messages: Sequence[dict]) -> str:
    chunks: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role", "assistant")).upper()
        parts = [f"[Message {index}] {role}"]

        content = _prepare_message_text(str(message.get("content", "")).strip(), limit=2400)
        if content:
            parts.append(f"Content: {content}")

        tool_calls = message.get("tool_calls") or []
        for tool_index, call in enumerate(tool_calls, start=1):
            tool_name = str(call.get("tool", "unknown")).strip() or "unknown"
            parts.append(f"Tool call {tool_index}: {tool_name}")

            tool_input = _prepare_message_text(str(call.get("input", "")).strip(), limit=1200)
            if tool_input:
                parts.append(f"Tool input: {tool_input}")

            tool_output = _prepare_message_text(str(call.get("output", "")).strip(), limit=1800)
            if tool_output:
                parts.append(f"Tool output: {tool_output}")

            tool_result = call.get("result")
            if isinstance(tool_result, dict):
                warnings = tool_result.get("warnings")
                if isinstance(warnings, list):
                    for warning in warnings:
                        warning_text = _prepare_message_text(str(warning).strip(), limit=200)
                        if warning_text:
                            parts.append(f"Tool warning: {warning_text}")

                artifact_refs = tool_result.get("artifact_refs")
                if isinstance(artifact_refs, list):
                    for artifact_ref in artifact_refs:
                        if not isinstance(artifact_ref, dict):
                            continue
                        artifact_ref_path = _prepare_message_text(
                            str(artifact_ref.get("path", "")).strip(),
                            limit=600,
                        )
                        if artifact_ref_path:
                            parts.append(f"Tool artifact: {artifact_ref_path}")

                structured_payload = tool_result.get("structured_payload")
                if isinstance(structured_payload, dict):
                    review_status = _prepare_message_text(
                        str(structured_payload.get("review_status", "")).strip(),
                        limit=200,
                    )
                    if review_status:
                        parts.append(f"Evidence review status: {review_status}")
                    review_question = _prepare_message_text(
                        str(structured_payload.get("question", "")).strip(),
                        limit=400,
                    )
                    if review_question:
                        parts.append(f"Evidence review question: {review_question}")
                    requires_review = structured_payload.get("requires_review")
                    if isinstance(requires_review, bool):
                        parts.append(
                            f"Evidence review required: {'yes' if requires_review else 'no'}"
                        )
                    unsupported_claims_present = structured_payload.get(
                        "unsupported_claims_present"
                    )
                    if isinstance(unsupported_claims_present, bool):
                        parts.append(
                            "Unsupported claims present: "
                            f"{'yes' if unsupported_claims_present else 'no'}"
                        )

        chunks.append("\n".join(parts))

    return "\n\n".join(chunks).strip()


def build_summary_prompt(messages: Sequence[dict]) -> list:
    conversation = format_messages_for_summary(messages)
    return [
        SystemMessage(
            content=(
                "You compress BioAPEX conversation history into a scientific continuity summary. "
                f"Reply in English and keep the full summary under {MAX_SUMMARY_CHARS} characters. "
                f"Return ONLY this structure starting with {STRUCTURED_SUMMARY_HEADER!r}: "
                "Decisions and rationale, Results register, Evidence register, Compliance register, "
                "and Open questions and next actions. Use bullet points in every section. "
                "If a section has no important information, write '- None recorded.' "
                "Preserve PMIDs and other stable IDs, file paths, run IDs, claims with their evidence links, "
                "important tool-call results, and any risky action that was blocked or approved."
            )
        ),
        HumanMessage(
            content=(
                "Summarize the following archived conversation history for later scientific continuity:\n\n"
                f"{conversation}"
            )
        ),
    ]


async def generate_structured_summary(messages: Sequence[dict], llm) -> str:
    summary_llm = llm.bind(temperature=0.3)
    response = await summary_llm.ainvoke(build_summary_prompt(messages))
    return normalize_generated_summary(str(response.content).strip())


def build_deterministic_summary(
    messages: Sequence[dict], *, max_chars: int = MAX_SUMMARY_CHARS
) -> str:
    """Build a structured continuity summary without calling an LLM.

    Used by the cheap ``snip`` and ``microcompact`` phases of the compaction
    ladder in :mod:`runtime.compaction`. Instead of asking a model to
    summarize, scan ``messages`` for high-signal fragments (PMIDs, other
    stable IDs, file paths, URLs, tool run IDs, risk/approval lines) and
    deposit them into the appropriate register. The output is enforced
    through :func:`enforce_summary_size_limit` so both LLM and deterministic
    summaries share a single size contract; callers can tighten it further
    via ``max_chars`` — the ``snip`` rung in particular must keep its
    summary smaller than what it archived or compaction grows the prompt
    instead of shrinking it.
    """
    summary = ScientificContinuitySummary()

    evidence_seen: set[str] = set()
    compliance_seen: set[str] = set()
    decision_seen: set[str] = set()
    result_seen: set[str] = set()

    message_list = list(messages)
    exchange_count = sum(
        1 for message in message_list if str(message.get("role", "")).lower() == "user"
    )
    tool_calls_seen = 0

    for message in message_list:
        role = str(message.get("role", "assistant")).strip().lower() or "assistant"
        content_text = str(message.get("content", "") or "").strip()

        for fragment in _extract_salient_fragments(content_text, max_items=8):
            if fragment in evidence_seen:
                continue
            if _RISK_LINE_RE.search(fragment) or _RISK_LINE_RE.search(content_text):
                if fragment not in compliance_seen:
                    summary.compliance_register.append(fragment)
                    compliance_seen.add(fragment)
                    continue
            summary.evidence_register.append(fragment)
            evidence_seen.add(fragment)

        if content_text:
            head = _clip_text_preserving_ends(content_text, limit=180)
            if role == "user":
                if head and head not in decision_seen:
                    summary.decisions_and_rationale.append(f"User asked: {head}")
                    decision_seen.add(head)
            else:
                if head and head not in result_seen:
                    summary.results_register.append(head)
                    result_seen.add(head)

        for call in message.get("tool_calls") or []:
            tool_calls_seen += 1
            tool_name = str(call.get("tool", "unknown")).strip() or "unknown"
            tool_input = str(call.get("input", "") or "").strip()
            tool_output = str(call.get("output", "") or "").strip()

            for fragment in _extract_salient_fragments(
                f"{tool_input}\n{tool_output}", max_items=6
            ):
                if fragment in evidence_seen:
                    continue
                summary.evidence_register.append(fragment)
                evidence_seen.add(fragment)

            risk_source = " ".join((tool_input, tool_output))
            if _RISK_LINE_RE.search(risk_source):
                note = _clip_text_preserving_ends(
                    f"{tool_name}: {risk_source}", limit=160
                )
                if note not in compliance_seen:
                    summary.compliance_register.append(note)
                    compliance_seen.add(note)

            result = call.get("result")
            if isinstance(result, dict):
                status = result.get("status") or result.get("review_status")
                if isinstance(status, str) and status.strip():
                    note = f"{tool_name}: {status.strip()}"
                    if note not in result_seen:
                        summary.results_register.append(note)
                        result_seen.add(note)

    summary.decisions_and_rationale.append(
        f"Archived {len(message_list)} messages ({exchange_count} user turns, "
        f"{tool_calls_seen} tool calls) without LLM summarization."
    )

    if not summary.open_questions_and_next_actions:
        summary.open_questions_and_next_actions.append(
            "See archived batch for full message text and tool outputs."
        )

    return enforce_summary_size_limit(summary, max_chars=max_chars)


def enforce_summary_size_limit(
    summary: ScientificContinuitySummary | str, *, max_chars: int = MAX_SUMMARY_CHARS
) -> str:
    parsed = parse_summary_block(summary) if isinstance(summary, str) else _copy_summary(summary)

    for item_limit in (240, 180, 140, 110, 80):
        candidate = _shrink_summary(parsed, item_limit=item_limit)
        serialized = serialize_summary(candidate)
        if len(serialized) <= max_chars:
            return serialized

    fallback = _shrink_summary(parsed, item_limit=60, max_items_per_section=1)
    serialized = serialize_summary(fallback)
    if len(serialized) <= max_chars:
        return serialized

    minimal = ScientificContinuitySummary(
        decisions_and_rationale=_fallback_section(
            parsed.decisions_and_rationale,
            default="See archived messages for full decision trail.",
        ),
        results_register=_fallback_section(
            parsed.results_register,
            default="See archived messages for detailed results.",
        ),
        evidence_register=_fallback_section(
            parsed.evidence_register,
            default="See archived messages for evidence links and IDs.",
        ),
        compliance_register=_fallback_section(
            parsed.compliance_register,
            default="See archived messages for compliance outcomes.",
        ),
        open_questions_and_next_actions=_fallback_section(
            parsed.open_questions_and_next_actions,
            default="Continue from archived context.",
        ),
    )
    return serialize_summary(_shrink_summary(minimal, item_limit=50, max_items_per_section=1))


def _match_heading(line: str) -> str | None:
    heading = _HEADING_PREFIX_RE.sub("", line).strip()
    heading = heading.rstrip(":").strip().lower()
    heading = _HEADING_NUMBER_RE.sub("", heading).strip()
    normalized_heading = _NON_ALNUM_RE.sub(" ", heading).strip()
    return _HEADING_ALIASES.get(normalized_heading)


def _strip_bullet(line: str) -> str:
    match = _BULLET_RE.match(line)
    if match:
        return match.group(1).strip()
    return line.strip()


def _prepare_message_text(text: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    salient = _extract_salient_fragments(text)
    clipped = _clip_text_preserving_ends(compact, limit=limit)
    if not salient:
        return clipped

    parts = [clipped, f"Key references: {' | '.join(salient)}"]
    combined = "\n".join(parts)
    if len(combined) <= limit:
        return combined
    return _clip_text_preserving_ends(combined, limit=limit)


def _clip_text_preserving_ends(text: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact

    marker = " ... [truncated] ... "
    available = max(0, limit - len(marker))
    head = max(1, int(available * 0.65))
    tail = max(1, available - head)
    return f"{compact[:head].rstrip()}{marker}{compact[-tail:].lstrip()}"


def _extract_salient_fragments(text: str, *, max_items: int = 6) -> list[str]:
    fragments: list[str] = []
    seen: set[str] = set()

    for pattern in (_PMID_RE, _STABLE_ID_RE, _RUN_ID_RE, _PATH_RE, _URL_RE):
        for match in pattern.finditer(text):
            value = match.group(0).strip()
            if value and value not in seen:
                fragments.append(value)
                seen.add(value)
                if len(fragments) >= max_items:
                    return fragments

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _RISK_LINE_RE.search(line):
            candidate = _clip_text_preserving_ends(re.sub(r"\s+", " ", line), limit=120)
            if candidate not in seen:
                fragments.append(candidate)
                seen.add(candidate)
                if len(fragments) >= max_items:
                    return fragments

    return fragments


def _copy_summary(summary: ScientificContinuitySummary) -> ScientificContinuitySummary:
    return ScientificContinuitySummary(
        decisions_and_rationale=list(summary.decisions_and_rationale),
        results_register=list(summary.results_register),
        evidence_register=list(summary.evidence_register),
        compliance_register=list(summary.compliance_register),
        open_questions_and_next_actions=list(summary.open_questions_and_next_actions),
        source_format=summary.source_format,
        legacy_summary=summary.legacy_summary,
    )


def _shrink_summary(
    summary: ScientificContinuitySummary, *, item_limit: int, max_items_per_section: int | None = None
) -> ScientificContinuitySummary:
    shrunk = _copy_summary(summary)
    for field_name, _ in _SECTION_SPECS:
        items = [item for item in getattr(shrunk, field_name) if item.strip()]
        if max_items_per_section is not None:
            items = items[:max_items_per_section]
        setattr(
            shrunk,
            field_name,
            [_clip_text_preserving_ends(item, limit=item_limit) for item in items],
        )
    return shrunk


def _fallback_section(items: Sequence[str], *, default: str) -> list[str]:
    if not items:
        return [default]
    return [_clip_text_preserving_ends(items[0], limit=80)]
