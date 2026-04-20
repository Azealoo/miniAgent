"""Per-session approval state for gated tool calls.

File-first, no database: each session's pending approval decisions live at
``backend/storage/approvals/<session_id>.json``. The store is consulted by
``runtime.query_engine`` when it constructs the ``ToolPolicyExecutionContext``
for a turn; once a decision is consumed (turn completes) it is cleared so the
next gated call re-prompts the reviewer.

Decisions are keyed by tool name. Argument-fingerprint-scoped approvals are
intentionally out of scope for the MVP — the gate pauses the turn right before
the agent would re-invoke the same tool with the same arguments, so the next
turn only needs to know "the reviewer said yes/no to this tool, this turn."
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

ApprovalDecision = Literal["approve", "deny"]

_STORE_SUBDIR = "storage/approvals"


class ApprovalStoreLoadError(RuntimeError):
    """Raised when the on-disk approval store cannot be read or parsed.

    Used by the strict loader so the runtime can fail closed for destructive
    tools instead of silently degrading to "no approvals" when the JSON
    file is corrupt or unreadable.
    """


class ApprovalRecord(TypedDict):
    tool_name: str
    run_id: str
    decision: ApprovalDecision
    actor: str
    rationale: str | None
    recorded_at: str


def _store_path(base_dir: Path, session_id: str) -> Path:
    return Path(base_dir) / _STORE_SUBDIR / f"{session_id}.json"


def _parse_records(raw: object) -> list[ApprovalRecord]:
    if not isinstance(raw, list):
        return []
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
        records.append(
            {
                "tool_name": tool_name,
                "run_id": run_id,
                "decision": decision,
                "actor": str(item.get("actor") or "ui-user"),
                "rationale": (
                    str(item["rationale"]) if isinstance(item.get("rationale"), str) else None
                ),
                "recorded_at": str(item.get("recorded_at") or _now_iso()),
            }
        )
    return records


def _load_strict(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    """Load approval records, raising ``ApprovalStoreLoadError`` on failure.

    A missing file is not a failure — the store is intentionally absent
    between gated calls — but an unreadable or malformed JSON payload is.
    """
    path = _store_path(base_dir, session_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApprovalStoreLoadError(
            f"Approval store for session {session_id} is unreadable."
        ) from exc
    return _parse_records(raw)


def _load(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    path = _store_path(base_dir, session_id)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Approval store for session %s is unreadable; ignoring.", session_id, exc_info=True)
        return []
    return _parse_records(raw)


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
) -> ApprovalRecord:
    record: ApprovalRecord = {
        "tool_name": tool_name,
        "run_id": run_id,
        "decision": decision,
        "actor": actor,
        "rationale": rationale,
        "recorded_at": _now_iso(),
    }
    records = _load(base_dir, session_id)
    # A reviewer may retry an approval decision after a typo — the latest
    # decision for a (tool_name, run_id) tuple wins.
    records = [
        item
        for item in records
        if not (item["tool_name"] == tool_name and item["run_id"] == run_id)
    ]
    records.append(record)
    _save(base_dir, session_id, records)
    return record


def pending_records(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    return list(_load(base_dir, session_id))


def approved_tool_names(base_dir: Path, session_id: str) -> frozenset[str]:
    return frozenset(
        record["tool_name"]
        for record in _load(base_dir, session_id)
        if record["decision"] == "approve"
    )


def denied_records(base_dir: Path, session_id: str) -> list[ApprovalRecord]:
    return [record for record in _load(base_dir, session_id) if record["decision"] == "deny"]


def load_decisions_strict(
    base_dir: Path, session_id: str
) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(approved_tool_names, denied_tool_names)``, raising on failure.

    Callers that need to fail closed when the on-disk store is corrupt
    should use this helper instead of :func:`approved_tool_names` and
    :func:`denied_records`, which swallow load errors and silently report
    "no approvals".
    """
    records = _load_strict(base_dir, session_id)
    approved = frozenset(
        record["tool_name"] for record in records if record["decision"] == "approve"
    )
    denied = frozenset(
        record["tool_name"] for record in records if record["decision"] == "deny"
    )
    return approved, denied


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
    "ApprovalDecision",
    "ApprovalRecord",
    "ApprovalStoreLoadError",
    "approved_tool_names",
    "consume",
    "denied_records",
    "load_decisions_strict",
    "pending_records",
    "record_decision",
]
