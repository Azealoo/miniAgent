from __future__ import annotations

import json
import re
from typing import Any, Literal, TypeAlias

from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field

JsonLike: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None

TOOL_RESULT_CONTRACT_VERSION = "tool_result.v1"
MAX_STRUCTURED_PAYLOAD_JSON_CHARS = 16_000
MAX_SOURCE_PAYLOAD_JSON_CHARS = 12_000
_MAX_PAYLOAD_STRING_CHARS = 4_000
_MAX_PAYLOAD_LIST_ITEMS = 25
_MAX_PAYLOAD_DICT_KEYS = 40
_MAX_PAYLOAD_DEPTH = 6

ToolResultStatus = Literal["success", "error"]
ToolResultOutcome = Literal[
    "success",
    "success_empty",
    "blocked",
    "invalid_input",
    "retriable_failure",
    "execution_failure",
]
ToolErrorCode = Literal[
    "blocked",
    "invalid_input",
    "retriable_failure",
    "execution_failure",
]

_TRUNCATED_MARKERS = ("[output truncated]", "...[truncated]")
_INVALID_INPUT_PATTERNS = (
    re.compile(r"\brequired\b", re.I),
    re.compile(r"\binvalid\b", re.I),
    re.compile(r"\bmust be\b", re.I),
    re.compile(r"\bmissing\b", re.I),
    re.compile(r"\bnot found\b", re.I),
    re.compile(r"\bnot a file\b", re.I),
    re.compile(r"\bempty command\b", re.I),
    re.compile(r"\boutside allowed\b", re.I),
    re.compile(r"\bexceeds maximum\b", re.I),
)
_RETRIABLE_PATTERNS = (
    re.compile(r"\btimeout\b", re.I),
    re.compile(r"\btimed out\b", re.I),
    re.compile(r"\btemporar", re.I),
    re.compile(r"\bconnection\b", re.I),
    re.compile(r"\b429\b"),
    re.compile(r"\b5\d{2}\b"),
    re.compile(r"\brate limit", re.I),
)


class ToolArtifactRef(BaseModel):
    path: str | None = None
    label: str | None = None
    artifact_type: str | None = None
    identifier: str | None = None


class ToolResultError(BaseModel):
    code: ToolErrorCode
    message: str
    retriable: bool = False


