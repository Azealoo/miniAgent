"""End-to-end coverage for the reviewer approval flow.

Exercises three guarantees from the issue:

1. The runtime emits ``tool_awaiting_approval`` and pauses the turn with
   ``turn_status=awaiting_approval`` (no more tokens or tool calls).
2. ``POST /api/chat/approval`` records the decision to the on-disk approval
   store and appends a ``tool_approval_decision`` audit event (decision,
   actor, rationale, timestamp).
3. After an approve decision, the next ``/api/chat`` turn sees the tool as
   approved in the policy context (i.e., the gate does not re-trigger) and
   the store is consumed once the turn completes; a deny decision is surfaced
   as a ``denied_tool_runs`` entry on the policy context.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def isolated_approval_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm
    original_memory_indexer = agent_manager.memory_indexer

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.llm = MagicMock()
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("workspace", "memory", "skills", "knowledge", "storage"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm
        agent_manager.memory_indexer = original_memory_indexer


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/chat/approval",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


async def _collect_sse_payloads(response) -> list[dict]:
    chunks: list[str] = []
    try:
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
    finally:
        close_iterator = getattr(response.body_iterator, "aclose", None)
        if close_iterator is not None:
            await close_iterator()

    payloads: list[dict] = []
    for block in "".join(chunks).split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))
    return payloads


@pytest.mark.asyncio
async def test_awaiting_approval_pauses_turn_and_emits_turn_status(isolated_approval_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "tool_awaiting_approval",
            "tool": "terminal",
            "input": "rm -rf /",
            "run_id": "run-42",
            "reason": "requires_approval",
            "message": "Approve before running.",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "terminal",
                "summary": "[NEEDS_APPROVAL] Tool 'terminal' is gated.",
                "outcome": "needs_approval",
                "status": "error",
            },
        }
        # Any tokens emitted AFTER the gate are a regression: the runtime must
        # stop iterating the agent's stream once the gate fires.
        yield {"type": "done", "turn_status": "awaiting_approval"}
        yield {"type": "token", "content": "leaked after pause"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="Drop tables", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    gate = next(item for item in payloads if item["type"] == "tool_awaiting_approval")
    done = next(item for item in payloads if item["type"] == "done")

    assert gate["tool"] == "terminal"
    assert gate["run_id"] == "run-42"
    assert done["turn_status"] == "awaiting_approval"
    assert not any(
        item["type"] == "token" and "leaked" in item.get("content", "")
        for item in payloads
    )

    # Approval_gate block is persisted in session history so reviewers can find
    # the gate after refreshing.
    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    blocks = assistant_messages[0]["blocks"]
    gate_blocks = [block for block in blocks if block["type"] == "approval_gate"]
    assert len(gate_blocks) == 1
    assert gate_blocks[0]["tool"] == "terminal"
    assert gate_blocks[0]["run_id"] == "run-42"
    assert gate_blocks[0]["reason"] == "requires_approval"


@pytest.mark.asyncio
async def test_approval_endpoint_records_decision_to_store_and_audit(isolated_approval_state):
    from api.chat import ApprovalDecisionRequest, submit_approval_decision
    from audit.store import query_audit_events
    from graph import approval_store
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    response = await submit_approval_decision(
        ApprovalDecisionRequest(
            session_id=session_id,
            run_id="run-42",
            tool_name="terminal",
            decision="approve",
            actor="alice",
            rationale="Verified on a disposable VM.",
        ),
        _http_request(),
    )

    assert response.recorded is True
    assert response.decision == "approve"
    assert response.actor == "alice"
    assert response.recorded_at  # non-empty ISO timestamp

    records = approval_store.pending_records(agent_manager.base_dir, session_id)
    assert len(records) == 1
    assert records[0]["tool_name"] == "terminal"
    assert records[0]["run_id"] == "run-42"
    assert records[0]["decision"] == "approve"
    assert records[0]["actor"] == "alice"
    assert records[0]["rationale"] == "Verified on a disposable VM."
    assert records[0]["args_hash"] == ""

    events = query_audit_events(
        agent_manager.base_dir,
        event_type="tool_approval_decision",
        session_id=session_id,
    )
    assert events, "expected an audit event for the approval decision"
    event = events[0]
    assert event.outcome == "approve"
    assert event.actor == "alice"
    assert event.tool_name == "terminal"
    assert event.run_id == "run-42"
    assert event.details["decision"] == "approve"
    assert event.details["rationale"] == "Verified on a disposable VM."
    assert event.recorded_at is not None


@pytest.mark.asyncio
async def test_next_turn_consumes_approved_tool_runs_from_store(isolated_approval_state):
    from api.chat import ChatRequest, chat
    from graph import approval_store
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    args_hash = approval_store.compute_args_hash({"command": "ls"})
    approval_store.record_decision(
        agent_manager.base_dir,
        session_id=session_id,
        tool_name="terminal",
        run_id="run-42",
        decision="approve",
        actor="alice",
        rationale=None,
        args_hash=args_hash,
    )

    captured: dict[str, object] = {}

    async def fake_astream(_message, _history):
        from tools.policy import get_tool_policy_context

        captured["policy_context"] = get_tool_policy_context()
        yield {"type": "token", "content": "ran with approval"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="retry", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    policy_context = captured["policy_context"]
    assert policy_context is not None
    assert ("terminal", args_hash) in policy_context.approved_tool_runs
    assert policy_context.denied_tool_runs == frozenset()

    done = next(item for item in payloads if item["type"] == "done")
    assert done.get("turn_status", "ok") == "ok"

    # A successful turn consumes pending approvals so the next unrelated gated
    # call re-prompts the reviewer.
    remaining = approval_store.pending_records(agent_manager.base_dir, session_id)
    assert remaining == []


@pytest.mark.asyncio
async def test_denied_decision_surfaces_as_blocked_instead_of_reprompt(isolated_approval_state):
    from graph import approval_store
    from graph.agent import agent_manager
    from tools import get_runtime_tools
    from tools.policy import tool_policy_context
    from tools.policy_types import ToolPolicyExecutionContext

    session_id = agent_manager.session_manager.create_session()
    call_kwargs = {"path": "memory/note.md", "content": "hi"}
    args_hash = approval_store.compute_args_hash(call_kwargs)
    approval_store.record_decision(
        agent_manager.base_dir,
        session_id=session_id,
        tool_name="write_file",
        run_id="run-99",
        decision="deny",
        actor="bob",
        rationale="Not this run.",
        args_hash=args_hash,
    )

    denied = approval_store.denied_tool_runs(agent_manager.base_dir, session_id)
    assert denied == frozenset({("write_file", args_hash)})

    runtime_tools = get_runtime_tools(agent_manager.base_dir)
    write_file = next(tool for tool in runtime_tools if tool.name == "write_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id=session_id,
            request_id="req-1",
            allowed_access_scope="execution",
            denied_tool_runs=denied,
        )
    ):
        summary, artifact = write_file._run(**call_kwargs)

    assert artifact["outcome"] == "blocked"
    assert artifact["metadata"]["policy"]["block_reason"] == "reviewer_denied_approval"
    assert "denied" in summary.lower() or "reviewer" in summary.lower()


@pytest.mark.asyncio
async def test_approval_for_different_args_does_not_authorize_new_call(isolated_approval_state):
    """An approval bound to one args_hash must not authorize a call whose
    kwargs hash to a different digest — the reviewer only OK'd that specific
    invocation."""
    from graph import approval_store
    from graph.agent import agent_manager
    from tools import get_runtime_tools
    from tools.policy import tool_policy_context
    from tools.policy_types import ToolPolicyExecutionContext

    session_id = agent_manager.session_manager.create_session()
    approved_args_hash = approval_store.compute_args_hash({"command": "ls /tmp"})
    approval_store.record_decision(
        agent_manager.base_dir,
        session_id=session_id,
        tool_name="terminal",
        run_id="run-1",
        decision="approve",
        actor="alice",
        rationale=None,
        args_hash=approved_args_hash,
    )

    approved = approval_store.approved_tool_runs(agent_manager.base_dir, session_id)
    assert approved == frozenset({("terminal", approved_args_hash)})

    runtime_tools = get_runtime_tools(agent_manager.base_dir)
    terminal = next(tool for tool in runtime_tools if tool.name == "terminal")

    # Same tool, *different* args → must re-prompt.
    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id=session_id,
            request_id="req-1",
            allowed_access_scope="execution",
            approved_tool_runs=approved,
        )
    ):
        summary, artifact = terminal._run(command="rm -rf /")

    assert artifact["outcome"] == "needs_approval"
    assert artifact["metadata"]["policy"]["status"] == "needs_approval"
    assert summary.startswith("[NEEDS_APPROVAL]")


def test_expired_approvals_are_dropped_on_load(isolated_approval_state, monkeypatch):
    """A stored approval older than ``APPROVAL_TTL_SECONDS`` is silently
    filtered out on load so a stale decision cannot authorize a later call."""
    from datetime import datetime, timedelta, timezone

    from graph import approval_store
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    args_hash = approval_store.compute_args_hash({"command": "ls"})
    approval_store.record_decision(
        agent_manager.base_dir,
        session_id=session_id,
        tool_name="terminal",
        run_id="run-1",
        decision="approve",
        actor="alice",
        rationale=None,
        args_hash=args_hash,
    )

    assert approval_store.approved_tool_runs(
        agent_manager.base_dir, session_id
    ) == frozenset({("terminal", args_hash)})

    # Fast-forward the wall clock past the TTL by patching the module's
    # ``datetime.now`` lookup. ``_load`` computes ``now`` as
    # ``datetime.now(timezone.utc)`` so overriding the module attribute is
    # enough.
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime.now(timezone.utc) + timedelta(
                seconds=approval_store.APPROVAL_TTL_SECONDS + 10
            )
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr(approval_store, "datetime", _FrozenDatetime)
    try:
        # After TTL elapses, the stored record is filtered out on load.
        assert approval_store.approved_tool_runs(
            agent_manager.base_dir, session_id
        ) == frozenset()
        assert approval_store.pending_records(
            agent_manager.base_dir, session_id
        ) == []
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_destructive_tool_always_reprompts_even_when_approved(isolated_approval_state):
    """Approvals stored for a destructive manifest are ignored by the policy
    layer — the reviewer must confirm each destructive call in the moment."""
    from graph import approval_store
    from graph.agent import agent_manager
    from tools import get_runtime_tools
    from tools.policy import tool_policy_context
    from tools.policy_types import ToolPolicyExecutionContext

    session_id = agent_manager.session_manager.create_session()
    call_kwargs = {"path": "memory/note.md", "content": "hi"}
    args_hash = approval_store.compute_args_hash(call_kwargs)
    approval_store.record_decision(
        agent_manager.base_dir,
        session_id=session_id,
        tool_name="write_file",
        run_id="run-42",
        decision="approve",
        actor="alice",
        rationale=None,
        args_hash=args_hash,
    )

    approved = approval_store.approved_tool_runs(agent_manager.base_dir, session_id)
    assert ("write_file", args_hash) in approved

    runtime_tools = get_runtime_tools(agent_manager.base_dir)
    write_file = next(tool for tool in runtime_tools if tool.name == "write_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id=session_id,
            request_id="req-1",
            allowed_access_scope="execution",
            approved_tool_runs=approved,
        )
    ):
        summary, artifact = write_file._run(**call_kwargs)

    assert artifact["outcome"] == "needs_approval"
    assert artifact["metadata"]["policy"]["status"] == "needs_approval"
    assert summary.startswith("[NEEDS_APPROVAL]")
