"""Unit tests for the SubAgent abstraction.

Covers:
(a) successful launch → artifact file is produced on disk with the
    expected canonical payload shape.
(b) timeout / recursion-cap exit → raising a recursion-style error from
    the underlying agent stream produces status ``recursion_cap_exceeded``.
(c) token-budget exit → exceeding ``token_budget`` mid-stream produces
    status ``token_budget_exceeded`` and still persists the artifact.
(d) artifact fields validate → the persisted JSON indexes cleanly via the
    artifact registry as a ``subagent_run`` record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeAgent:
    """Replay a scripted sequence of ``astream_events`` entries."""

    def __init__(self, events: list[dict[str, Any]], *, raise_at_end: Exception | None = None) -> None:
        self._events = events
        self._raise_at_end = raise_at_end

    async def astream_events(
        self,
        payload,
        version: str = "v2",
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.captured_config = config
        self.captured_payload = payload
        for event in self._events:
            yield event
        if self._raise_at_end is not None:
            raise self._raise_at_end


def _token_event(text: str) -> dict[str, Any]:
    return {
        "event": "on_chat_model_stream",
        "data": {"chunk": _FakeChunk(text)},
    }


def _tool_start_event(name: str, input_value: str, run_id: str) -> dict[str, Any]:
    return {
        "event": "on_tool_start",
        "name": name,
        "run_id": run_id,
        "data": {"input": {"query": input_value}},
    }


def _tool_end_event(name: str, output: str, run_id: str) -> dict[str, Any]:
    return {
        "event": "on_tool_end",
        "name": name,
        "run_id": run_id,
        "data": {"output": output},
    }


def _make_contract(**overrides: Any):
    from runtime.subagent import SubAgentContract

    defaults = dict(
        name="plan_agent",
        system_prompt="You are BioAPEX's planning specialist.",
        tools_allowed=(type("DummyTool", (), {"name": "read_file"})(),),
        max_steps=50,
        token_budget=0,
    )
    defaults.update(overrides)
    return SubAgentContract(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# (a) launch + (d) artifact fields
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_launch_produces_canonical_subagent_artifact(tmp_path):
    from runtime.subagent import (
        SUBAGENT_ARTIFACT_FILENAME,
        SUBAGENT_ARTIFACT_TYPE,
        SUBAGENT_WORKFLOW_SLUG,
        run_subagent,
    )

    events = [
        _tool_start_event("read_file", "memory/MEMORY.md", "run-tool-1"),
        _tool_end_event("read_file", "MEMORY.md contents", "run-tool-1"),
        _token_event('{"goal":"ok",'),
        _token_event('"steps":[]}'),
    ]
    fake_agent = _FakeAgent(events)

    with patch("runtime.subagent.create_agent", return_value=fake_agent):
        artifact = await run_subagent(
            _make_contract(max_steps=50),
            llm=object(),
            user_prompt="Design a plan for BRCA1.",
            base_dir=tmp_path,
        )

    assert artifact.status == "ok"
    assert artifact.steps_used == 1
    assert artifact.tokens_used > 0
    assert artifact.run_id.startswith("run-")
    assert artifact.response_text.startswith('{"goal":"ok"')

    artifact_path = Path(artifact.absolute_path)
    assert artifact_path.is_file()
    assert artifact_path.name == SUBAGENT_ARTIFACT_FILENAME

    relative = Path(artifact.relative_path)
    assert relative.parts[0] == "artifacts"
    assert relative.parts[1] == SUBAGENT_WORKFLOW_SLUG
    assert relative.parts[3] == artifact.run_id

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["artifact_type"] == SUBAGENT_ARTIFACT_TYPE
    assert payload["run_id"] == artifact.run_id
    assert payload["source_workflow"] == SUBAGENT_WORKFLOW_SLUG
    assert payload["source_tool"] == "plan_agent"
    assert payload["status"] == "ok"
    assert payload["subagent"]["name"] == "plan_agent"
    assert payload["subagent"]["tools_allowed"] == ["read_file"]
    assert payload["inputs"]["user_prompt"] == "Design a plan for BRCA1."
    assert payload["outputs"]["tool_trace"][0]["tool"] == "read_file"
    assert payload["outputs"]["tool_trace"][0]["output"] == "MEMORY.md contents"
    assert fake_agent.captured_config == {"recursion_limit": 50}


# ──────────────────────────────────────────────────────────────────────────────
# (b) recursion / timeout exit
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recursion_cap_exit_records_status(tmp_path):
    from runtime.subagent import run_subagent

    class _FakeRecursionError(RuntimeError):
        pass

    events = [
        _token_event("starting work..."),
        _tool_start_event("read_file", "workspace/AGENTS.md", "run-loop-1"),
        _tool_end_event("read_file", "contents", "run-loop-1"),
    ]
    fake_agent = _FakeAgent(
        events,
        raise_at_end=_FakeRecursionError("Recursion limit reached in the graph."),
    )

    with patch("runtime.subagent.create_agent", return_value=fake_agent):
        artifact = await run_subagent(
            _make_contract(max_steps=25),
            llm=object(),
            user_prompt="Plan a long investigation.",
            base_dir=tmp_path,
        )

    assert artifact.status == "recursion_cap_exceeded"
    assert "Recursion" in (artifact.error or "")
    persisted = json.loads(Path(artifact.absolute_path).read_text(encoding="utf-8"))
    assert persisted["status"] == "recursion_cap_exceeded"
    assert persisted["outputs"]["tool_trace"][0]["tool"] == "read_file"


@pytest.mark.asyncio
async def test_generic_error_is_classified_and_persisted(tmp_path):
    from runtime.subagent import run_subagent

    fake_agent = _FakeAgent([], raise_at_end=ValueError("downstream model crashed"))

    with patch("runtime.subagent.create_agent", return_value=fake_agent):
        artifact = await run_subagent(
            _make_contract(),
            llm=object(),
            user_prompt="Attempt a run that fails.",
            base_dir=tmp_path,
        )

    assert artifact.status == "error"
    assert "downstream model crashed" in (artifact.error or "")
    assert Path(artifact.absolute_path).is_file()


# ──────────────────────────────────────────────────────────────────────────────
# (c) token-budget exit
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_token_budget_exit_stops_streaming_and_persists(tmp_path):
    from runtime.subagent import run_subagent

    # Emit far more tokens than the budget allows. We patch the token
    # counter to return a predictable value per call so the test does not
    # depend on the optional tiktoken backend.
    events = [
        _tool_start_event("read_file", "memory/MEMORY.md", "run-budget-1"),
        _tool_end_event("read_file", "contents", "run-budget-1"),
        _token_event("chunk-one "),
        _token_event("chunk-two "),
        _token_event("chunk-three "),
        _token_event("chunk-four "),
        _token_event("chunk-five "),
    ]
    fake_agent = _FakeAgent(events)

    with patch("runtime.subagent.create_agent", return_value=fake_agent), patch(
        "runtime.subagent._count_tokens",
        side_effect=lambda value: 0 if value is None else 1,
    ):
        artifact = await run_subagent(
            _make_contract(
                name="verification_agent",
                system_prompt="Be skeptical but calibrated.",
                token_budget=2,
            ),
            llm=object(),
            user_prompt="Short prompt.",
            base_dir=tmp_path,
        )

    assert artifact.status == "token_budget_exceeded"
    # Budget-path exit must not masquerade as an error — the exception used
    # internally to unwind the event loop is classified separately from the
    # generic ``except Exception`` boundary.
    assert artifact.error is None
    # Partial transcript is preserved: the tool call that executed before
    # the budget tripped must still appear in the persisted trace.
    assert artifact.tool_trace
    assert artifact.tool_trace[0]["tool"] == "read_file"
    # With 2 tokens consumed by system+user prompt and a budget of 2,
    # the very first streamed chunk should trip the limit.
    assert artifact.tokens_used >= 2
    assert len(artifact.response_text.split()) <= 5
    persisted = json.loads(Path(artifact.absolute_path).read_text(encoding="utf-8"))
    assert persisted["status"] == "token_budget_exceeded"
    assert persisted["tokens_used"] == artifact.tokens_used
    assert persisted["error"] is None
    assert persisted["outputs"]["tool_trace"][0]["tool"] == "read_file"


# ──────────────────────────────────────────────────────────────────────────────
# (d) artifact registry validation
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subagent_artifact_indexes_as_subagent_run_record(tmp_path):
    from artifacts.registry import ArtifactRegistry
    from runtime.subagent import run_subagent

    events = [_token_event('{"goal":"ok","steps":[]}')]
    fake_agent = _FakeAgent(events)

    with patch("runtime.subagent.create_agent", return_value=fake_agent):
        artifact = await run_subagent(
            _make_contract(),
            llm=object(),
            user_prompt="Plan this work.",
            base_dir=tmp_path,
        )

    snapshot = ArtifactRegistry(tmp_path).rebuild()
    matching = [
        record
        for record in snapshot.records
        if record.artifact_type == "subagent_run" and record.run_id == artifact.run_id
    ]
    assert len(matching) == 1
    record = matching[0]
    assert record.status == "valid", record.error
    assert record.workflow == "subagent"
    assert record.source_workflow == "subagent"
    assert record.source_tool == "plan_agent"
    assert record.path.endswith("/subagent_run.json")


# ──────────────────────────────────────────────────────────────────────────────
# Contract guards
# ──────────────────────────────────────────────────────────────────────────────

def test_contract_rejects_empty_fields():
    from runtime.subagent import SubAgentContract

    with pytest.raises(ValueError):
        SubAgentContract(
            name="",
            system_prompt="x",
            tools_allowed=(),
            max_steps=1,
            token_budget=0,
        )
    with pytest.raises(ValueError):
        SubAgentContract(
            name="x",
            system_prompt="",
            tools_allowed=(),
            max_steps=1,
            token_budget=0,
        )
    with pytest.raises(ValueError):
        SubAgentContract(
            name="x",
            system_prompt="y",
            tools_allowed=(),
            max_steps=0,
            token_budget=0,
        )
    with pytest.raises(ValueError):
        SubAgentContract(
            name="x",
            system_prompt="y",
            tools_allowed=(),
            max_steps=1,
            token_budget=-1,
        )
