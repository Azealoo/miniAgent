"""Client-side telemetry ingestion.

POST /api/audit/client

Accepts a small typed envelope from the frontend `telemetry` logger and
appends it to the existing audit log as an event of type ``client_error``.
This is the backend half of issue #107 — the frontend surfaces unhandled
React errors (through the ErrorBoundary) and SSE transport failures
(overflow / terminal error events) through this route instead of dropping
them silently in the browser console.

Rate limiting: the endpoint is guarded by an in-process per-client token
bucket. A misbehaving browser tab cannot flood the audit log, and we avoid
pulling in a dedicated rate-limiter dependency (slowapi is not in the
backend requirements). The bucket is keyed on the client IP — loopback
development and lab-network traffic share the same limits because the
audit log storage is the resource we're protecting, not the network path.

PII scrubbing is the frontend's responsibility (see
``frontend/src/lib/telemetry.ts`` for the scrub policy). The backend
enforces hard size caps — message length, stack length, meta JSON size —
so even a bypassed scrub cannot push arbitrary blobs into the audit file.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from audit.store import append_audit_event

router = APIRouter()

# Per-client token bucket. Defaults tuned to absorb a burst of
# error-boundary renders (each one triggers at most one event) while
# refusing to ingest a sustained flood from a stuck loop.
_BUCKET_CAPACITY = 20
_BUCKET_REFILL_PER_SECOND = 0.5  # one token every 2 seconds
_BUCKET_MAX_ENTRIES = 512

_MAX_MESSAGE_CHARS = 500
_MAX_STACK_CHARS = 4_000
_MAX_META_KEYS = 32
_MAX_META_VALUE_CHARS = 1_000
_MAX_EVENT_NAME_CHARS = 80


ClientEventLevel = Literal["error", "warning"]


class ClientEvent(BaseModel):
    level: ClientEventLevel = "error"
    event: str = Field(..., min_length=1, max_length=_MAX_EVENT_NAME_CHARS)
    message: str | None = None
    stack: str | None = None
    meta: dict[str, Any] | None = None
    request_id: str | None = None
    session_id: str | None = None
    user_agent: str | None = None


class ClientEventResponse(BaseModel):
    recorded: bool


def _base_dir() -> Path:
    from graph.agent import agent_manager

    if agent_manager.base_dir is None:
        raise HTTPException(503, "Audit base directory is not initialized.")
    return agent_manager.base_dir


class _TokenBucket:
    """In-process, per-client token bucket keyed on the request remote host."""

    def __init__(
        self,
        capacity: int,
        refill_per_second: float,
        *,
        max_entries: int = _BUCKET_MAX_ENTRIES,
    ) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.max_entries = max_entries
        self._entries: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._entries.get(key, (float(self.capacity), now))
            # Refill proportional to wall-clock elapsed since last take.
            tokens = min(
                float(self.capacity),
                tokens + (now - last) * self.refill_per_second,
            )
            if tokens < 1.0:
                self._entries[key] = (tokens, now)
                return False
            tokens -= 1.0
            self._entries[key] = (tokens, now)
            # Cap the table so a long-lived process with many unique clients
            # cannot grow the dict without bound.
            if len(self._entries) > self.max_entries:
                # Drop the oldest entry (smallest "last" timestamp).
                oldest_key = min(
                    self._entries,
                    key=lambda item: self._entries[item][1],
                )
                if oldest_key != key:
                    self._entries.pop(oldest_key, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


_rate_limiter = _TokenBucket(
    capacity=_BUCKET_CAPACITY,
    refill_per_second=_BUCKET_REFILL_PER_SECOND,
)


def _reset_rate_limiter_for_tests() -> None:
    """Test-only helper; kept module-private to discourage runtime use."""
    _rate_limiter.reset()


def _client_key(request: Request | None) -> str:
    if request is None or request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _truncate(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 16].rstrip() + "...[truncated]"


def _normalize_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    normalized: dict[str, Any] = {}
    for index, (raw_key, raw_value) in enumerate(meta.items()):
        if index >= _MAX_META_KEYS:
            normalized["_meta_truncated"] = True
            break
        key = str(raw_key)[:64]
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            normalized[key] = raw_value
        else:
            normalized[key] = _truncate(str(raw_value), max_chars=_MAX_META_VALUE_CHARS)
    return normalized


@router.post("/audit/client", response_model=ClientEventResponse)
def record_client_event(
    event: ClientEvent,
    request: Request = None,
    response: Response = None,
) -> ClientEventResponse:
    if not _rate_limiter.take(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many client telemetry events; slow down.",
        )

    summary = _truncate(event.message, max_chars=_MAX_MESSAGE_CHARS) or (
        f"Client {event.level} event: {event.event}"
    )
    summary = _truncate(summary, max_chars=240) or "Client event"

    details = {
        "event": event.event,
        "level": event.level,
        "message": _truncate(event.message, max_chars=_MAX_MESSAGE_CHARS),
        "stack": _truncate(event.stack, max_chars=_MAX_STACK_CHARS),
        "user_agent": _truncate(event.user_agent, max_chars=_MAX_META_VALUE_CHARS),
        "meta": _normalize_meta(event.meta),
    }

    append_audit_event(
        _base_dir(),
        event_type="client_error",
        summary=summary,
        outcome=event.level,
        session_id=_truncate(event.session_id, max_chars=64),
        run_id=_truncate(event.request_id, max_chars=64),
        actor="client",
        details=details,
    )
    # 204-style: nothing useful in the body, but keep JSON shape stable for
    # the frontend so the response schema never surprises the logger.
    return ClientEventResponse(recorded=True)