class ToolResultEnvelope(BaseModel):
    contract_version: str = TOOL_RESULT_CONTRACT_VERSION
    tool_name: str
    summary: str
    structured_payload: JsonLike = None
    artifact_refs: list[ToolArtifactRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: ToolResultStatus = "success"
    outcome: ToolResultOutcome = "success"
    error: ToolResultError | None = None
    metadata: dict[str, JsonLike] = Field(default_factory=dict)
    source_payload: JsonLike = None


def artifact_ref(
    *,
    path: str | None = None,
    label: str | None = None,
    artifact_type: str | None = None,
    identifier: str | None = None,
) -> ToolArtifactRef:
    return ToolArtifactRef(
        path=path,
        label=label,
        artifact_type=artifact_type,
        identifier=identifier,
    )


def truncate_text(text: str, max_len: int, *, marker: str = "\n...[truncated]") -> tuple[str, bool]:
    if len(text) <= max_len:
        return text, False
    return text[:max_len] + marker, True


def json_to_pretty_text(data: Any, max_len: int) -> tuple[str, bool]:
    rendered = json.dumps(data, ensure_ascii=False, indent=2)
    return truncate_text(rendered, max_len)


def success_result(
    tool_name: str,
    summary: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
) -> tuple[str, dict[str, Any]]:
    return build_tool_result(
        tool_name,
        summary,
        structured_payload=structured_payload,
        artifact_refs=artifact_refs,
        warnings=warnings,
        metadata=metadata,
        source_payload=source_payload,
        outcome="success",
    )


def empty_result(
    tool_name: str,
    summary: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
) -> tuple[str, dict[str, Any]]:
    return build_tool_result(
        tool_name,
        summary,
        structured_payload=structured_payload,
        artifact_refs=artifact_refs,
        warnings=warnings,
        metadata=metadata,
        source_payload=source_payload,
        outcome="success_empty",
    )


def blocked_result(
    tool_name: str,
    message: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
) -> tuple[str, dict[str, Any]]:
    summary = message if message.startswith("[BLOCKED]") else f"[BLOCKED] {message}"
    error_message = summary.removeprefix("[BLOCKED]").strip() or "Operation blocked."
    return build_tool_result(
        tool_name,
        summary,
        structured_payload=structured_payload,
        artifact_refs=artifact_refs,
        warnings=warnings,
        metadata=metadata,
        source_payload=source_payload,
        outcome="blocked",
        error=ToolResultError(code="blocked", message=error_message, retriable=False),
    )


def invalid_input_result(
    tool_name: str,
    message: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
) -> tuple[str, dict[str, Any]]:
    summary = message if message.startswith("[ERROR]") else f"[ERROR] {message}"
    error_message = summary.removeprefix("[ERROR]").strip() or "Invalid input."
    return build_tool_result(
        tool_name,
        summary,
        structured_payload=structured_payload,
        artifact_refs=artifact_refs,
        warnings=warnings,
        metadata=metadata,
        source_payload=source_payload,
        outcome="invalid_input",
        error=ToolResultError(code="invalid_input", message=error_message, retriable=False),
    )


def retriable_error_result(
    tool_name: str,
    message: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
) -> tuple[str, dict[str, Any]]:
    summary = message if message.startswith("[ERROR]") else f"[ERROR] {message}"
    error_message = summary.removeprefix("[ERROR]").strip() or "Retriable failure."
    return build_tool_result(
        tool_name,
        summary,
        structured_payload=structured_payload,
        artifact_refs=artifact_refs,
        warnings=warnings,
        metadata=metadata,
        source_payload=source_payload,
        outcome="retriable_failure",
        error=ToolResultError(code="retriable_failure", message=error_message, retriable=True),
    )


def execution_error_result(
    tool_name: str,
    message: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
) -> tuple[str, dict[str, Any]]:
    summary = message if message.startswith("[ERROR]") else f"[ERROR] {message}"
    error_message = summary.removeprefix("[ERROR]").strip() or "Execution failure."
    return build_tool_result(
        tool_name,
        summary,
        structured_payload=structured_payload,
        artifact_refs=artifact_refs,
        warnings=warnings,
        metadata=metadata,
        source_payload=source_payload,
        outcome="execution_failure",
        error=ToolResultError(code="execution_failure", message=error_message, retriable=False),
    )


def build_tool_result(
    tool_name: str,
    summary: str,
    *,
    structured_payload: JsonLike = None,
    artifact_refs: list[ToolArtifactRef] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, JsonLike] | None = None,
    source_payload: JsonLike = None,
    outcome: ToolResultOutcome = "success",
    error: ToolResultError | None = None,
) -> tuple[str, dict[str, Any]]:
    normalized_summary = summary or "(no output)"
    normalized_warnings = list(warnings or [])
    if any(marker in normalized_summary for marker in _TRUNCATED_MARKERS):
        if "output_truncated" not in normalized_warnings:
            normalized_warnings.append("output_truncated")

    normalized_metadata = dict(metadata or {})
    normalized_structured_payload, structured_truncated, structured_chars = _cap_json_payload(
        structured_payload,
        max_chars=MAX_STRUCTURED_PAYLOAD_JSON_CHARS,
    )
    normalized_source_payload, source_truncated, source_chars = _cap_json_payload(
        source_payload,
        max_chars=MAX_SOURCE_PAYLOAD_JSON_CHARS,
    )
    if structured_chars is not None:
        normalized_metadata.setdefault("structured_payload_json_chars", structured_chars)
    if source_chars is not None:
        normalized_metadata.setdefault("source_payload_json_chars", source_chars)
    if structured_truncated and "structured_payload_truncated" not in normalized_warnings:
        normalized_warnings.append("structured_payload_truncated")
    if source_truncated and "source_payload_truncated" not in normalized_warnings:
        normalized_warnings.append("source_payload_truncated")

    status: ToolResultStatus = "error" if outcome not in ("success", "success_empty") or error else "success"
    envelope = ToolResultEnvelope(
        tool_name=tool_name,
        summary=normalized_summary,
        structured_payload=normalized_structured_payload,
        artifact_refs=list(artifact_refs or []),
        warnings=normalized_warnings,
        status=status,
        outcome=outcome,
        error=error,
        metadata=normalized_metadata,
        source_payload=normalized_source_payload,
    )
    return normalized_summary, envelope.model_dump(mode="json")


