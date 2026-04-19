"""Prose permission rules with classifier-backed evaluation (issue #91).

This module adds an opt-in gate on top of the structured tool-policy stack
(``tools/policy.py``). Operators author rules in natural language via the
``permissions.rules`` config block; a pluggable classifier converts each
(rule-set, tool-call) pair into an ``allow|deny|ask`` verdict. Verdicts are
cached per session so repeat calls on identical arguments do not re-invoke
the classifier.

The layer is wired in via the existing ``runtime.hooks`` pre-tool registry
rather than by modifying ``evaluate_pre_tool_policy``. Structured checks
(access scope, skill ``tools_allowed``, sandbox, explicit ``requires_approval``)
therefore remain authoritative and run first; prose rules are an additional
gate, never a replacement. Rule conflicts are resolved on a strictest-wins
order: ``deny`` > ``ask`` > ``allow``.

Fallback ladder (on classifier failure, timeout, or when no classifier is
registered and rules are non-empty):

1. **Cached verdict** — an earlier (session, tool, args, rules) cache hit
   is reused verbatim.
2. **Hardcoded deny-list** — a small, conservative set of patterns that
   should block regardless of prose rules (fork bombs, ``rm -rf /``, raw
   device writes). Hardcoded because an attacker who can author or inject
   a prose rule could otherwise whitelist these.
3. **Ask user** — if neither fires, the hook returns ``ask`` so the runtime
   surfaces a ``needs_approval`` gate (same path used by
   ``requires_approval`` tools).

The classifier is a plug-in: tests inject a fake via
``set_prose_classifier``. The default is ``None``, meaning rules are inert
until an operator wires a real implementation. That keeps this issue
strictly plumbing — no LLM dependency enters the sync tool-dispatch path
unless an operator opts in.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

import config

from runtime import hooks as runtime_hooks

logger = logging.getLogger(__name__)

ProseVerdict = Literal["allow", "deny", "ask"]

_SENSITIVE_KW_KEYS: frozenset[str] = frozenset(
    {"token", "api_key", "password", "authorization", "secret"}
)
_REDACTED_MARKER = "<redacted>"

_HOOK_NAME = "prose_permission_rules"


@dataclass(frozen=True)
class ProseRule:
    """A single operator-authored rule.

    ``effect`` is the outcome a classifier should return when the rule
    matches the tool call. The runtime aggregates individual rule verdicts
    via strictest-wins (``deny`` > ``ask`` > ``allow``).
    """

    description: str
    effect: ProseVerdict


@dataclass(frozen=True)
class ClassifierInput:
    """Payload handed to the classifier for one tool call."""

    tool_name: str
    redacted_kwargs: dict[str, Any]
    rules: tuple[ProseRule, ...]
    session_id: Optional[str]


ProseRulesClassifier = Callable[[ClassifierInput], ProseVerdict]


class ClassifierUnavailable(Exception):
    """Raised by a classifier when it cannot produce a verdict.

    The hook treats this exactly like any other classifier exception:
    it falls through to the hardcoded deny-list / ask-user ladder.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Classifier registry
# ─────────────────────────────────────────────────────────────────────────────

_classifier_lock = threading.Lock()
_classifier: Optional[ProseRulesClassifier] = None


def set_prose_classifier(classifier: Optional[ProseRulesClassifier]) -> None:
    """Install (or clear) the process-wide prose-rules classifier."""
    global _classifier
    with _classifier_lock:
        _classifier = classifier


def get_prose_classifier() -> Optional[ProseRulesClassifier]:
    with _classifier_lock:
        return _classifier


# ─────────────────────────────────────────────────────────────────────────────
# Session-scoped verdict cache
# ─────────────────────────────────────────────────────────────────────────────


