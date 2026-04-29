"""Per-session approval state for gated tool calls.

File-first, no database: each session's pending approval decisions live at
``backend/storage/approvals/<session_id>.json``. The store is consulted by
``runtime.query_engine`` when it constructs the ``ToolPolicyExecutionContext``
for a turn; once a decision is consumed (turn completes) it is cleared so the
next gated call re-prompts the reviewer.

Decisions are keyed by ``(session_id, tool_name, args_hash)`` with a short TTL
(``APPROVAL_TTL_SECONDS``). An approval recorded for one set of tool arguments
no longer applies to a later call with different arguments — the policy layer
computes the args hash at gate-evaluation time and matches against the stored
record. Expired records are dropped on load. Records for destructive
manifests are stored but intentionally ignored at lookup time so destructive
tools always re-prompt (see ``tools.policy._user_has_approved``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)

ApprovalDecision = Literal["approve", "deny"]

_STORE_SUBDIR = "storage/approvals"

# How long a recorded approval/deny remains valid. After this window the
# record is dropped on load and the reviewer must decide again. Short enough
# that an abandoned approval cannot be silently reused by a later turn.
APPROVAL_TTL_SECONDS = 300


class ApprovalRecord(TypedDict):
    tool_name: str
    run_id: str
    args_hash: str
    decision: ApprovalDecision
    actor: str
    rationale: str | None
    recorded_at: str


def compute_args_hash(kwargs: dict[str, Any] | None) -> str:
    """Return a stable SHA-256 digest over the tool's canonical-JSON kwargs.

    Uses ``sort_keys=True`` and ``default=str`` so non-JSON-native values
    (paths, datetimes, etc.) still produce a stable digest. ``None`` and an
    empty dict both hash to the canonical empty-dict digest so callers that
    have no kwargs still get a deterministic value to match against.
    """
    payload = kwargs or {}
    try:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        # Defensive fallback: a weird unserializable arg should still produce
        # a digest rather than raise through the policy layer.
        canonical = repr(sorted(payload.items())) if isinstance(payload, dict) else repr(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _store_path(base_dir: Path, session_id: str) -> Path:
    return Path(base_dir) / _STORE_SUBDIR / f"{session_id}.json"


def _parse_recorded_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_expired(record: ApprovalRecord, *, now: datetime | None = None) -> bool:
    recorded_at = _parse_recorded_at(record.get("recorded_at"))
    if recorded_at is None:
        # Unparseable timestamps are treated as expired — safer to re-prompt
        # than to honor an ambiguous record.
        return True
    reference = now or datetime.now(timezone.utc)
    return (reference - recorded_at) > timedelta(seconds=APPROVAL_TTL_SECONDS)


def _load(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    path = _store_path(base_dir, session_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Approval store for session %s is unreadable; ignoring.", session_id, exc_info=True)
        return []
    if not isinstance(raw, list):
        return []
    now = datetime.now(timezone.utc)
    records: list[ApprovalRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool_name")
        run_id = item.get("run_id")
        decision = item.get("decision")
        if not isinstance(tool_name, str) or not isinstance(run_id, str):
            continue
        if decision not in {"approve", "deny"}:
            continue
        args_hash = item.get("args_hash")
        if not isinstance(args_hash, str):
            args_hash = ""
        record: ApprovalRecord = {
            "tool_name": tool_name,
            "run_id": run_id,
            "args_hash": args_hash,
            "decision": decision,
            "actor": str(item.get("actor") or "ui-user"),
            "rationale": (
                str(item["rationale"]) if isinstance(item.get("rationale"), str) else None
            ),
            "recorded_at": str(item.get("recorded_at") or _now_iso()),
        }
        if _is_expired(record, now=now):
            continue
        records.append(record)
    return records


def _save(base_dir: Path, session_id: str, records: list[ApprovalRecord]) -> None:
    path = _store_path(base_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records, ensure_ascii=False, indent=2)
    # Atomic write so a crashed backend never leaves a half-written JSON file.
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{session_id}.",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_decision(
    base_dir: Path,
    *,
    session_id: str,
    tool_name: str,
    run_id: str,
    decision: ApprovalDecision,
    actor: str,
    rationale: str | None,
    args_hash: str = "",
) -> ApprovalRecord:
    record: ApprovalRecord = {
        "tool_name": tool_name,
        "run_id": run_id,
        "args_hash": args_hash,
        "decision": decision,
        "actor": actor,
        "rationale": rationale,
        "recorded_at": _now_iso(),
    }
    records = _load(base_dir, session_id)
    # A reviewer may retry an approval decision after a typo — the latest
    # decision for a (tool_name, run_id, args_hash) tuple wins.
    records = [
        item
        for item in records
        if not (
            item["tool_name"] == tool_name
            and item["run_id"] == run_id
            and item.get("args_hash", "") == args_hash
        )
    ]
    records.append(record)
    _save(base_dir, session_id, records)
    return record


def pending_records(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    return list(_load(base_dir, session_id))


def approved_tool_runs(base_dir: Path, session_id: str) -> frozenset[tuple[str, str]]:
    """Return ``(tool_name, args_hash)`` tuples the reviewer approved.

    The policy layer is responsible for filtering destructive manifests out
    of the matched set — that rule lives next to the manifest, not here.
    """
    return frozenset(
        (record["tool_name"], record.get("args_hash", ""))
        for record in _load(base_dir, session_id)
        if record["decision"] == "approve"
    )


def denied_tool_runs(base_dir: Path, session_id: str) -> frozenset[tuple[str, str]]:
    return frozenset(
        (record["tool_name"], record.get("args_hash", ""))
        for record in _load(base_dir, session_id)
        if record["decision"] == "deny"
    )


def denied_records(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    return [record for record in _load(base_dir, session_id) if record["decision"] == "deny"]


def consume(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    """Return and clear pending decisions.

    Called at the end of a successful turn so the same approval is not silently
    re-applied on the next, unrelated gated call.
    """
    records = _load(base_dir, session_id)
    if not records:
        return []
    path = _store_path(base_dir, session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning(
            "Failed to clear approval store for session %s",
            session_id,
            exc_info=True,
        )
    return records


__all__ = [
    "APPROVAL_TTL_SECONDS",
    "ApprovalDecision",
    "ApprovalRecord",
    "approved_tool_runs",
    "compute_args_hash",
    "consume",
    "denied_records",
    "denied_tool_runs",
    "pending_records",
    "record_decision",
]
