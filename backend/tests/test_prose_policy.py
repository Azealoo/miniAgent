"""Tests for prose permission rules (issue #91).

Covers the three scenarios the acceptance criteria calls out — cache hit,
cache miss, and fallback (classifier failure → hardcoded deny-list / ask
user) — plus the ``allow``/``deny``/``ask`` verdict round-trips.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config  # noqa: E402
from runtime import hooks as runtime_hooks  # noqa: E402
from tools import get_runtime_tools  # noqa: E402
from tools.policy import tool_policy_context  # noqa: E402
from tools.policy_types import ToolPolicyExecutionContext  # noqa: E402
from tools.prose_policy import (  # noqa: E402
    ClassifierInput,
    cache_snapshot,
    evaluate_prose_rules,
    register_prose_permission_hook,
    reset_cache,
    set_prose_classifier,
)


@pytest.fixture(autouse=True)
def _isolate_prose_policy(monkeypatch):
    """Enable prose rules with a tunable rule-set + classifier per test."""

    # Ensure the hook is installed (tests may run before any other import
    # path triggered registration).
    registry_snapshot = runtime_hooks.get_registry().snapshot()
    register_prose_permission_hook()

    rules_state: dict[str, Any] = {
        "enabled": True,
        "rules": [
            {"description": "block anything that rewrites the repo history", "effect": "deny"},
        ],
        "cache_max_entries_per_session": 256,
    }

    def _fake_permissions() -> dict[str, Any]:
        return dict(rules_state)

    monkeypatch.setattr(config, "get_permissions_settings", _fake_permissions)

    reset_cache()
    set_prose_classifier(None)

    yield rules_state

    set_prose_classifier(None)
    reset_cache()
    runtime_hooks.get_registry().restore(registry_snapshot)


# ─────────────────────────────────────────────────────────────────────────────
# Core decision function — the "cache hit / miss / fallback" matrix
# ─────────────────────────────────────────────────────────────────────────────


def test_prose_rules_empty_rule_set_is_inert(_isolate_prose_policy):
    _isolate_prose_policy["rules"] = []
    calls: list[ClassifierInput] = []

    def _classifier(payload: ClassifierInput) -> str:
        calls.append(payload)
        return "deny"

    set_prose_classifier(_classifier)

    decision = evaluate_prose_rules("terminal", {"command": "echo hi"}, "session-inert")
    assert decision is None
    assert calls == []


def test_prose_rules_disabled_flag_is_inert(_isolate_prose_policy):
    _isolate_prose_policy["enabled"] = False
    calls: list[ClassifierInput] = []

    def _classifier(payload: ClassifierInput) -> str:
        calls.append(payload)
        return "deny"

    set_prose_classifier(_classifier)

    decision = evaluate_prose_rules("terminal", {"command": "echo hi"}, "session-off")
    assert decision is None
    assert calls == []


def test_prose_rules_allow_verdict_is_transparent(_isolate_prose_policy):
    set_prose_classifier(lambda _input: "allow")

    decision = evaluate_prose_rules("read_file", {"path": "notes.md"}, "session-allow")

    assert decision is None


def test_prose_rules_deny_verdict_blocks_with_metadata(_isolate_prose_policy):
    set_prose_classifier(lambda _input: "deny")

    decision = evaluate_prose_rules(
        "terminal", {"command": "git push --force"}, "session-deny"
    )

    assert decision is not None
    assert decision.status == "deny"
    assert decision.reason == "prose_rules_deny"
    assert decision.metadata["prose_rules"]["outcome"] == "deny"
    assert decision.metadata["prose_rules"]["from_cache"] is False


def test_prose_rules_ask_verdict_requests_approval(_isolate_prose_policy):
    set_prose_classifier(lambda _input: "ask")

    decision = evaluate_prose_rules(
        "terminal", {"command": "scp secret.txt remote:/"}, "session-ask"
    )

    assert decision is not None
    assert decision.status == "ask"
    assert decision.reason == "prose_rules_ask"
    assert decision.metadata["prose_rules"]["outcome"] == "ask"


def test_prose_rules_cache_miss_invokes_classifier_and_stores_verdict(
    _isolate_prose_policy,
):
    invocations: list[ClassifierInput] = []

    def _classifier(payload: ClassifierInput) -> str:
        invocations.append(payload)
        return "deny"

    set_prose_classifier(_classifier)

    decision = evaluate_prose_rules(
        "terminal", {"command": "git push --force origin main"}, "session-miss"
    )

    assert decision is not None and decision.status == "deny"
    assert len(invocations) == 1
    # The classifier saw the real kwargs (no sensitive keys in play here).
    assert invocations[0].tool_name == "terminal"
    assert invocations[0].redacted_kwargs == {
        "command": "git push --force origin main"
    }
    assert cache_snapshot("session-miss")  # populated


def test_prose_rules_cache_hit_skips_classifier_on_repeat(
    _isolate_prose_policy,
):
    invocations: list[ClassifierInput] = []

    def _classifier(payload: ClassifierInput) -> str:
        invocations.append(payload)
        return "deny"

    set_prose_classifier(_classifier)

    kwargs = {"command": "git push --force origin main"}
    first = evaluate_prose_rules("terminal", kwargs, "session-hit")
    second = evaluate_prose_rules("terminal", dict(kwargs), "session-hit")

    assert first is not None and first.status == "deny"
    assert second is not None and second.status == "deny"
    assert len(invocations) == 1, "classifier must not run on cache hit"
    assert second.metadata["prose_rules"]["from_cache"] is True


def test_prose_rules_cache_is_scoped_per_session(_isolate_prose_policy):
    invocations: list[ClassifierInput] = []

    def _classifier(payload: ClassifierInput) -> str:
        invocations.append(payload)
        return "deny"

    set_prose_classifier(_classifier)

    kwargs = {"command": "git push --force origin main"}
    evaluate_prose_rules("terminal", kwargs, "session-A")
    evaluate_prose_rules("terminal", dict(kwargs), "session-B")

    assert len(invocations) == 2, "different sessions must each hit the classifier"


def test_prose_rules_cache_invalidated_by_rules_change(_isolate_prose_policy):
    invocations: list[ClassifierInput] = []

    def _classifier(payload: ClassifierInput) -> str:
        invocations.append(payload)
        return "deny"

    set_prose_classifier(_classifier)

    kwargs = {"command": "git push --force origin main"}
    evaluate_prose_rules("terminal", kwargs, "session-X")
    _isolate_prose_policy["rules"] = [
        {"description": "block anything touching production", "effect": "deny"}
    ]
    evaluate_prose_rules("terminal", dict(kwargs), "session-X")

    assert len(invocations) == 2, "rule-set change must invalidate the cache"


def test_prose_rules_fallback_hits_hardcoded_deny_list(_isolate_prose_policy):
    """Classifier raises → ladder: cache miss → hardcoded deny-list → deny."""

    def _broken_classifier(_payload: ClassifierInput) -> str:
        raise RuntimeError("classifier is on fire")

    set_prose_classifier(_broken_classifier)

    decision = evaluate_prose_rules(
        "terminal", {"command": "sudo rm -rf / --no-preserve-root"}, "session-fb1"
    )

    assert decision is not None
    assert decision.status == "deny"
    assert decision.reason == "prose_rules_hardcoded_deny"
    assert decision.metadata["prose_rules"]["outcome"] == "hardcoded_deny"
    assert "RuntimeError" in (decision.metadata["prose_rules"]["classifier_error"] or "")


def test_prose_rules_fallback_asks_user_when_no_deny_match(_isolate_prose_policy):
    """Classifier raises → ladder: cache miss → deny-list miss → ask."""

    def _broken_classifier(_payload: ClassifierInput) -> str:
        raise RuntimeError("classifier is on fire")

    set_prose_classifier(_broken_classifier)

    decision = evaluate_prose_rules(
        "terminal", {"command": "echo hello"}, "session-fb2"
    )

    assert decision is not None
    assert decision.status == "ask"
    assert decision.reason == "prose_rules_ask_fallback"
    assert decision.metadata["prose_rules"]["outcome"] == "ask_fallback"


def test_prose_rules_fallback_when_no_classifier_registered(_isolate_prose_policy):
    """Rules present + no classifier → fallback ladder (ask by default)."""

    set_prose_classifier(None)

    decision = evaluate_prose_rules(
        "read_file", {"path": "notes.md"}, "session-fb3"
    )

    assert decision is not None
    assert decision.status == "ask"
    assert decision.reason == "prose_rules_ask_fallback"


def test_prose_rules_classifier_sees_redacted_sensitive_kwargs(
    _isolate_prose_policy,
):
    seen: list[dict[str, Any]] = []

    def _classifier(payload: ClassifierInput) -> str:
        seen.append(payload.redacted_kwargs)
        return "allow"

    set_prose_classifier(_classifier)

    evaluate_prose_rules(
        "http_json",
        {
            "url": "https://api.example.com/x",
            "api_key": "sk-live-shhhh",
            "Authorization": "Bearer abc",
        },
        "session-redact",
    )

    assert seen == [
        {
            "url": "https://api.example.com/x",
            "api_key": "<redacted>",
            "Authorization": "<redacted>",
        }
    ]


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: the pre-tool hook short-circuits PolicyWrappedTool
# ─────────────────────────────────────────────────────────────────────────────


def test_prose_hook_denies_tool_dispatch_end_to_end(
    _isolate_prose_policy, tmp_path
):
    """A ``deny`` verdict reaches PolicyWrappedTool via runtime hooks."""

    set_prose_classifier(lambda _input: "deny")

    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")
    note_path = tmp_path / "notes.md"
    note_path.write_text("should never be read\n", encoding="utf-8")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-e2e-deny",
            request_id="req-1",
            allowed_access_scope="execution",
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert summary.startswith("[BLOCKED]")
    assert artifact["outcome"] == "blocked"
    assert artifact["metadata"].get("hook_block_reason") == "prose_rules_deny"


def test_prose_hook_requests_approval_end_to_end(_isolate_prose_policy, tmp_path):
    """An ``ask`` verdict surfaces as a ``needs_approval`` result envelope."""

    set_prose_classifier(lambda _input: "ask")

    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")
    note_path = tmp_path / "notes.md"
    note_path.write_text("gated read\n", encoding="utf-8")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-e2e-ask",
            request_id="req-2",
            allowed_access_scope="execution",
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert summary.startswith("[NEEDS_APPROVAL]")
    assert artifact["outcome"] == "needs_approval"
    assert artifact["metadata"].get("hook_approval_reason") == "prose_rules_ask"
    assert artifact["metadata"].get("requires_approval") is True


def test_prose_hook_allow_lets_tool_run_end_to_end(_isolate_prose_policy, tmp_path):
    """An ``allow`` verdict leaves the structured policy path untouched."""

    set_prose_classifier(lambda _input: "allow")

    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")
    note_path = tmp_path / "notes.md"
    note_path.write_text("transparent allow\n", encoding="utf-8")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-e2e-allow",
            request_id="req-3",
            allowed_access_scope="execution",
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert "transparent allow" in summary
    assert artifact["outcome"] == "success"
    assert artifact["metadata"]["policy"]["status"] == "allow"