def is_tool_result_dict(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("contract_version") == TOOL_RESULT_CONTRACT_VERSION
        and "tool_name" in value
        and "summary" in value
    )


def normalize_tool_output(tool_name: str, raw_output: Any) -> ToolResultEnvelope:
    if isinstance(raw_output, ToolResultEnvelope):
        return raw_output

    if isinstance(raw_output, ToolMessage):
        return _normalize_tool_message(tool_name, raw_output)

    if is_tool_result_dict(raw_output):
        return ToolResultEnvelope.model_validate(raw_output)

    if raw_output is None:
        return ToolResultEnvelope(
            tool_name=tool_name,
            summary="(no output)",
            outcome="success_empty",
            metadata={"legacy_output": True},
        )

    if isinstance(raw_output, str):
        return _normalize_legacy_text(tool_name, raw_output)

    if isinstance(raw_output, (dict, list, int, float, bool)):
        return ToolResultEnvelope(
            tool_name=tool_name,
            summary=str(raw_output),
            structured_payload=raw_output,
            metadata={"legacy_output": True},
        )

    return ToolResultEnvelope(
        tool_name=tool_name,
        summary=str(raw_output),
        metadata={"legacy_output": True},
    )


def _normalize_tool_message(tool_name: str, message: ToolMessage) -> ToolResultEnvelope:
    if is_tool_result_dict(message.artifact):
        envelope = ToolResultEnvelope.model_validate(message.artifact)
        if not envelope.summary:
            envelope.summary = _tool_message_content_to_text(message.content)
        return envelope

    summary = _tool_message_content_to_text(message.content)
    envelope = _normalize_legacy_text(tool_name, summary)
    if message.status == "error" and envelope.status != "error":
        envelope.status = "error"
        envelope.outcome = "execution_failure"
        envelope.error = ToolResultError(
            code="execution_failure",
            message=summary or "Tool execution failed.",
            retriable=False,
        )
    return envelope


def _normalize_legacy_text(tool_name: str, text: str) -> ToolResultEnvelope:
    summary = text or "(no output)"
    warnings: list[str] = []
    if any(marker in summary for marker in _TRUNCATED_MARKERS):
        warnings.append("output_truncated")

    stripped = summary.strip()
    if not stripped or stripped == "(no output)":
        return ToolResultEnvelope(
            tool_name=tool_name,
            summary="(no output)",
            outcome="success_empty",
            warnings=warnings,
            metadata={"legacy_output": True},
        )

    if stripped.startswith("[BLOCKED]"):
        message = stripped.removeprefix("[BLOCKED]").strip() or "Operation blocked."
        return ToolResultEnvelope(
            tool_name=tool_name,
            summary=summary,
            warnings=warnings,
            status="error",
            outcome="blocked",
            error=ToolResultError(code="blocked", message=message, retriable=False),
            metadata={"legacy_output": True},
        )

    if stripped.startswith("[ERROR]"):
        message = stripped.removeprefix("[ERROR]").strip() or "Tool execution failed."
        code = _classify_legacy_error(message)
        return ToolResultEnvelope(
            tool_name=tool_name,
            summary=summary,
            warnings=warnings,
            status="error",
            outcome=code,
            error=ToolResultError(
                code=code,
                message=message,
                retriable=code == "retriable_failure",
            ),
            metadata={"legacy_output": True},
        )

    return ToolResultEnvelope(
        tool_name=tool_name,
        summary=summary,
        warnings=warnings,
        metadata={"legacy_output": True},
    )


def _classify_legacy_error(message: str) -> ToolErrorCode:
    if any(pattern.search(message) for pattern in _RETRIABLE_PATTERNS):
        return "retriable_failure"
    if any(pattern.search(message) for pattern in _INVALID_INPUT_PATTERNS):
        return "invalid_input"
    return "execution_failure"


