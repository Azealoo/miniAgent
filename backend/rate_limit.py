"""In-process token-bucket rate limiter for the file API.

Framework-free (no SlowAPI dependency) to keep the backend in line with
the project's "simplicity first" principle. Buckets live in a
process-local dict — this is sufficient for single-worker uvicorn
deployments. Multi-worker or multi-host deployments should front
BioAPEX with a reverse proxy that does global rate limiting.

Rate limits are keyed by bearer-token identity when present on the
incoming request (the route already validated it via
``access_control``), else by client host. Limits live under the
``api_rate_limits`` block in ``backend/config.json`` and are read on
every request so that changes to ``config.json`` take effect for the
next request without a restart.

Setting ``BIOAPEX_RATE_LIMIT_DISABLED=1`` in the process environment
turns the limiter off; it is intended for local development and tests
that drive the API at rates no real user would produce.
"""
from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

import config as cfg

_DISABLE_ENV_VAR = "BIOAPEX_RATE_LIMIT_DISABLED"

# Defaults — tuned for typical file-read / artifact-download volume from a
# single biologist. Overridable via ``api_rate_limits`` in config.json.
DEFAULT_LIMITS: dict[str, dict[str, float | bool]] = {
    "files_read": {"rate": 30, "period_seconds": 60, "enabled": True},
    "files_write": {"rate": 10, "period_seconds": 60, "enabled": True},
}


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


_STATE: dict[tuple[str, str], _Bucket] = {}
_LOCK = threading.Lock()


def _client_identity(request: Request | None) -> str:
    """Return a stable key for the caller.

    Prefers a hashed bearer-token prefix (so the raw token never ends up
    in logs or memory maps), else the request client host, else a
    catch-all ``anon`` sentinel for synthetic / direct-handler invocations.
    """
    if request is None:
        return "anon"
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer":
        cleaned = token.strip()
        if cleaned:
            digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
            return f"bearer:{digest[:16]}"
    client = getattr(request, "client", None)
    host = client.host if client is not None else None
    return f"host:{host or 'unknown'}"


def _resolved_limit(bucket_name: str) -> tuple[float, float, bool]:
    """Return ``(rate, period_seconds, enabled)`` for a named bucket.

    Layering: built-in default → ``api_rate_limits.<bucket_name>`` override.
    Invalid or non-positive values disable the bucket silently so a
    fat-fingered config cannot accidentally lock the API.
    """
    if os.getenv(_DISABLE_ENV_VAR, "").strip() == "1":
        return 0.0, 0.0, False

    runtime = cfg.get_api_rate_limits()
    merged = dict(DEFAULT_LIMITS.get(bucket_name, {"rate": 0, "period_seconds": 60, "enabled": True}))
    overrides = runtime.get(bucket_name)
    if isinstance(overrides, dict):
        merged.update(overrides)

    enabled = bool(merged.get("enabled", True))
    try:
        rate = float(merged.get("rate", 0))
    except (TypeError, ValueError):
        rate = 0.0
    try:
        period = float(merged.get("period_seconds", 60))
    except (TypeError, ValueError):
        period = 60.0
    if rate <= 0 or period <= 0:
        enabled = False
    return rate, period, enabled


def check_rate_limit(request: Request | None, bucket_name: str) -> None:
    """Raise ``HTTPException(429)`` with ``Retry-After`` when drained."""
    rate, period, enabled = _resolved_limit(bucket_name)
    if not enabled:
        return

    refill_per_sec = rate / period
    key = (bucket_name, _client_identity(request))
    now = time.monotonic()

    with _LOCK:
        bucket = _STATE.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=rate, last_refill=now)
            _STATE[key] = bucket
        else:
            elapsed = now - bucket.last_refill
            if elapsed > 0:
                bucket.tokens = min(rate, bucket.tokens + elapsed * refill_per_sec)
                bucket.last_refill = now

        if bucket.tokens < 1.0:
            missing = 1.0 - bucket.tokens
            retry_after = max(1, math.ceil(missing / refill_per_sec))
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {bucket_name}.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.tokens -= 1.0


def clear_buckets() -> None:
    """Drop all in-memory bucket state. Intended for test isolation."""
    with _LOCK:
        _STATE.clear()


__all__ = [
    "DEFAULT_LIMITS",
    "check_rate_limit",
    "clear_buckets",
]
