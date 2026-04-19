"""Primary -> fallback model selection wrapper for LLM invocations.

Catches overload/timeout exceptions from the primary chat model, rebuilds
the client using the role's configured ``fallback_model``, and emits an
audit line so the switch is observable. Orthogonal to the verification
repair retry in :mod:`runtime.query_engine` and to any output-token
escalation loop — this wrapper handles only the primary->fallback switch.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from audit.store import append_audit_event
from runtime.model_factory import (
    ModelRole,
    build_chat_model,
    build_fallback_chat_model,
    get_role_model_config,
)

T = TypeVar("T")
logger = logging.getLogger(__name__)


def is_overload_or_timeout(exc: BaseException) -> bool:
    """Return True for anthropic/openai 529/overload or timeout exceptions.

    Duck-typed so neither SDK is required at import time. Recognises:
      * HTTP status 529 / 503 (overload-like)
      * Anthropic-style ``body['error']['type']`` containing ``overload``
      * Class names ending in ``Timeout`` or ``TimeoutError``
      * Messages containing ``overload`` or ``529``
    """
    name = type(exc).__name__
    if name.endswith("TimeoutError") or name.endswith("Timeout"):
        return True

    status = getattr(exc, "status_code", None)
    if status in (529, 503):
        return True

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            etype = str(err.get("type") or "").lower()
            if "overload" in etype:
                return True

    msg = str(exc).lower()
    if "overload" in msg or "529" in msg:
        return True
    return False


def _emit_fallback_audit(
    *,
    base_dir: Path | str | None,
    role: ModelRole,
    primary_model: str,
    fallback_model: str,
    exc: BaseException,
    session_id: str | None,
) -> None:
    summary = (
        f"Primary {role} model '{primary_model}' fell back to '{fallback_model}' "
        f"after {type(exc).__name__}."
    )
    if base_dir is None:
        logger.info("model_fallback role=%s primary=%s fallback=%s reason=%s",
                    role, primary_model, fallback_model, type(exc).__name__)
        return
    append_audit_event(
        base_dir,
        event_type="model_fallback",
        summary=summary,
        outcome="fallback",
        session_id=session_id,
        details={
            "role": role,
            "primary_model": primary_model,
            "fallback_model": fallback_model,
            "exception_class": type(exc).__name__,
            "exception_message": str(exc)[:500],
        },
    )


def try_with_model_fallback(
    role: ModelRole,
    fn: Callable[[Any], T],
    *,
    base_dir: Path | str | None = None,
    session_id: str | None = None,
    streaming: bool | None = None,
) -> T:
    """Run ``fn(primary_model)``; on overload/timeout retry once with fallback.

    Re-raises the original exception when the role has no ``fallback_model``
    configured (no-op), or when the exception is not classified as
    overload/timeout.
    """
    primary = build_chat_model(role, streaming=streaming)
    try:
        return fn(primary)
    except BaseException as exc:
        if not is_overload_or_timeout(exc):
            raise
        fallback = build_fallback_chat_model(role, streaming=streaming)
        if fallback is None:
            raise
        primary_cfg = get_role_model_config(role, streaming=streaming)
        _emit_fallback_audit(
            base_dir=base_dir,
            role=role,
            primary_model=primary_cfg.model,
            fallback_model=primary_cfg.fallback_model or "",
            exc=exc,
            session_id=session_id,
        )
        return fn(fallback)


async def atry_with_model_fallback(
    role: ModelRole,
    fn: Callable[[Any], Awaitable[T]],
    *,
    base_dir: Path | str | None = None,
    session_id: str | None = None,
    streaming: bool | None = None,
) -> T:
    """Async variant of :func:`try_with_model_fallback`."""
    primary = build_chat_model(role, streaming=streaming)
    try:
        return await fn(primary)
    except BaseException as exc:
        if not is_overload_or_timeout(exc):
            raise
        fallback = build_fallback_chat_model(role, streaming=streaming)
        if fallback is None:
            raise
        primary_cfg = get_role_model_config(role, streaming=streaming)
        _emit_fallback_audit(
            base_dir=base_dir,
            role=role,
            primary_model=primary_cfg.model,
            fallback_model=primary_cfg.fallback_model or "",
            exc=exc,
            session_id=session_id,
        )
        return await fn(fallback)


__all__ = [
    "atry_with_model_fallback",
    "is_overload_or_timeout",
    "try_with_model_fallback",
]
