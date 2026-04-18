"""Speculative read-only tool execution.

When the LLM emits a fully-formed tool_use content block we know the target
tool and its arguments before the agent framework formally dispatches the
call. For read-only, concurrency-safe tools we can start execution
immediately and serve the result from cache when the real dispatch arrives
a short time later. For the single-tool case the win is the dispatch gap
(a few ms of LangChain orchestration); when the model emits multiple tool
calls in one turn and the agent serializes them, the wins compound because
all speculations run in parallel.

A ``SpeculationSession`` lives for the duration of one ``agent.astream``
run and tracks pending ``asyncio.Task``s keyed by ``(tool_name,
args_digest)``. ``PolicyWrappedTool._arun`` consumes a matching task on
dispatch; leftover speculations are cancelled and logged on session exit
so the wasted work is visible to operators.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator

logger = logging.getLogger(__name__)

_SPECULATION_CONTEXT: ContextVar["SpeculationSession | None"] = ContextVar(
    "bioapex_speculation_session",
    default=None,
)

_SPECULATION_TRACE_FILENAME = "speculation.jsonl"
_SPECULATION_ENABLED_ENV = "BIOAPEX_SPECULATIVE_TOOLS"
_TRACE_DIR_ENV = "BIOAPEX_TOOL_TRACE_DIR"
_DEFAULT_TRACE_DIR = Path(__file__).resolve().parents[1] / "storage" / "tool-traces"


def speculation_enabled() -> bool:
    """True unless the kill-switch env var is set to a falsey value."""
    raw = os.environ.get(_SPECULATION_ENABLED_ENV, "1").strip().lower()
    return raw not in {"0", "false", "off", "no", ""}


def canonical_args_digest(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Stable hash of a tool invocation's arguments.

    Used as the second half of the cache key. JSON serialization with
    ``sort_keys`` guarantees that keyword order never causes a miss; values
    that don't round-trip through JSON fall back to ``str``. The digest
    deliberately ignores object identity, so two calls with structurally
    identical args match even when the Python objects differ.
    """

    try:
        payload = json.dumps(
            {"a": list(args), "k": kwargs},
            sort_keys=True,
            default=str,
        )
    except Exception:
        payload = repr((args, kwargs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _SpeculationEntry:
    __slots__ = ("task", "started_at", "consumed")

    def __init__(self, task: "asyncio.Task[Any]", started_at: float) -> None:
        self.task = task
        self.started_at = started_at
        self.consumed = False


class SpeculationSession:
    """Per-turn collection of pending speculative tool invocations."""

    def __init__(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self._entries: dict[tuple[str, str], _SpeculationEntry] = {}

    # ------------------------------------------------------------------ #
    # Producer side                                                       #
    # ------------------------------------------------------------------ #

    def speculate(
        self,
        tool_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        runner: Callable[[], Awaitable[Any]],
    ) -> bool:
        """Schedule ``runner`` as a background task keyed by tool+args.

        ``runner`` is invoked via ``asyncio.create_task`` in the current
        running loop; it inherits the caller's contextvars so tool policy
        context still resolves inside the speculative coroutine. Returns
        ``False`` if a speculation for the same key is already pending, if
        there is no running loop, or if the runner could not be scheduled.
        """

        key = (tool_name, canonical_args_digest(args, kwargs))
        if key in self._entries:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        task = loop.create_task(runner())
        self._entries[key] = _SpeculationEntry(
            task=task,
            started_at=time.perf_counter(),
        )
        _write_trace(
            phase="started",
            tool_name=tool_name,
            args_digest=key[1],
            session_id=self.session_id,
            turn_id=self.turn_id,
        )
        return True

    # ------------------------------------------------------------------ #
    # Consumer side                                                       #
    # ------------------------------------------------------------------ #

    async def consume(
        self,
        tool_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[Any, float] | None:
        """Return ``(result, speculation_duration_ms)`` on match, else None.

        A match means there was a speculation with the same ``(tool_name,
        args_digest)`` that has not been consumed yet. If the speculation
        raised, the discard is logged and ``None`` is returned so the
        caller can fall back to real dispatch.
        """

        key = (tool_name, canonical_args_digest(args, kwargs))
        entry = self._entries.get(key)
        if entry is None or entry.consumed:
            return None
        entry.consumed = True
        try:
            result = await entry.task
        except asyncio.CancelledError:
            _write_trace(
                phase="discarded",
                tool_name=tool_name,
                args_digest=key[1],
                reason="speculation_cancelled",
                session_id=self.session_id,
                turn_id=self.turn_id,
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive
            _write_trace(
                phase="discarded",
                tool_name=tool_name,
                args_digest=key[1],
                reason="speculation_raised",
                session_id=self.session_id,
                turn_id=self.turn_id,
                error=str(exc),
            )
            return None
        duration_ms = (time.perf_counter() - entry.started_at) * 1000.0
        _write_trace(
            phase="accepted",
            tool_name=tool_name,
            args_digest=key[1],
            duration_ms=duration_ms,
            session_id=self.session_id,
            turn_id=self.turn_id,
        )
        return result, duration_ms

    async def discard_pending(self, reason: str) -> None:
        """Cancel and log every speculation that was never consumed.

        Called on session exit so stray tasks are never orphaned and every
        unused speculation appears in the trace with the exit reason
        (``stream_ended``, ``error``, …).
        """

        for (tool_name, args_digest), entry in list(self._entries.items()):
            if entry.consumed:
                continue
            entry.consumed = True
            entry.task.cancel()
            try:
                await entry.task
            except (asyncio.CancelledError, Exception):
                pass
            _write_trace(
                phase="discarded",
                tool_name=tool_name,
                args_digest=args_digest,
                reason=reason,
                session_id=self.session_id,
                turn_id=self.turn_id,
            )

    # ------------------------------------------------------------------ #
    # Test inspection                                                     #
    # ------------------------------------------------------------------ #

    def pending_count(self) -> int:
        return sum(1 for entry in self._entries.values() if not entry.consumed)

    def scheduled_count(self) -> int:
        return len(self._entries)


@contextmanager
def speculation_session(session: SpeculationSession) -> Iterator[SpeculationSession]:
    token: Token = _SPECULATION_CONTEXT.set(session)
    try:
        yield session
    finally:
        _SPECULATION_CONTEXT.reset(token)


def get_current_speculation() -> SpeculationSession | None:
    return _SPECULATION_CONTEXT.get()


# ---------------------------------------------------------------------- #
# Trace writer                                                            #
# ---------------------------------------------------------------------- #


def _resolve_trace_dir() -> Path:
    override = os.environ.get(_TRACE_DIR_ENV)
    if override:
        return Path(override)
    return _DEFAULT_TRACE_DIR


def _write_trace(
    *,
    phase: str,
    tool_name: str,
    args_digest: str,
    session_id: str | None = None,
    turn_id: str | None = None,
    duration_ms: float | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> None:
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id": session_id,
        "turn_id": turn_id,
        "tool_name": tool_name,
        "args_digest": args_digest,
        "phase": phase,
    }
    if duration_ms is not None:
        record["speculation_duration_ms"] = round(duration_ms, 3)
    if reason is not None:
        record["reason"] = reason
    if error is not None:
        record["error"] = error
    try:
        trace_dir = _resolve_trace_dir()
        trace_dir.mkdir(parents=True, exist_ok=True)
        path = trace_dir / _SPECULATION_TRACE_FILENAME
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - tracing never breaks the hot path
        logger.debug("Failed to write speculation trace", exc_info=True)


__all__ = [
    "SpeculationSession",
    "canonical_args_digest",
    "get_current_speculation",
    "speculation_enabled",
    "speculation_session",
]
