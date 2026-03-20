"""Deterministic protocol-execution mode with durable protocol-run artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from artifacts import (
    ArtifactReference,
    ComplianceReport,
    ProtocolRun,
    SCHEMA_PACK_VERSION,
    build_content_hash_manifest,
    normalize_identifier,
    prepare_run_directory,
)
from artifacts.schemas import ProtocolStepRecord
from tools.contracts import artifact_ref, blocked_result, invalid_input_result, success_result

PROTOCOL_EXECUTOR_TOOL_NAME = "protocol_executor"
PROTOCOL_EXECUTOR_WORKFLOW_NAME = "protocol-executor"
PROTOCOL_EXECUTOR_SELECTED_WORKFLOW = "protocol-executor"
_OPERATOR_NOT_PROVIDED = "not_provided"
_SOURCE_SECTION_TITLES = (
    "steps",
    "procedure",
    "protocol",
    "instructions",
    "method",
    "preparation instructions",
)
_PROTOCOL_ACTION_PATTERNS = (
    re.compile(r"\bwalk me through\b", re.IGNORECASE),
    re.compile(r"\bguide me through\b", re.IGNORECASE),
    re.compile(r"\bfollow\b", re.IGNORECASE),
    re.compile(r"\bexecute\b", re.IGNORECASE),
    re.compile(r"\brun\b", re.IGNORECASE),
    re.compile(r"\bperform\b", re.IGNORECASE),
    re.compile(r"\bcarry out\b", re.IGNORECASE),
    re.compile(r"\bstart\b", re.IGNORECASE),
)
_PROTOCOL_CONTEXT_PATTERNS = (
    re.compile(r"\bprotocol\b", re.IGNORECASE),
    re.compile(r"\bsop\b", re.IGNORECASE),
    re.compile(r"\bprocedure\b", re.IGNORECASE),
    re.compile(r"\bstep[-\s]?by[-\s]?step\b", re.IGNORECASE),
    re.compile(r"\bsteps\b", re.IGNORECASE),
)
_PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+")
_ORDERED_STEP_RE = re.compile(r"^\s*\d+[\.\)]\s+(?P<text>.+?)\s*$")
_BULLET_STEP_RE = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
_SAMPLE_ID_RE = re.compile(r"\b(sample[-_][a-z0-9._-]+)\b", re.IGNORECASE)
_OPERATOR_PATTERNS = (
    re.compile(r"\boperator[:=\s]+(?P<operator>[A-Za-z0-9._-]+)\b", re.IGNORECASE),
    re.compile(r"\bperformed by (?P<operator>[A-Za-z0-9._-]+)\b", re.IGNORECASE),
)
_SENSITIVE_SUBJECT_RE = re.compile(
    r"\b(sars[-\s]?cov[-\s]?2|influenza|anthrax|ricin|botulinum|pathogen|virus|toxin)\b",
    re.IGNORECASE,
)
_SENSITIVE_ACTION_RE = re.compile(
    r"\b(culture|grow|propagate|amplify|isolate|synthesize|assemble)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SensitiveProtocolAssessment:
    block_detailed_guidance: bool
    reason: str | None = None


class ProtocolExecutorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    attached_identifiers: list[str] = Field(default_factory=list)
    selected_workflow: str | None = None

    @field_validator("user_message")
    @classmethod
    def _validate_user_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("user_message must not be empty.")
        return cleaned

    @field_validator("attached_identifiers")
    @classmethod
    def _validate_attached_identifiers(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = item.strip()
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(candidate)
        return cleaned

    @field_validator("selected_workflow")
    @classmethod
    def _validate_selected_workflow(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


@dataclass(frozen=True)
class ProtocolExecutionClassification:
    is_protocol_request: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedProtocolSource:
    source_ref: ArtifactReference
    kind: Literal["skill", "document", "request_note"]
    display_name: str
    source_text: str
    source_excerpt: str
    read_error: str | None = None


@dataclass(frozen=True)
class ProtocolExecutorResult:
    protocol_run: ProtocolRun
    artifact_path: Path
    artifact_relpath: str
    tool_input: str
    tool_summary: str
    tool_result: dict
    response_text: str


def classify_protocol_execution_request(
    base_dir: Path | str,
    payload: ProtocolExecutorInput,
) -> ProtocolExecutionClassification:
    if payload.selected_workflow not in {None, PROTOCOL_EXECUTOR_SELECTED_WORKFLOW}:
        return ProtocolExecutionClassification(is_protocol_request=False, reasons=())

    reasons: list[str] = []
    if payload.selected_workflow == PROTOCOL_EXECUTOR_SELECTED_WORKFLOW:
        reasons.append("selected-workflow")

    message = payload.user_message
    lowered = message.casefold()
    if any(pattern.search(message) for pattern in _PROTOCOL_ACTION_PATTERNS):
        reasons.append("execution-language")
    if any(pattern.search(message) for pattern in _PROTOCOL_CONTEXT_PATTERNS):
        reasons.append("protocol-language")
    if _extract_path_tokens(message):
        reasons.append("source-path-mentioned")
    if _find_named_skill(base_dir, payload.attached_identifiers + [message]) is not None:
        reasons.append("skill-mentioned")
    if any(_safe_resolve_workspace_file(base_dir, item) is not None for item in payload.attached_identifiers):
        reasons.append("attached-source-file")
    if "protocol execution" in lowered:
        reasons.append("protocol-execution-mode")

    is_protocol_request = (
        payload.selected_workflow == PROTOCOL_EXECUTOR_SELECTED_WORKFLOW
        or ("execution-language" in reasons and any(
            reason in reasons
            for reason in (
                "protocol-language",
                "source-path-mentioned",
                "skill-mentioned",
                "attached-source-file",
                "protocol-execution-mode",
            )
        ))
    )
    return ProtocolExecutionClassification(
        is_protocol_request=is_protocol_request,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def run_protocol_executor(
    base_dir: Path | str,
    payload: ProtocolExecutorInput,
    *,
    compliance_report: ComplianceReport,
    compliance_artifact_relpath: str,
    classification: ProtocolExecutionClassification,
) -> ProtocolExecutorResult:
    base_path = Path(base_dir).resolve()
    layout = prepare_run_directory(base_path, PROTOCOL_EXECUTOR_WORKFLOW_NAME)
    source = _resolve_protocol_source(
        base_path,
        layout=layout,
        payload=payload,
    )
    source_is_unreadable = source.read_error is not None
    candidate_steps = (
        _build_protocol_steps(source.source_text)
        if source.kind != "request_note" and not source_is_unreadable
        else []
    )
    source_has_explicit_steps = bool(candidate_steps)
    sensitive_assessment = _assess_sensitive_protocol_guidance(
        payload=payload,
        source=source,
    )
    steps = (
        []
        if (
            source.kind == "request_note"
            or source_is_unreadable
            or not source_has_explicit_steps
            or sensitive_assessment.block_detailed_guidance
        )
        else candidate_steps
    )
    assumptions = _build_assumptions(
        payload,
        source=source,
        source_has_explicit_steps=source_has_explicit_steps,
        sensitive_assessment=sensitive_assessment,
    )
    related_artifacts = [
        ArtifactReference(
            artifact_type="compliance_report",
            path=compliance_artifact_relpath,
            id=compliance_report.id,
            run_id=compliance_report.run_id,
        )
    ]
    completion_state: Literal["in_progress", "blocked"] = (
        "blocked"
        if (
            source.kind == "request_note"
            or source_is_unreadable
            or not source_has_explicit_steps
            or sensitive_assessment.block_detailed_guidance
        )
        else "in_progress"
    )
    protocol_run = ProtocolRun.model_validate(
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "protocol_run",
            "id": normalize_identifier(f"protocol-run-{layout.run_id}"),
            "run_id": layout.run_id,
            "created_at": layout.created_at,
            "source_workflow": PROTOCOL_EXECUTOR_WORKFLOW_NAME,
            "source_agent": PROTOCOL_EXECUTOR_TOOL_NAME,
            "related_artifacts": [ref.model_dump(mode="json") for ref in related_artifacts],
            "protocol_source": source.source_ref.model_dump(mode="json"),
            "operator": _extract_operator(payload.user_message),
            "sample_ids": _extract_sample_ids(payload.user_message),
            "materials": [],
            "reagent_lots": [],
            "equipment": [],
            "started_at": layout.created_at,
            "completion_state": completion_state,
            "steps": [step.model_dump(mode="json") for step in steps],
            "deviations": [],
            "assumptions": assumptions,
        }
    )

    artifact_path = layout.stable_artifact_path("protocol_run")
    artifact_relpath = layout.stable_artifact_relpath("protocol_run").as_posix()
    protocol_payload = yaml.safe_dump(
        protocol_run.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=False,
    )
    artifact_path.write_text(protocol_payload, encoding="utf-8")
    _refresh_content_hash_manifest(layout)

    tool_input = _build_tool_input(payload, source)
    guidance_policy = (
        "Sequential execution guidance is emitted only when compliance preflight allows the turn "
        "and an explicit source protocol or skill was read. Otherwise BioAPEX stops before "
        "procedural detail is emitted."
    )
    structured_payload = {
        "mode": "protocol_execution",
        "classification": {
            "is_protocol_request": classification.is_protocol_request,
            "reasons": list(classification.reasons),
        },
        "guidance_policy": guidance_policy,
        "source": {
            "kind": source.kind,
            "display_name": source.display_name,
            "path": source.source_ref.path,
            "artifact_type": source.source_ref.artifact_type,
            "excerpt": source.source_excerpt,
            "readable": not source_is_unreadable,
            "read_error": source.read_error,
        },
        "safety_boundary": {
            "detailed_guidance_allowed": not sensitive_assessment.block_detailed_guidance,
            "blocked_reason": sensitive_assessment.reason,
            "allowed_high_level_guidance": (
                "source acknowledgement and escalation guidance only"
                if sensitive_assessment.block_detailed_guidance
                else "source-grounded sequential protocol guidance"
            ),
        },
        "protocol_run": {
            "id": protocol_run.id,
            "run_id": protocol_run.run_id,
            "artifact_path": artifact_relpath,
            "completion_state": protocol_run.completion_state,
            "step_count": len(protocol_run.steps),
            "assumptions": protocol_run.assumptions,
            "sample_ids": protocol_run.sample_ids,
        },
    }
    warnings = ["assumptions_recorded"] if assumptions else []
    if source.kind == "request_note":
        warnings.append("protocol_source_missing")
    elif source_is_unreadable:
        warnings.append("protocol_source_unreadable")
    elif not source_has_explicit_steps:
        warnings.append("protocol_source_unstructured")
    if sensitive_assessment.block_detailed_guidance:
        warnings.append("sensitive_procedural_detail_blocked")

    artifact_refs = [
        artifact_ref(
            path=artifact_relpath,
            label="protocol_run",
            artifact_type="protocol_run",
            identifier=protocol_run.id,
        ),
        artifact_ref(
            path=compliance_artifact_relpath,
            label="compliance_report",
            artifact_type="compliance_report",
            identifier=compliance_report.id,
        ),
    ]

    if source.kind == "request_note" or source_is_unreadable or not source_has_explicit_steps:
        tool_summary, tool_result = invalid_input_result(
            PROTOCOL_EXECUTOR_TOOL_NAME,
            (
                "Protocol execution requires an explicit protocol source or skill before it can proceed."
                if source.kind == "request_note"
                else "Protocol execution requires a readable text source before it can proceed."
                if source_is_unreadable
                else "Protocol execution requires a source that yields explicit sequential steps before it can proceed."
            ),
            structured_payload=structured_payload,
            artifact_refs=artifact_refs,
            warnings=warnings,
            metadata={
                "completion_state": protocol_run.completion_state,
                "source_kind": source.kind,
                "source_read_error": source.read_error,
                "step_count": len(protocol_run.steps),
            },
        )
        if source.kind == "request_note":
            response_text = (
                "Protocol execution mode was requested, but no explicit source protocol or skill was "
                "provided. BioAPEX did not emit sequential procedural guidance.\n\n"
                "Provide a concrete source such as a workspace file path like "
                "`backend/knowledge/protocols/...` or a skill name like "
                "`protocol_from_knowledge`, `buffer_recipe_scaler`, `dilution_calculator`, or "
                "`unit_conversion`, then retry.\n\n"
                f"Recorded blocked protocol run: {artifact_relpath}"
            )
        elif source_is_unreadable:
            source_read_issue = (
                "could not be decoded as UTF-8 text"
                if source.read_error == "unicode_decode_error"
                else "could not be read from disk"
            )
            response_text = (
                f"Protocol execution mode read `{source.display_name}`, but the source {source_read_issue}. "
                "BioAPEX did not emit procedural guidance from an unreadable "
                "source.\n\n"
                f"Recorded blocked protocol run: {artifact_relpath}"
            )
        else:
            response_text = (
                f"Protocol execution mode read `{source.display_name}`, but the source did not yield "
                "an explicit sequential step list. BioAPEX did not emit procedural guidance from an "
                "unstructured source.\n\n"
                f"Recorded blocked protocol run: {artifact_relpath}"
            )
    elif sensitive_assessment.block_detailed_guidance:
        tool_summary, tool_result = blocked_result(
            PROTOCOL_EXECUTOR_TOOL_NAME,
            "Detailed operational protocol guidance is blocked for this sensitive procedure.",
            structured_payload=structured_payload,
            artifact_refs=artifact_refs,
            warnings=warnings,
            metadata={
                "completion_state": protocol_run.completion_state,
                "source_kind": source.kind,
                "step_count": len(protocol_run.steps),
                "blocked_reason": sensitive_assessment.reason,
            },
        )
        response_text = (
            "Protocol execution mode identified a sensitive procedure in the requested source. "
            "BioAPEX will not emit step-by-step operational instructions for this protocol.\n\n"
            "Allowed output in this path is limited to acknowledging the source, recording the "
            "blocked run, and directing the user to approved institutional oversight or SOP review.\n\n"
            f"Recorded blocked protocol run: {artifact_relpath}"
        )
    else:
        tool_summary, tool_result = success_result(
            PROTOCOL_EXECUTOR_TOOL_NAME,
            f"Protocol execution mode started from {source.display_name} with {len(protocol_run.steps)} explicit step(s).",
            structured_payload=structured_payload,
            artifact_refs=artifact_refs,
            warnings=warnings,
            metadata={
                "completion_state": protocol_run.completion_state,
                "source_kind": source.kind,
                "step_count": len(protocol_run.steps),
            },
        )
        response_text = _build_response_text(
            source=source,
            protocol_run=protocol_run,
            artifact_relpath=artifact_relpath,
        )

    return ProtocolExecutorResult(
        protocol_run=protocol_run,
        artifact_path=artifact_path,
        artifact_relpath=artifact_relpath,
        tool_input=tool_input,
        tool_summary=tool_summary,
        tool_result=tool_result,
        response_text=response_text,
    )


def _resolve_protocol_source(
    base_path: Path,
    *,
    layout,
    payload: ProtocolExecutorInput,
) -> ResolvedProtocolSource:
    for candidate in payload.attached_identifiers:
        resolved = _safe_resolve_workspace_file(base_path, candidate)
        if resolved is not None:
            return _materialize_resolved_source(base_path, resolved)

    for token in _extract_path_tokens(payload.user_message):
        resolved = _safe_resolve_workspace_file(base_path, token)
        if resolved is not None:
            return _materialize_resolved_source(base_path, resolved)

    named_skill = _find_named_skill(base_path, payload.attached_identifiers + [payload.user_message])
    if named_skill is not None:
        return _materialize_resolved_source(base_path, named_skill)

    request_note_relpath = layout.user_input_relpath(
        "protocol-source-request.txt",
        slot="protocol-source",
    ).as_posix()
    request_note_path = layout.user_input_path(
        "protocol-source-request.txt",
        slot="protocol-source",
    )
    request_note_text = (
        "Protocol execution was requested without an explicit source protocol or skill.\n"
        f"user_message: {payload.user_message}\n"
        f"attached_identifiers: {', '.join(payload.attached_identifiers) if payload.attached_identifiers else 'none'}\n"
        f"selected_workflow: {payload.selected_workflow or 'none'}\n"
    )
    request_note_path.write_text(request_note_text, encoding="utf-8")
    return ResolvedProtocolSource(
        source_ref=ArtifactReference(
            artifact_type="protocol_source_request",
            path=request_note_relpath,
            id=normalize_identifier(f"protocol-source-request-{layout.run_id}"),
            run_id=layout.run_id,
        ),
        kind="request_note",
        display_name="explicit-source-required",
        source_text="",
        source_excerpt="No explicit source protocol or skill was provided.",
    )


def _materialize_resolved_source(base_path: Path, path: Path) -> ResolvedProtocolSource:
    relative_path = path.relative_to(base_path).as_posix()
    kind: Literal["skill", "document"] = "skill" if path.name == "SKILL.md" else "document"
    source_name = path.parent.name if kind == "skill" else path.name
    source_id = normalize_identifier(
        f"{'skill' if kind == 'skill' else 'protocol-source'}-{path.parent.name if kind == 'skill' else path.stem}"
    )
    artifact_type = "skill_definition" if kind == "skill" else "protocol_document"
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ResolvedProtocolSource(
            source_ref=ArtifactReference(
                artifact_type=artifact_type,
                path=relative_path,
                id=source_id,
            ),
            kind=kind,
            display_name=source_name,
            source_text="",
            source_excerpt="Source could not be decoded as UTF-8 text.",
            read_error="unicode_decode_error",
        )
    except OSError:
        return ResolvedProtocolSource(
            source_ref=ArtifactReference(
                artifact_type=artifact_type,
                path=relative_path,
                id=source_id,
            ),
            kind=kind,
            display_name=source_name,
            source_text="",
            source_excerpt="Source could not be read from disk.",
            read_error="os_error",
        )
    return ResolvedProtocolSource(
        source_ref=ArtifactReference(
            artifact_type=artifact_type,
            path=relative_path,
            id=source_id,
        ),
        kind=kind,
        display_name=source_name,
        source_text=text,
        source_excerpt=_build_source_excerpt(text),
    )


def _build_source_excerpt(text: str) -> str:
    excerpts: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("---") or line.startswith("#"):
            continue
        excerpts.append(line)
        if len(" ".join(excerpts)) >= 180:
            break
    excerpt = " ".join(excerpts).strip()
    if len(excerpt) > 220:
        return excerpt[:217] + "..."
    return excerpt


def _build_protocol_steps(source_text: str) -> list[ProtocolStepRecord]:
    steps: list[ProtocolStepRecord] = []
    for index, item in enumerate(_extract_structured_steps(source_text), start=1):
        cleaned = _clean_step_text(item)
        if not cleaned:
            continue
        step_id = normalize_identifier(f"step-{index:02d}")
        status = "in_progress" if index == 1 else "pending"
        steps.append(
            ProtocolStepRecord(
                step_id=step_id,
                sequence_number=index,
                title=_build_step_title(cleaned, index=index),
                instruction=cleaned,
                status=status,
            )
        )
    return steps


def _extract_structured_steps(source_text: str) -> list[str]:
    steps_in_section: list[str] = []
    in_frontmatter = False
    in_code_block = False
    active_section = False

    for line_number, raw_line in enumerate(source_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if line_number == 1 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        heading_match = _HEADING_RE.match(raw_line)
        if heading_match:
            title = heading_match.group("title").strip().casefold()
            active_section = any(section in title for section in _SOURCE_SECTION_TITLES)
            continue

        step_text = _match_step_line(raw_line)
        if step_text is None:
            continue
        if active_section:
            steps_in_section.append(step_text)

    return _dedupe_text_items(steps_in_section)


def _match_step_line(raw_line: str) -> str | None:
    ordered_match = _ORDERED_STEP_RE.match(raw_line)
    if ordered_match:
        return ordered_match.group("text")
    bullet_match = _BULLET_STEP_RE.match(raw_line)
    if bullet_match:
        return bullet_match.group("text")
    return None


def _build_step_title(text: str, *, index: int) -> str:
    candidate = re.split(r"[.;:]", text, maxsplit=1)[0].strip()
    if 2 <= len(candidate.split()) <= 8 and len(candidate) <= 80:
        return candidate
    return f"Step {index}"


def _clean_step_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.replace("`", "")).strip()
    return cleaned.rstrip(".") + "." if cleaned and cleaned[-1].isalnum() else cleaned


def _build_assumptions(
    payload: ProtocolExecutorInput,
    *,
    source: ResolvedProtocolSource,
    source_has_explicit_steps: bool,
    sensitive_assessment: SensitiveProtocolAssessment,
) -> list[str]:
    assumptions: list[str] = []
    if source.kind == "request_note":
        assumptions.append(
            "Protocol execution was blocked because no explicit source protocol or skill was provided."
        )
    elif source.read_error == "unicode_decode_error":
        assumptions.append(
            "Protocol execution was blocked because the provided source could not be decoded as UTF-8 text."
        )
    elif source.read_error == "os_error":
        assumptions.append(
            "Protocol execution was blocked because the provided source could not be read from disk."
        )
    elif not source_has_explicit_steps:
        assumptions.append(
            "Protocol execution was blocked because the provided source did not yield explicit sequential steps."
        )
    if sensitive_assessment.block_detailed_guidance:
        assumptions.append(
            "Detailed procedural guidance was blocked because the source or request matched sensitive-procedure signals."
        )
    if not _extract_sample_ids(payload.user_message):
        assumptions.append("No sample identifiers were provided at protocol start.")
    if _extract_operator(payload.user_message) == _OPERATOR_NOT_PROVIDED:
        assumptions.append(
            "Operator identity was not supplied in the request, so BioAPEX recorded operator as not_provided."
        )
    assumptions.append(
        "Materials, reagent lots, and equipment were not inferred from the request and remain unconfirmed until explicitly recorded."
    )
    return assumptions


def _extract_sample_ids(message: str) -> list[str]:
    sample_ids: list[str] = []
    seen: set[str] = set()
    for match in _SAMPLE_ID_RE.findall(message):
        normalized = normalize_identifier(match)
        if normalized in seen:
            continue
        seen.add(normalized)
        sample_ids.append(normalized)
    return sample_ids


def _extract_operator(message: str) -> str:
    for pattern in _OPERATOR_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        operator = match.group("operator").strip()
        if operator:
            return operator
    return _OPERATOR_NOT_PROVIDED


def _assess_sensitive_protocol_guidance(
    *,
    payload: ProtocolExecutorInput,
    source: ResolvedProtocolSource,
) -> SensitiveProtocolAssessment:
    combined_text = "\n".join(
        item for item in (payload.user_message, source.display_name, source.source_text) if item
    )
    if _SENSITIVE_SUBJECT_RE.search(combined_text) and _SENSITIVE_ACTION_RE.search(combined_text):
        return SensitiveProtocolAssessment(
            block_detailed_guidance=True,
            reason="sensitive_procedure_detected",
        )
    return SensitiveProtocolAssessment(block_detailed_guidance=False)


def _build_tool_input(payload: ProtocolExecutorInput, source: ResolvedProtocolSource) -> str:
    parts = [payload.user_message]
    if payload.attached_identifiers:
        parts.append(f"attachments={', '.join(payload.attached_identifiers)}")
    if payload.selected_workflow:
        parts.append(f"selected_workflow={payload.selected_workflow}")
    parts.append(f"resolved_source={source.source_ref.path}")
    return "\n".join(parts)


def _build_response_text(
    *,
    source: ResolvedProtocolSource,
    protocol_run: ProtocolRun,
    artifact_relpath: str,
) -> str:
    lines = [
        f"Protocol execution mode started from `{source.display_name}`.",
        "BioAPEX is emitting only source-grounded sequential guidance and will not invent missing procedural details.",
        "",
        "Sequential steps:",
    ]
    for step in protocol_run.steps[:8]:
        lines.append(f"{step.sequence_number}. {step.instruction}")
    if len(protocol_run.steps) > 8:
        lines.append(
            f"... {len(protocol_run.steps) - 8} additional step(s) were recorded in `{artifact_relpath}`."
        )
    if protocol_run.assumptions:
        lines.extend(["", "Recorded assumptions:"])
        for assumption in protocol_run.assumptions:
            lines.append(f"- {assumption}")
    lines.extend(["", f"Protocol run artifact: `{artifact_relpath}`"])
    return "\n".join(lines)


def _safe_resolve_workspace_file(base_dir: Path | str, candidate: str) -> Path | None:
    raw = candidate.strip().strip("`'\"")
    if not raw:
        return None
    path_candidate = Path(raw)
    if path_candidate.is_absolute():
        resolved = path_candidate.resolve()
    else:
        resolved = (Path(base_dir).resolve() / raw).resolve()
    try:
        resolved.relative_to(Path(base_dir).resolve())
    except ValueError:
        return None
    if not resolved.is_file():
        return None
    return resolved


def _extract_path_tokens(message: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _PATH_TOKEN_RE.findall(message):
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _find_named_skill(base_dir: Path | str, text_candidates: list[str]) -> Path | None:
    skills_root = Path(base_dir).resolve() / "backend" / "skills"
    if not skills_root.is_dir():
        return None

    skill_paths = {
        skill_dir.name: skill_dir / "SKILL.md"
        for skill_dir in skills_root.iterdir()
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file()
    }
    lowered_text = " ".join(text_candidates).casefold()
    for skill_name, path in sorted(skill_paths.items()):
        if re.search(rf"\b{re.escape(skill_name.casefold())}\b", lowered_text):
            return path
    return None


def _dedupe_text_items(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        normalized = _clean_step_text(item)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _refresh_content_hash_manifest(layout) -> None:
    entries: dict[str, bytes] = {}
    for path in sorted(layout.run_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(layout.run_dir).as_posix()
        if relative == "content_hashes.json":
            continue
        entries[relative] = path.read_bytes()

    manifest = build_content_hash_manifest(
        run_id=layout.run_id,
        schema_version=SCHEMA_PACK_VERSION,
        created_at=layout.created_at,
        source_workflow=layout.workflow,
        entries=entries,
    )
    layout.content_hash_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "PROTOCOL_EXECUTOR_SELECTED_WORKFLOW",
    "PROTOCOL_EXECUTOR_TOOL_NAME",
    "PROTOCOL_EXECUTOR_WORKFLOW_NAME",
    "ProtocolExecutionClassification",
    "ProtocolExecutorInput",
    "ProtocolExecutorResult",
    "classify_protocol_execution_request",
    "run_protocol_executor",
]