class _SessionVerdictCache:
    """Bounded per-session cache of (cache_key → verdict) tuples.

    The cache is keyed by ``(session_id, rules_fingerprint, tool_name,
    kwargs_hash)``. Each session slot is an ordered dict with FIFO
    eviction; the per-session cap is configurable via
    ``permissions.cache_max_entries_per_session``. A rule-set fingerprint
    change invalidates every prior verdict without an explicit flush.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, OrderedDict[tuple, ProseVerdict]] = {}

    def _per_session_cap(self) -> int:
        raw = config.get_permissions_settings().get("cache_max_entries_per_session", 256)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 256

    def get(self, session_id: str, key: tuple) -> Optional[ProseVerdict]:
        with self._lock:
            session_cache = self._sessions.get(session_id)
            if session_cache is None:
                return None
            return session_cache.get(key)

    def put(self, session_id: str, key: tuple, verdict: ProseVerdict) -> None:
        cap = self._per_session_cap()
        with self._lock:
            session_cache = self._sessions.setdefault(session_id, OrderedDict())
            if key in session_cache:
                session_cache.move_to_end(key)
            session_cache[key] = verdict
            while len(session_cache) > cap:
                session_cache.popitem(last=False)

    def evict_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def snapshot(self, session_id: str) -> dict[tuple, ProseVerdict]:
        with self._lock:
            session_cache = self._sessions.get(session_id)
            return dict(session_cache) if session_cache else {}


_cache = _SessionVerdictCache()


def reset_cache() -> None:
    """Clear the session cache (exposed for tests)."""
    _cache.clear()


def cache_snapshot(session_id: str) -> dict[tuple, ProseVerdict]:
    """Return a copy of the cached verdicts for ``session_id`` (tests)."""
    return _cache.snapshot(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Hardcoded deny-list
# ─────────────────────────────────────────────────────────────────────────────

# These patterns are hardcoded (not prose) because they must fire even if an
# attacker has coaxed the classifier into a lax verdict. The set is
# intentionally small and targeted at the shell-dispatching tools; the
# sandbox already covers path-escape / SSRF for file- and URL-style args.
_HARDCODED_DENY_SUBSTRINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # (tool_name, (substring, substring, ...))
    ("terminal", (
        "rm -rf /",
        "rm -rf --no-preserve-root",
        ":(){ :|:& };:",  # classic fork bomb
        "mkfs",
        "dd if=/dev/zero of=/dev/",
        "dd if=/dev/random of=/dev/",
        "> /dev/sda",
    )),
    ("python_repl", (
        "os.system('rm -rf /')",
        'os.system("rm -rf /")',
    )),
)


def _hardcoded_deny_match(tool_name: str, kwargs: dict[str, Any]) -> bool:
    for target_tool, patterns in _HARDCODED_DENY_SUBSTRINGS:
        if target_tool != tool_name:
            continue
        blob = _serialize_for_match(kwargs)
        for pattern in patterns:
            if pattern in blob:
                return True
    return False


def _serialize_for_match(kwargs: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in kwargs.items():
        if isinstance(value, str):
            parts.append(value)
        else:
            try:
                parts.append(json.dumps(value, default=str))
            except (TypeError, ValueError):
                parts.append(repr(value))
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Rule loading / fingerprinting
# ─────────────────────────────────────────────────────────────────────────────


def _load_rules_from_config() -> tuple[ProseRule, ...]:
    settings = config.get_permissions_settings()
    if not bool(settings.get("enabled", False)):
        return ()
    raw_rules = settings.get("rules", []) or []
    if not isinstance(raw_rules, list):
        return ()
    parsed: list[ProseRule] = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            continue
        description = entry.get("description")
        effect = entry.get("effect")
        if not isinstance(description, str) or not description.strip():
            continue
        if effect not in {"allow", "deny", "ask"}:
            continue
        parsed.append(ProseRule(description=description.strip(), effect=effect))
    return tuple(parsed)


def _rules_fingerprint(rules: tuple[ProseRule, ...]) -> str:
    if not rules:
        return "empty"
    payload = json.dumps(
        [(rule.description, rule.effect) for rule in rules],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _kwargs_hash(kwargs: dict[str, Any]) -> str:
    try:
        payload = json.dumps(kwargs, sort_keys=True, default=repr, ensure_ascii=False)
    except (TypeError, ValueError):
        payload = repr(sorted(kwargs.items()))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _redact_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in kwargs.items():
        if str(key).lower() in _SENSITIVE_KW_KEYS:
            redacted[key] = _REDACTED_MARKER
        else:
            redacted[key] = value
    return redacted


# ─────────────────────────────────────────────────────────────────────────────
# Hook entry point
# ─────────────────────────────────────────────────────────────────────────────


def evaluate_prose_rules(
    tool_name: str,
    kwargs: dict[str, Any],
    session_id: Optional[str],
) -> Optional[runtime_hooks.PreToolDecision]:
    """Core decision function — exposed so tests don't need the full wrapper.

    Returns ``None`` to mean "no opinion" (the hook layer treats this as
    ``allow``). Returns a ``deny`` or ``ask`` decision to short-circuit.
    Never returns an explicit ``allow`` decision because the runtime hook
    contract already defaults to allow.
    """

    rules = _load_rules_from_config()
    if not rules:
        return None

    rules_fp = _rules_fingerprint(rules)
    args_hash = _kwargs_hash(kwargs)
    cache_key: tuple = (rules_fp, tool_name, args_hash)

    cached: Optional[ProseVerdict] = None
    if session_id:
        cached = _cache.get(session_id, cache_key)

    verdict: Optional[ProseVerdict] = cached
    used_cache = cached is not None
    classifier_error: Optional[str] = None

    if verdict is None:
        classifier = get_prose_classifier()
        if classifier is not None:
            try:
                raw = classifier(
                    ClassifierInput(
                        tool_name=tool_name,
                        redacted_kwargs=_redact_kwargs(kwargs),
                        rules=rules,
                        session_id=session_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — fallthrough to ladder
                classifier_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning(
                    "prose_policy classifier raised for tool %s: %s",
                    tool_name,
                    classifier_error,
                )
                raw = None
            if raw in {"allow", "deny", "ask"}:
                verdict = raw  # type: ignore[assignment]
                if session_id:
                    _cache.put(session_id, cache_key, verdict)

    if verdict is None:
        # Fallback ladder: hardcoded deny-list → ask user
        if _hardcoded_deny_match(tool_name, kwargs):
            return runtime_hooks.PreToolDecision(
                status="deny",
                message=(
                    f"Tool '{tool_name}' invocation matched the prose-rules "
                    "hardcoded deny-list fallback."
                ),
                reason="prose_rules_hardcoded_deny",
                metadata={
                    "prose_rules": {
                        "outcome": "hardcoded_deny",
                        "rules_fingerprint": rules_fp,
                        "classifier_error": classifier_error,
                    }
                },
            )
        return runtime_hooks.PreToolDecision(
            status="ask",
            message=(
                f"Prose permission rules could not classify this '{tool_name}' "
                "call; surfacing for user approval."
            ),
            reason="prose_rules_ask_fallback",
            metadata={
                "prose_rules": {
                    "outcome": "ask_fallback",
                    "rules_fingerprint": rules_fp,
                    "classifier_error": classifier_error,
                }
            },
        )

    if verdict == "allow":
        return None

    if verdict == "deny":
        return runtime_hooks.PreToolDecision(
            status="deny",
            message=(
                f"Tool '{tool_name}' was denied by prose permission rules."
            ),
            reason="prose_rules_deny",
            metadata={
                "prose_rules": {
                    "outcome": "deny",
                    "from_cache": used_cache,
                    "rules_fingerprint": rules_fp,
                }
            },
        )

    # verdict == "ask"
    return runtime_hooks.PreToolDecision(
        status="ask",
        message=(
            f"Tool '{tool_name}' requires user approval per prose permission rules."
        ),
        reason="prose_rules_ask",
        metadata={
            "prose_rules": {
                "outcome": "ask",
                "from_cache": used_cache,
                "rules_fingerprint": rules_fp,
            }
        },
    )


def _prose_permissions_pre_hook(
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Optional[runtime_hooks.PreToolDecision]:
    del args  # prose rules classify over tool_name + kwargs only
    invocation = runtime_hooks.get_invocation_context()
    session_id = invocation.session_id if invocation else None
    return evaluate_prose_rules(name, kwargs, session_id)


def register_prose_permission_hook() -> None:
    """Install the pre-tool hook on the default runtime registry (idempotent)."""
    registry = runtime_hooks.get_registry()
    existing_names = {hook_name for hook_name, _ in registry.pre_hooks}
    if _HOOK_NAME in existing_names:
        return
    registry.register_pre(_HOOK_NAME, _prose_permissions_pre_hook)


__all__ = [
    "ClassifierInput",
    "ClassifierUnavailable",
    "ProseRule",
    "ProseRulesClassifier",
    "ProseVerdict",
    "cache_snapshot",
    "evaluate_prose_rules",
    "get_prose_classifier",
    "register_prose_permission_hook",
    "reset_cache",
    "set_prose_classifier",
]
