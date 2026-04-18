"""Pre/post tool hook registry for runtime bookkeeping.

This module centralizes the declarative hook plumbing that tool execution
layers (``backend/tools/policy_wrappers.py`` and
``backend/runtime/query_engine.py``) previously inlined. It provides two
entry points — :func:`pre_tool` and :func:`post_tool` — that tool wrappers
invoke at the ``tool_start`` and ``tool_end`` boundaries.

Lifecycle
---------

For every wrapped tool call:

1. The runtime policy layer (``tools.policy.evaluate_pre_tool_policy`` and
   ``evaluate_sandbox_arguments``) runs first. Those decisions short-circuit
   before any hook fires — the hook layer is a *second* gate, not a
   replacement for the sandbox or access-scope checks.
2. The wrapper calls :func:`pre_tool(name, args, kwargs)` once per tool
   invocation. Each registered hook is run in registration order. Its
   return value is a :class:`PreToolDecision` with one of four statuses:

   * ``allow`` — continue to the next hook (or, after the last hook, to
     tool dispatch) with the current args/kwargs.
   * ``deny`` — short-circuit the tool run. The wrapper converts this to
     a ``blocked`` result using ``decision.message``. Later hooks do not
     run.
   * ``ask`` — short-circuit with a ``needs_approval`` result. The SSE
     boundary in ``runtime/query_engine.py`` surfaces this to the client
     as a ``tool_awaiting_approval`` event. Later hooks do not run.
   * ``modify`` — replace the args/kwargs payload seen by subsequent
     hooks and by the tool itself. Use this for redaction, feature-flag
     kills that rewrite the payload, and similar transforms.

3. The tool body dispatches with whatever args/kwargs the final pre hook
   produced (or the original input if every hook returned ``allow``).

4. After normalization and sandbox output-byte capping, the wrapper calls
   :func:`post_tool(name, args, kwargs, envelope)`. The same statuses are
   reused with post-dispatch semantics:

   * ``allow`` — continue. The envelope is unchanged.
   * ``deny`` — replace the envelope with a ``blocked`` result. Use this
     for compliance checks that need to see the tool output before
     permitting it to propagate.
   * ``modify`` — replace the envelope entirely (e.g. to scrub
     sensitive fields from ``structured_payload`` or add audit metadata).
   * ``ask`` — treated like ``modify`` for post hooks; the envelope
     stays but a ``needs_approval`` marker can be overlaid by the hook's
     own metadata. Prefer returning ``modify`` with an overlaid envelope
     for clarity.

Hook failures (raised exceptions) are logged and skipped — the tool path
must not die because a bookkeeping hook raised. Hooks are expected to be
short (sub-millisecond per call); a unit test asserts that the full
chain runs in under 100 ms.

Registration
------------

Modules install hooks at import time via :func:`register_pre` and
:func:`register_post`. Tests that want to isolate the registry can use
:func:`snapshot` / :func:`restore`, or construct their own
:class:`HookRegistry` and pass it explicitly.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator, Literal, Optional

logger = logging.getLogger(__name__)

HookStatus = Literal["allow", "deny", "ask", "modify"]


@dataclass(frozen=True)
class HookInvocationContext:
    """Per-call bookkeeping metadata that hooks may consult.

    The tool wrapper sets this via :func:`hook_invocation_context` before
    calling :func:`pre_tool` / :func:`post_tool`; hooks read it via
    :func:`get_invocation_context`. Hooks that do not need timing or
    session context can ignore this entirely.
    """

    tool_name: str
    started_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    request_id: Optional[str] = None
    extras: dict[str, Any] = field(default_factory=dict)


_HOOK_CONTEXT: ContextVar[Optional[HookInvocationContext]] = ContextVar(
    "bioapex_hook_invocation_context",
    default=None,
)


@contextmanager
def hook_invocation_context(context: HookInvocationContext) -> Iterator[HookInvocationContext]:
    token: Token = _HOOK_CONTEXT.set(context)
    try:
        yield context
    finally:
        _HOOK_CONTEXT.reset(token)


def get_invocation_context() -> Optional[HookInvocationContext]:
    return _HOOK_CONTEXT.get()


@dataclass(frozen=True)
class PreToolDecision:
    """Outcome of a single pre-tool hook (or the aggregated chain)."""

    status: HookStatus = "allow"
    message: str = ""
    reason: str = ""
    args: Optional[tuple[Any, ...]] = None
    kwargs: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PostToolDecision:
    """Outcome of a single post-tool hook (or the aggregated chain)."""

    status: HookStatus = "allow"
    message: str = ""
    reason: str = ""
    result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


PreToolHook = Callable[
    [str, tuple[Any, ...], dict[str, Any]],
    Optional[PreToolDecision],
]
PostToolHook = Callable[
    [str, tuple[Any, ...], dict[str, Any], Any],
    Optional[PostToolDecision],
]


class HookRegistry:
    """Ordered collection of pre/post hooks with short-circuit evaluation."""

    def __init__(self) -> None:
        self._pre: list[tuple[str, PreToolHook]] = []
        self._post: list[tuple[str, PostToolHook]] = []

    def register_pre(self, name: str, hook: PreToolHook) -> None:
        self._pre.append((name, hook))

    def register_post(self, name: str, hook: PostToolHook) -> None:
        self._post.append((name, hook))

    def unregister(self, name: str) -> None:
        self._pre = [(n, h) for n, h in self._pre if n != name]
        self._post = [(n, h) for n, h in self._post if n != name]

    def clear(self) -> None:
        self._pre.clear()
        self._post.clear()

    def snapshot(self) -> tuple[list, list]:
        return list(self._pre), list(self._post)

    def restore(self, snapshot: tuple[list, list]) -> None:
        pre, post = snapshot
        self._pre = list(pre)
        self._post = list(post)

    @property
    def pre_hooks(self) -> tuple[tuple[str, PreToolHook], ...]:
        return tuple(self._pre)

    @property
    def post_hooks(self) -> tuple[tuple[str, PostToolHook], ...]:
        return tuple(self._post)

    def pre_tool(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> PreToolDecision:
        """Run pre-tool hooks. Returns the aggregated decision.

        ``deny`` and ``ask`` short-circuit the chain. ``modify`` updates the
        payload seen by subsequent hooks. ``allow`` is the neutral case.
        """

        current_args = args
        current_kwargs = kwargs
        modified_by: list[str] = []
        for hook_name, hook in self._pre:
            try:
                decision = hook(name, current_args, current_kwargs)
            except Exception:  # noqa: BLE001 — hooks must never break tools
                logger.exception(
                    "pre_tool hook %r raised for tool %r; skipping hook",
                    hook_name,
                    name,
                )
                continue
            if decision is None:
                continue
            if decision.status == "deny" or decision.status == "ask":
                return decision
            if decision.status == "modify":
                if decision.args is not None:
                    current_args = decision.args
                if decision.kwargs is not None:
                    current_kwargs = decision.kwargs
                modified_by.append(hook_name)
                continue
            # ``allow`` (or anything else): keep going.

        if modified_by:
            return PreToolDecision(
                status="modify",
                args=current_args,
                kwargs=current_kwargs,
                metadata={"modified_by": tuple(modified_by)},
            )
        return PreToolDecision(status="allow")

    def post_tool(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        result: Any,
    ) -> PostToolDecision:
        """Run post-tool hooks. Returns the aggregated decision.

        ``deny`` short-circuits with a replacement result. ``modify`` chains
        the replacement result through subsequent hooks. ``allow`` is the
        neutral case; ``ask`` is accepted but behaves like ``modify`` here.
        """

        current_result = result
        modified_by: list[str] = []
        for hook_name, hook in self._post:
            try:
                decision = hook(name, args, kwargs, current_result)
            except Exception:  # noqa: BLE001 — hooks must never break tools
                logger.exception(
                    "post_tool hook %r raised for tool %r; skipping hook",
                    hook_name,
                    name,
                )
                continue
            if decision is None:
                continue
            if decision.status == "deny":
                return decision
            if decision.status in {"modify", "ask"}:
                if decision.result is not None:
                    current_result = decision.result
                modified_by.append(hook_name)
                continue

        if modified_by:
            return PostToolDecision(
                status="modify",
                result=current_result,
                metadata={"modified_by": tuple(modified_by)},
            )
        return PostToolDecision(status="allow", result=current_result)


_default_registry = HookRegistry()


def get_registry() -> HookRegistry:
    """Return the module-level default registry."""

    return _default_registry


def register_pre(name: str, hook: PreToolHook) -> None:
    _default_registry.register_pre(name, hook)


def register_post(name: str, hook: PostToolHook) -> None:
    _default_registry.register_post(name, hook)


def unregister(name: str) -> None:
    _default_registry.unregister(name)


def pre_tool(
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> PreToolDecision:
    """Run pre-tool hooks on the default registry."""

    return _default_registry.pre_tool(name, args, kwargs)


def post_tool(
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
) -> PostToolDecision:
    """Run post-tool hooks on the default registry."""

    return _default_registry.post_tool(name, args, kwargs, result)


__all__ = [
    "HookInvocationContext",
    "HookRegistry",
    "HookStatus",
    "PostToolDecision",
    "PostToolHook",
    "PreToolDecision",
    "PreToolHook",
    "get_invocation_context",
    "get_registry",
    "hook_invocation_context",
    "post_tool",
    "pre_tool",
    "register_post",
    "register_pre",
    "unregister",
]
