"""Typed session content blocks, schema version, and id validators."""

import re
from typing import Any, Literal, TypedDict

# Only allow standard UUID v4 strings produced by uuid.uuid4().
# This blocks path traversal payloads like "../config" or "../../etc/passwd".
_SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ARCHIVE_ID_RE = re.compile(r"^\d+$")

SESSION_SCHEMA_VERSION = "session.v3"


class SessionTextBlock(TypedDict):
    type: Literal["text"]
    text: str


class SessionToolUseBlock(TypedDict, total=False):
    type: Literal["tool_use"]
    tool: str
    input: str
    run_id: str


class SessionToolResultBlock(TypedDict, total=False):
    type: Literal["tool_result"]
    tool: str
    output: str
    run_id: str
    result: dict[str, Any]


class SessionRetrievalBlock(TypedDict, total=False):
    type: Literal["retrieval"]
    query: str
    results: list[dict[str, Any]]


class SessionUsageBlock(TypedDict):
    type: Literal["usage"]
    metadata: dict[str, Any]


class SessionPlanBlock(TypedDict, total=False):
    type: Literal["plan"]
    event: Literal["created", "updated"]
    summary: str
    run_id: str
    plan: dict[str, Any]
    tool_trace: list[dict[str, Any]]


class SessionVerificationBlock(TypedDict, total=False):
    type: Literal["verification"]
    summary: str
    verdict: Literal["pass", "repair_required", "fail"]
    run_id: str
    verification: dict[str, Any]
    tool_trace: list[dict[str, Any]]


class SessionArchiveIndexEntry(TypedDict):
    archive_id: str | None
    message_count: int


SessionContentBlock = (
    SessionTextBlock
    | SessionToolUseBlock
    | SessionToolResultBlock
    | SessionRetrievalBlock
    | SessionUsageBlock
    | SessionPlanBlock
    | SessionVerificationBlock
)


def _validate_session_id(session_id: str) -> None:
    """Raise ValueError if *session_id* does not look like a UUID v4."""
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")


def _tool_block_key(tool_name: str, run_id: str | None) -> str:
    return run_id or tool_name
