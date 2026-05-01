"""Typed session content blocks, schema version, and id validators."""

import re
from typing import Any, Literal

# Pydantic >=2.12 requires ``typing_extensions.TypedDict`` on Python < 3.12 so
# that TypeAdapter can build a core schema (see https://errors.pydantic.dev/
# 2.13/u/typed-dict-version). Using the backport unconditionally keeps the
# schema drift guard working on the CI image (Python 3.11).
from typing_extensions import TypedDict

# Only allow standard UUID v4 strings produced by uuid.uuid4().
# This blocks path traversal payloads like "../config" or "../../etc/passwd".
_SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ARCHIVE_ID_RE = re.compile(r"^\d+$")

SESSION_SCHEMA_VERSION = "session.v3"


class SessionCorruptError(Exception):
    """Raised when a session JSON file cannot be decoded.

    The corrupted file has been moved aside (see ``quarantine_path``) so the
    next read returns an empty session — callers can surface a typed error
    to the UI instead of silently overwriting the user's history.
    """

    def __init__(
        self,
        session_id: str,
        quarantine_path: str,
        *,
        original_error: Exception | None = None,
    ) -> None:
        self.session_id = session_id
        self.quarantine_path = quarantine_path
        self.original_error = original_error
        super().__init__(
            f"Session {session_id!r} JSON was corrupt; quarantined at {quarantine_path}"
        )


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


class SessionApprovalGateBlock(TypedDict, total=False):
    type: Literal["approval_gate"]
    tool: str
    input: str
    run_id: str
    reason: str
    message: str
    result: dict[str, Any]
    policy: dict[str, Any]


class SessionWarningBlock(TypedDict, total=False):
    type: Literal["warning"]
    kind: str
    message: str
    missing: list[str]
    cited: list[str]
    included: list[str]
    review_path: str


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
    | SessionApprovalGateBlock
    | SessionWarningBlock
)


def _validate_session_id(session_id: str) -> None:
    """Raise ValueError if *session_id* does not look like a UUID v4."""
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"Invalid session_id: {session_id!r}")


def _tool_block_key(tool_name: str, run_id: str | None) -> str:
    return run_id or tool_name
