"""Tests for the runtime hook registry (backend/runtime/hooks.py)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.tools import BaseTool

from runtime import hooks as runtime_hooks
from runtime.hooks import (
    HookRegistry,
    PostToolDecision,
    PreToolDecision,
    post_tool,
    pre_tool,
)
from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry


@pytest.fixture
def fresh_default_registry():
    """Snapshot + restore the process-level default registry."""

    snapshot = runtime_hooks.get_registry().snapshot()
    try:
        yield runtime_hooks.get_registry()
    finally:
        runtime_hooks.get_registry().restore(snapshot)


def _make_manifest(name: str) -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="test tool",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_runtime_hooks",
        read_only=True,
        destructive=False,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        tool_validates_input=False,
        activity_summary_hint="inspect",
        result_summary_hint="result",
    )


class _EchoTool(BaseTool):
    name: str = "echo_tool"
    description: str = "Echoes a message."
    response_format: str = "content_and_artifact"

    def _run(self, message: str = "ok", **kwargs):
        return f"echoed: {message}"

    async def _arun(self, message: str = "ok", **kwargs):
        return f"echoed: {message}"


def _wrap(tool: BaseTool) -> PolicyWrappedTool:
    return PolicyWrappedTool(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=tool,
        manifest=_make_manifest(tool.name),
    )


# ---------- HookRegistry unit semantics --------------------------------------


def test_allow_only_returns_allow():
    reg = HookRegistry()
    reg.register_pre("noop", lambda name, args, kwargs: PreToolDecision(status="allow"))
    assert reg.pre_tool("t", (), {}).status == "allow"


def test_deny_short_circuits_and_later_hooks_do_not_run():
    reg = HookRegistry()
    calls: list[str] = []
    reg.register_pre(
        "deny",
        lambda name, args, kwargs: PreToolDecision(
            status="deny", message="no", reason="policy"
        ),
    )

    def _later(name, args, kwargs):
        calls.append(name)
        return PreToolDecision(status="allow")

    reg.register_pre("later", _later)
    result = reg.pre_tool("t", (), {"x": 1})
    assert result.status == "deny"
    assert result.message == "no"
    assert result.reason == "policy"
    assert calls == []


def test_ask_short_circuits_like_deny():
    reg = HookRegistry()
    reg.register_pre(
        "ask",
        lambda n, a, k: PreToolDecision(status="ask", message="approve?"),
    )
    reg.register_pre(
        "later",
        lambda n, a, k: pytest.fail("later hook must not run after ask"),
    )
    result = reg.pre_tool("t", (), {})
    assert result.status == "ask"
    assert result.message == "approve?"


def test_modify_threads_new_args_through_chain():
    reg = HookRegistry()
    reg.register_pre(
        "scrub",
        lambda n, a, k: PreToolDecision(status="modify", kwargs={"message": "scrubbed"}),
    )

    seen: dict[str, object] = {}

    def _observer(name, args, kwargs):
        seen["kwargs"] = dict(kwargs)
        return PreToolDecision(status="allow")

    reg.register_pre("observer", _observer)
    result = reg.pre_tool("t", (), {"message": "secret"})
    assert result.status == "modify"
    assert result.kwargs == {"message": "scrubbed"}
    assert seen["kwargs"] == {"message": "scrubbed"}


def test_post_tool_modify_replaces_result():
    reg = HookRegistry()
    reg.register_post(
        "overlay",
        lambda n, a, k, r: PostToolDecision(status="modify", result="overlaid"),
    )
    result = reg.post_tool("t", (), {}, "original")
    assert result.status == "modify"
    assert result.result == "overlaid"


def test_post_tool_deny_short_circuits_chain():
    reg = HookRegistry()
    reg.register_post(
        "block",
        lambda n, a, k, r: PostToolDecision(
            status="deny", message="compliance", reason="gdpr"
        ),
    )
    reg.register_post(
        "later",
        lambda n, a, k, r: pytest.fail("deny must short-circuit"),
    )
    result = reg.post_tool("t", (), {}, "original")
    assert result.status == "deny"
    assert result.reason == "gdpr"


def test_hook_exception_is_skipped_not_raised():
    reg = HookRegistry()

    def _boom(name, args, kwargs):
        raise RuntimeError("bookkeeping hook crashed")

    reg.register_pre("boom", _boom)
    reg.register_pre(
        "survivor",
        lambda n, a, k: PreToolDecision(status="allow"),
    )
    # Must not raise — hook failures should never break the tool path.
    assert reg.pre_tool("t", (), {}).status == "allow"


def test_default_registry_has_migrated_tool_trace_hook():
    hook_names = {name for name, _ in runtime_hooks.get_registry().post_hooks}
    assert "tool_trace_jsonl" in hook_names


# ---------- Performance guard ------------------------------------------------


def test_registered_hook_chain_runs_under_100ms(fresh_default_registry):
    """Chain of representative hooks must execute in well under 100 ms.

    We install a small but realistic set of hooks (redactor, flag gate,
    audit bookkeeper, result overlay, observer) and time a single pre+post
    pass. The budget is deliberately generous — the point of the guard
    is to fail loudly if someone adds a hook that does blocking I/O.
    """

    fresh_default_registry.clear()

    def _redactor(name, args, kwargs):
        if "token" in kwargs:
            redacted = dict(kwargs)
            redacted["token"] = "<redacted>"
            return PreToolDecision(status="modify", kwargs=redacted)
        return PreToolDecision(status="allow")

    def _flag_gate(name, args, kwargs):
        if kwargs.get("feature") == "killed":
            return PreToolDecision(status="deny", message="feature flag kill")
        return PreToolDecision(status="allow")

    def _pre_audit(name, args, kwargs):
        return None  # side-effectful no-op

    def _post_audit(name, args, kwargs, result):
        return None  # side-effectful no-op

    def _overlay(name, args, kwargs, result):
        return PostToolDecision(status="allow")

    def _final_observer(name, args, kwargs, result):
        return PostToolDecision(status="allow", result=result)

    fresh_default_registry.register_pre("redactor", _redactor)
    fresh_default_registry.register_pre("flag_gate", _flag_gate)
    fresh_default_registry.register_pre("audit", _pre_audit)
    fresh_default_registry.register_post("post_audit", _post_audit)
    fresh_default_registry.register_post("overlay", _overlay)
    fresh_default_registry.register_post("observer", _final_observer)

    t0 = time.perf_counter()
    pre = pre_tool("example_tool", (), {"message": "hi", "token": "abc"})
    post = post_tool("example_tool", (), pre.kwargs or {"message": "hi"}, "raw_result")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert pre.status == "modify"
    assert pre.kwargs == {"message": "hi", "token": "<redacted>"}
    assert post.status == "allow"
    assert elapsed_ms < 100.0, f"hook chain took {elapsed_ms:.3f} ms"


# ---------- Integration through PolicyWrappedTool ----------------------------


@pytest.fixture
def exec_ctx():
    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-hooks",
            request_id="req-hooks",
            turn_id="turn-hooks",
            allowed_access_scope="execution",
        )
    ):
        yield


def test_pre_hook_deny_blocks_tool_execution(exec_ctx, fresh_default_registry):
    fresh_default_registry.register_pre(
        "deny_echo",
        lambda n, a, k: PreToolDecision(
            status="deny",
            message="tool disabled for this session",
            reason="feature_flag",
        ),
    )
    # Keep the trace hook active so we match production layering.
    from tools.policy_wrappers import _tool_trace_post_hook
    fresh_default_registry.register_post("tool_trace_jsonl", _tool_trace_post_hook)

    wrapper = _wrap(_EchoTool())
    summary, payload = wrapper._run(message="hello")
    assert "[BLOCKED]" in summary
    assert payload["outcome"] == "blocked"
    assert payload["metadata"]["hook_block_reason"] == "feature_flag"


def test_pre_hook_modify_rewrites_tool_kwargs(exec_ctx, fresh_default_registry):
    from tools.policy_wrappers import _tool_trace_post_hook

    def _rewrite(name, args, kwargs):
        if "message" in kwargs:
            new = dict(kwargs)
            new["message"] = "[rewritten]"
            return PreToolDecision(status="modify", kwargs=new)
        return PreToolDecision(status="allow")

    fresh_default_registry.register_pre("rewrite", _rewrite)
    fresh_default_registry.register_post("tool_trace_jsonl", _tool_trace_post_hook)

    wrapper = _wrap(_EchoTool())
    summary, _payload = wrapper._run(message="original")
    assert "echoed: [rewritten]" in summary


def test_post_hook_ask_keeps_envelope_but_marks_metadata(
    exec_ctx, fresh_default_registry
):
    """Post hooks treat ``ask`` as a modify-equivalent overlay path."""

    from tools.contracts import ToolResultEnvelope
    from tools.policy_wrappers import _tool_trace_post_hook

    def _mark(name, args, kwargs, result):
        if isinstance(result, ToolResultEnvelope):
            overlaid = result.model_copy(deep=True)
            metadata = dict(overlaid.metadata)
            metadata["requires_approval"] = True
            overlaid.metadata = metadata
            return PostToolDecision(status="modify", result=overlaid)
        return PostToolDecision(status="allow")

    fresh_default_registry.register_post("mark_approval", _mark)
    fresh_default_registry.register_post("tool_trace_jsonl", _tool_trace_post_hook)

    wrapper = _wrap(_EchoTool())
    _summary, payload = wrapper._run(message="ok")
    assert payload["metadata"]["requires_approval"] is True