def _tool_message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        rendered: list[str] = []
        for item in content:
            if isinstance(item, str):
                rendered.append(item)
            elif isinstance(item, dict):
                rendered.append(json.dumps(item, ensure_ascii=False, indent=2))
            else:
                rendered.append(str(item))
        return "\n".join(rendered)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False, indent=2)
    return str(content)


def _cap_json_payload(value: JsonLike, *, max_chars: int) -> tuple[JsonLike, bool, int | None]:
    if value is None:
        return None, False, None

    original_chars = _json_char_len(value)
    normalized, normalized_truncated = _normalize_jsonlike(value, depth=0)
    if original_chars is not None and original_chars <= max_chars:
        return normalized, normalized_truncated, original_chars

    normalized_chars = _json_char_len(normalized)
    if normalized_chars is not None and normalized_chars <= max_chars:
        return normalized, True, original_chars or normalized_chars

    preview, _ = truncate_text(
        _json_dump_safe(normalized),
        max_chars,
        marker="\n...[payload truncated]",
    )
    collapsed: JsonLike = {
        "truncated_preview": preview,
        "truncated": True,
        "original_type": type(value).__name__,
    }
    return collapsed, True, original_chars or normalized_chars


def _normalize_jsonlike(value: JsonLike, *, depth: int) -> tuple[JsonLike, bool]:
    if value is None or isinstance(value, (bool, int, float)):
        return value, False

    if isinstance(value, str):
        return truncate_text(
            value,
            _MAX_PAYLOAD_STRING_CHARS,
            marker="\n...[payload truncated]",
        )

    if depth >= _MAX_PAYLOAD_DEPTH:
        preview, _ = truncate_text(
            _json_dump_safe(value),
            _MAX_PAYLOAD_STRING_CHARS,
            marker="\n...[payload truncated]",
        )
        return {
            "truncated_preview": preview,
            "truncated": True,
            "original_type": type(value).__name__,
        }, True

    if isinstance(value, list):
        truncated = False
        items = value[:_MAX_PAYLOAD_LIST_ITEMS]
        normalized_items: list[JsonLike] = []
        for item in items:
            normalized_item, item_truncated = _normalize_jsonlike(item, depth=depth + 1)
            normalized_items.append(normalized_item)
            truncated = truncated or item_truncated
        if len(value) > _MAX_PAYLOAD_LIST_ITEMS:
            truncated = True
            normalized_items.append(
                {
                    "truncated_item_count": len(value) - _MAX_PAYLOAD_LIST_ITEMS,
                    "truncated": True,
                }
            )
        return normalized_items, truncated

    if isinstance(value, dict):
        truncated = False
        normalized_dict: dict[str, JsonLike] = {}
        items = list(value.items())
        for key, item in items[:_MAX_PAYLOAD_DICT_KEYS]:
            normalized_item, item_truncated = _normalize_jsonlike(item, depth=depth + 1)
            normalized_dict[str(key)] = normalized_item
            truncated = truncated or item_truncated
        if len(items) > _MAX_PAYLOAD_DICT_KEYS:
            truncated = True
            normalized_dict["_truncated_key_count"] = len(items) - _MAX_PAYLOAD_DICT_KEYS
        return normalized_dict, truncated

    coerced = str(value)
    return truncate_text(
        coerced,
        _MAX_PAYLOAD_STRING_CHARS,
        marker="\n...[payload truncated]",
    )


def _json_char_len(value: Any) -> int | None:
    try:
        return len(_json_dump_safe(value))
    except Exception:
        return None


def _json_dump_safe(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


__all__ = [
    "MAX_SOURCE_PAYLOAD_JSON_CHARS",
    "MAX_STRUCTURED_PAYLOAD_JSON_CHARS",
    "TOOL_RESULT_CONTRACT_VERSION",
    "ToolArtifactRef",
    "ToolResultEnvelope",
    "ToolResultError",
    "artifact_ref",
    "blocked_result",
    "build_tool_result",
    "empty_result",
    "execution_error_result",
    "invalid_input_result",
    "is_tool_result_dict",
    "json_to_pretty_text",
    "normalize_tool_output",
    "retriable_error_result",
    "success_result",
    "truncate_text",
]
