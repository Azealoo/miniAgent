import contextlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def isolated_chat_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.llm = MagicMock()

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm


async def _collect_sse_payloads(response) -> list[dict]:
    chunks: list[str] = []
    try:
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk.decode("utf-8"))
            else:
                chunks.append(chunk)
    finally:
        close_iterator = getattr(response.body_iterator, "aclose", None)
        if close_iterator is not None:
            await close_iterator()

    payloads: list[dict] = []
    for event in "".join(chunks).split("\n\n"):
        for line in event.split("\n"):
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))
    return payloads


def _request(
    path: str,
    *,
    method: str = "POST",
    host: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
            "client": (host, 12345),
        }
    )


def test_chat_request_rejects_removed_extra_fields():
    from api.chat import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "message": "Read memory",
                "session_id": "session-1",
                "stream": True,
            }
        )

    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "message": "Read memory",
                "session_id": "session-1",
                "attached_identifiers": ["workspace/uploads/example.txt"],
            }
        )


@pytest.mark.asyncio
async def test_chat_stream_includes_structured_tool_result_and_persists_it(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "tool_start",
            "tool": "read_file",
            "input": "memory/MEMORY.md",
            "run_id": "tool-run-1",
        }
        yield {
            "type": "tool_end",
            "tool": "read_file",
            "output": "# Memory",
            "run_id": "tool-run-1",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "read_file",
                "summary": "# Memory",
                "structured_payload": {"path": "memory/MEMORY.md", "content": "# Memory"},
                "artifact_refs": [{"path": "/tmp/memory/MEMORY.md", "label": "read_file_target"}],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {"requested_path": "memory/MEMORY.md"},
                "source_payload": None,
            },
        }
        yield {"type": "token", "content": "Done"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="Read memory", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    tool_start = next(
        item
        for item in payloads
        if item["type"] == "tool_start" and item["tool"] == "read_file"
    )
    tool_end = next(
        item
        for item in payloads
        if item["type"] == "tool_end" and item["tool"] == "read_file"
    )

    assert tool_start["run_id"] == "tool-run-1"
    assert tool_end["run_id"] == "tool-run-1"
    assert tool_end["result"]["tool_name"] == "read_file"
    assert tool_end["result"]["structured_payload"]["path"] == "memory/MEMORY.md"

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    tool_calls = assistant_messages[0]["tool_calls"]
    assert tool_calls[0]["run_id"] == "tool-run-1"
    assert tool_calls[0]["result"]["tool_name"] == "read_file"
    blocks = assistant_messages[0]["blocks"]
    assert blocks[0]["type"] == "tool_use"
    assert blocks[1]["type"] == "tool_result"
    assert blocks[2] == {"type": "text", "text": "Done"}


@pytest.mark.asyncio
async def test_chat_stream_emits_helper_agent_events_and_persists_typed_blocks(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "tool_end",
            "tool": "plan_agent",
            "output": "Planner produced 2 steps.",
            "run_id": "plan-run-1",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "plan_agent",
                "summary": "Planner produced 2 steps.",
                "structured_payload": {
                    "agent_type": "plan",
                    "plan": {
                        "goal": "Answer carefully",
                        "steps": [
                            {"step_id": "step-1", "intent": "Inspect memory"},
                            {"step_id": "step-2", "intent": "Draft answer"},
                        ],
                    },
                    "tool_trace": [{"tool": "read_file", "summary": "memory"}],
                },
                "artifact_refs": [],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {},
                "source_payload": None,
            },
        }
        yield {
            "type": "tool_end",
            "tool": "verification_agent",
            "output": "Verifier verdict: repair_required. Add one citation.",
            "run_id": "verify-run-1",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "verification_agent",
                "summary": "Verifier verdict: repair_required. Add one citation.",
                "structured_payload": {
                    "agent_type": "verification",
                    "verification": {
                        "verdict": "repair_required",
                        "summary": "Add one citation.",
                        "checks": [
                            {"name": "support", "status": "fail", "note": "Need evidence."}
                        ],
                        "issues": ["Missing citation."],
                        "repair_instructions": ["Cite the evidence review artifact."],
                    },
                    "tool_trace": [{"tool": "evidence_review", "summary": "reviewed"}],
                },
                "artifact_refs": [],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {},
                "source_payload": None,
            },
        }
        yield {"type": "token", "content": "Final answer"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="Plan then verify", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    plan_event = next(item for item in payloads if item["type"] == "plan_created")
    verification_event = next(
        item for item in payloads if item["type"] == "verification_result"
    )

    assert plan_event["summary"] == "Planner produced 2 steps."
    assert plan_event["plan"]["goal"] == "Answer carefully"
    assert plan_event["tool_trace"][0]["tool"] == "read_file"

    assert verification_event["verdict"] == "repair_required"
    assert verification_event["verification"]["repair_instructions"] == [
        "Cite the evidence review artifact."
    ]
    assert verification_event["tool_trace"][0]["tool"] == "evidence_review"

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    blocks = assistant_messages[0]["blocks"]
    assert any(block["type"] == "plan" for block in blocks)
    assert any(block["type"] == "verification" for block in blocks)

    plan_block = next(block for block in blocks if block["type"] == "plan")
    verification_block = next(block for block in blocks if block["type"] == "verification")

    assert plan_block["event"] == "created"
    assert plan_block["plan"]["goal"] == "Answer carefully"
    assert verification_block["verdict"] == "repair_required"
    assert verification_block["verification"]["issues"] == ["Missing citation."]
    assert blocks[-1] == {"type": "text", "text": "Final answer"}


@pytest.mark.asyncio
async def test_chat_stream_runs_bounded_repair_pass_as_second_segment(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    call_count = 0

    async def fake_astream(_message, _history):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield {
                "type": "tool_end",
                "tool": "plan_agent",
                "output": "Planner produced 1 step.",
                "run_id": "plan-run-1",
                "result": {
                    "contract_version": "tool_result.v1",
                    "tool_name": "plan_agent",
                    "summary": "Planner produced 1 step.",
                    "structured_payload": {
                        "agent_type": "plan",
                        "plan": {
                            "goal": "Answer carefully",
                            "steps": [
                                {"step_id": "step-1", "intent": "Check evidence"},
                            ],
                        },
                        "tool_trace": [{"tool": "read_file", "summary": "notes"}],
                    },
                    "artifact_refs": [],
                    "warnings": [],
                    "status": "success",
                    "outcome": "success",
                    "error": None,
                    "metadata": {},
                    "source_payload": None,
                },
            }
            yield {"type": "token", "content": "Draft answer without citation."}
            yield {
                "type": "tool_end",
                "tool": "verification_agent",
                "output": "Verifier verdict: repair_required. Add one citation.",
                "run_id": "verify-run-1",
                "result": {
                    "contract_version": "tool_result.v1",
                    "tool_name": "verification_agent",
                    "summary": "Verifier verdict: repair_required. Add one citation.",
                    "structured_payload": {
                        "agent_type": "verification",
                        "verification": {
                            "verdict": "repair_required",
                            "summary": "Add one citation.",
                            "checks": [
                                {"name": "support", "status": "fail", "note": "Need evidence."}
                            ],
                            "issues": ["Missing citation."],
                            "repair_instructions": ["Cite the evidence review artifact."],
                        },
                        "tool_trace": [{"tool": "evidence_review", "summary": "reviewed"}],
                    },
                    "artifact_refs": [],
                    "warnings": [],
                    "status": "success",
                    "outcome": "success",
                    "error": None,
                    "metadata": {},
                    "source_payload": None,
                },
            }
            yield {"type": "done"}
            return

        assert call_count == 2
        assert _history[-1]["role"] == "system"
        assert "Draft answer without citation." in _history[-1]["content"]
        assert "Missing citation." in _history[-1]["content"]
        yield {"type": "token", "content": "Repaired answer with citation."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="Plan then repair", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    assert call_count == 2
    assert [item["type"] for item in payloads].count("new_response") == 1

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert len(assistant_messages) == 2

    first_blocks = assistant_messages[0]["blocks"]
    second_blocks = assistant_messages[1]["blocks"]

    assert any(block["type"] == "plan" for block in first_blocks)
    assert any(block["type"] == "verification" for block in first_blocks)
    assert {"type": "text", "text": "Draft answer without citation."} in first_blocks
    assert second_blocks == [{"type": "text", "text": "Repaired answer with citation."}]
    assert assistant_messages[0]["content"] == "Draft answer without citation."
    assert assistant_messages[1]["content"] == "Repaired answer with citation."


@pytest.mark.asyncio
async def test_bounded_async_stream_force_cancels_aclose_when_inner_swallows_cancel(
    monkeypatch,
):
    """Issue #227: if the inner agent's aclose() blocks (e.g. a SLURM-wait
    tool swallowing CancelledError), the bounded stream's finally: block must
    not hang indefinitely. It should give up after ``_ACLOSE_TIMEOUT_S``,
    emit a warning, and force-cancel the pending aclose task so the turn can
    return.
    """
    import asyncio
    import logging
    import time

    from runtime import query_engine
    from runtime.query_engine import _bounded_async_stream

    class BlockingAgen:
        """Stand-in for the executor's async generator.

        ``aclose`` blocks until it's explicitly cancelled — modeling a tool
        (e.g. SLURM wait) whose cleanup will hang forever unless the
        bounded-stream wrapper escalates with its own ``task.cancel()``.
        """

        def __init__(self) -> None:
            self.cancel_count = 0
            self._yielded = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._yielded:
                self._yielded = True
                return {"type": "token", "content": "start"}
            await asyncio.sleep(60)
            raise StopAsyncIteration

        async def aclose(self) -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.cancel_count += 1
                # Honor the escalated cancel so the task actually completes
                # — this is what distinguishes a forced teardown from the
                # hang we're fixing.
                raise

    # Keep the test fast — we don't need the production 5s wait.
    monkeypatch.setattr(query_engine, "_ACLOSE_TIMEOUT_S", 0.2)

    inner = BlockingAgen()
    # Wallclock deadline far in the future so teardown is triggered by
    # ``aclose()`` (the caller exiting the ``async for``), not by the
    # wallclock branch.
    bounded = _bounded_async_stream(inner, time.monotonic() + 60.0)

    observed: list[dict] = []
    async for event in bounded:
        observed.append(event)
        break
    assert observed == [{"type": "token", "content": "start"}]

    start = time.monotonic()
    with caplog_collect_warnings("runtime.query_engine") as records:
        await bounded.aclose()
    elapsed = time.monotonic() - start

    # Teardown completes within a bounded window (first wait_for plus the
    # force-cancel wait_for, each capped by the monkeypatched timeout).
    assert elapsed < 2.0, f"aclose teardown took {elapsed:.2f}s"

    # The inner generator's aclose received at least one cancellation —
    # cancel was escalated rather than silently swallowed into a hang.
    assert inner.cancel_count >= 1

    # The warning log path fired, pointing operators at the stuck tool.
    assert any(
        "aclose exceeded" in record.getMessage() and record.levelno == logging.WARNING
        for record in records
    ), [r.getMessage() for r in records]


@contextlib.contextmanager
def caplog_collect_warnings(logger_name: str):
    """Minimal stand-in for pytest's ``caplog`` fixture scoped to one logger.

    Used by the bounded-stream teardown test so we can assert the warning
    emitted when ``aclose()`` exceeds its budget without pulling in the
    broader caplog fixture machinery.
    """
    import logging

    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler(level=logging.WARNING)
    target = logging.getLogger(logger_name)
    previous_level = target.level
    target.addHandler(handler)
    target.setLevel(logging.WARNING)
    try:
        yield records
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)


@pytest.mark.asyncio
async def test_agent_astream_injects_compact_source_aware_retrieved_memory(isolated_chat_state):
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    captured_messages = {}

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            captured_messages["messages"] = payload["messages"]
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Loaded."})()},
            }

    fake_indexer = MagicMock()
    fake_indexer.retrieve.return_value = [
        {
            "text": "BRCA1 follow-up notes say to inspect the latest evidence artifact first. "
            + ("extra context " * 80),
            "score": 0.91,
            "source": "memory/project/brca1.md#follow-up",
            "memory_type": "project_fact",
            "memory_type_label": "project fact",
            "memory_name": "BRCA1 follow-up note",
            "memory_description": "Tracks where the current BRCA1 evidence artifact lives.",
        }
    ]

    agent_manager.tools = []
    agent_manager.memory_indexer = fake_indexer

    try:
        with patch("config.get_rag_mode", return_value=True), patch(
            "graph.agent.create_agent",
            return_value=FakeAgent(),
        ):
            events = [event async for event in agent_manager.astream("Where are the BRCA1 notes?", [])]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer

    retrieval = next(event for event in events if event["type"] == "retrieval")
    assert retrieval["results"][0]["source"] == "memory/project/brca1.md#follow-up"
    assert retrieval["results"][0]["memory_type"] == "project_fact"
    assert retrieval["results"][0]["memory_name"] == "BRCA1 follow-up note"

    system_message = next(
        message
        for message in captured_messages["messages"]
        if message.__class__.__name__ == "SystemMessage"
    )
    assert (
        "[Retrieved Memory - background context only; not verified current project state]"
        in system_message.content
    )
    assert "[project fact]" in system_message.content
    assert "BRCA1 follow-up note" in system_message.content
    assert "memory/project/brca1.md#follow-up" in system_message.content
    assert len(system_message.content) < 1800


@pytest.mark.asyncio
async def test_agent_astream_llm_probe_picks_files_and_falls_back(isolated_chat_state):
    """rag_mode=llm_probe asks the executor LLM to pick files, with keyword RAG fallback."""
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    original_llm = agent_manager.llm

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "ok"})()},
            }

    class FakeLLM:
        def __init__(self, response_text: str):
            self.response_text = response_text
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            return type("Resp", (), {"content": self.response_text})()

    fake_indexer = MagicMock()
    fake_indexer.memory_file_count.return_value = 12  # above threshold
    fake_indexer.memory_corpus_digest.return_value = "digest-abc"
    fake_indexer.get_cached_probe_selection.return_value = None
    fake_indexer.build_probe_index.return_value = (
        "- memory/project/a.md — Alpha: A desc.\n- memory/user/b.md — Beta: B desc.",
        ["memory/project/a.md", "memory/user/b.md"],
    )
    fake_indexer.parse_probe_selection.return_value = ["memory/project/a.md"]
    fake_indexer.build_probe_results.return_value = [
        {
            "text": "alpha body",
            "score": 1.0,
            "source": "memory/project/a.md",
            "memory_name": "Alpha",
            "memory_description": "A desc.",
            "memory_type": "project_fact",
            "memory_type_label": "project fact",
        }
    ]

    agent_manager.tools = []
    agent_manager.memory_indexer = fake_indexer
    fake_llm = FakeLLM('["memory/project/a.md"]')
    agent_manager.llm = fake_llm

    try:
        with patch("config.get_rag_mode", return_value=True), patch(
            "config.get_rag_mode_name", return_value="llm_probe"
        ), patch("config.get_llm_probe_min_files", return_value=10), patch(
            "graph.agent.create_agent", return_value=FakeAgent()
        ):
            events = [
                event
                async for event in agent_manager.astream(
                    "Where are the alpha notes?", []
                )
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer
        agent_manager.llm = original_llm

    assert fake_llm.calls == 1
    retrieval = next(event for event in events if event["type"] == "retrieval")
    assert retrieval["mode"] == "llm_probe"
    assert retrieval["results"][0]["source"] == "memory/project/a.md"
    fake_indexer.parse_probe_selection.assert_called_once()
    # Keyword RAG must not be invoked when the probe produces a hit.
    fake_indexer.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_agent_astream_llm_probe_falls_back_to_keyword_on_failure(
    isolated_chat_state,
):
    """When the probe LLM raises, retrieval falls back to keyword RAG transparently."""
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    original_llm = agent_manager.llm

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "ok"})()},
            }

    class ExplodingLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("probe model unreachable")

    fake_indexer = MagicMock()
    fake_indexer.memory_file_count.return_value = 20
    fake_indexer.memory_corpus_digest.return_value = "digest-xyz"
    fake_indexer.get_cached_probe_selection.return_value = None
    fake_indexer.build_probe_index.return_value = (
        "- memory/project/a.md — Alpha: A desc.",
        ["memory/project/a.md"],
    )
    fake_indexer.retrieve.return_value = [
        {
            "text": "keyword fallback hit",
            "score": 0.5,
            "source": "memory/project/a.md",
            "memory_type": "project_fact",
            "memory_type_label": "project fact",
            "memory_name": "Alpha",
            "memory_description": "A desc.",
        }
    ]

    agent_manager.tools = []
    agent_manager.memory_indexer = fake_indexer
    agent_manager.llm = ExplodingLLM()

    try:
        with patch("config.get_rag_mode", return_value=True), patch(
            "config.get_rag_mode_name", return_value="llm_probe"
        ), patch("config.get_llm_probe_min_files", return_value=10), patch(
            "graph.agent.create_agent", return_value=FakeAgent()
        ):
            events = [
                event
                async for event in agent_manager.astream(
                    "Where are the alpha notes?", []
                )
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer
        agent_manager.llm = original_llm

    retrieval = next(event for event in events if event["type"] == "retrieval")
    assert retrieval["mode"] == "llm_probe_fallback_keyword"
    assert retrieval["results"][0]["text"] == "keyword fallback hit"
    fake_indexer.retrieve.assert_called_once()


@pytest.mark.asyncio
async def test_agent_astream_llm_probe_below_threshold_uses_keyword_rag(
    isolated_chat_state,
):
    """Too few memory files skips the probe and goes straight to keyword RAG."""
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    original_llm = agent_manager.llm

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "ok"})()},
            }

    fake_indexer = MagicMock()
    fake_indexer.memory_file_count.return_value = 3  # below threshold
    fake_indexer.retrieve.return_value = [
        {
            "text": "keyword hit",
            "score": 0.5,
            "source": "memory/project/a.md",
            "memory_type": "project_fact",
            "memory_type_label": "project fact",
            "memory_name": "Alpha",
            "memory_description": "A desc.",
        }
    ]

    agent_manager.tools = []
    agent_manager.memory_indexer = fake_indexer

    try:
        with patch("config.get_rag_mode", return_value=True), patch(
            "config.get_rag_mode_name", return_value="llm_probe"
        ), patch("config.get_llm_probe_min_files", return_value=10), patch(
            "graph.agent.create_agent", return_value=FakeAgent()
        ):
            events = [
                event
                async for event in agent_manager.astream("query", [])
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer
        agent_manager.llm = original_llm

    # No probe was invoked (build_probe_index is the probe entry point).
    fake_indexer.build_probe_index.assert_not_called()
    retrieval = next(event for event in events if event["type"] == "retrieval")
    assert retrieval["mode"] == "keyword"


@pytest.mark.asyncio
async def test_agent_astream_emits_retrieval_error_when_indexer_raises(
    isolated_chat_state, caplog
):
    """A broken MemoryIndexer must produce a log line, counter bump, and event.

    Regression test for issue #115: ``memory_indexer.retrieve`` failures used
    to be silently swallowed. The turn still continues (the ``retrieval_error``
    event is non-fatal) and ``METRICS.observe_retrieval(hit=False)`` keeps
    firing so the miss ratio stays comparable.
    """
    import logging

    from graph.agent import agent_manager
    from runtime.metrics_collector import METRICS

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "ok"})()},
            }

    class BrokenIndexer:
        def retrieve(self, *_args, **_kwargs):
            raise RuntimeError("index corrupt")

        def memory_file_count(self) -> int:
            return 0

    agent_manager.tools = []
    agent_manager.memory_indexer = BrokenIndexer()

    METRICS.reset()
    try:
        with caplog.at_level(logging.ERROR, logger="graph.agent"), patch(
            "config.get_rag_mode", return_value=True
        ), patch(
            "graph.agent.create_agent", return_value=FakeAgent()
        ):
            events = [
                event
                async for event in agent_manager.astream(
                    "Where are the BRCA1 notes?", []
                )
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer

    retrieval_error = next(
        event for event in events if event["type"] == "retrieval_error"
    )
    assert retrieval_error["query"] == "Where are the BRCA1 notes?"
    assert retrieval_error["error_type"] == "RuntimeError"
    assert "index corrupt" in retrieval_error["message"]

    assert any(
        record.name == "graph.agent"
        and record.levelno == logging.ERROR
        and "retrieval_error" in record.getMessage()
        for record in caplog.records
    )

    exposition = METRICS.render_exposition()
    assert (
        'bioapex_retrieval_errors_total{error_type="RuntimeError"} 1'
        in exposition
    )
    # Non-fatal semantics: the miss counter still ticks so the hit-ratio
    # gauge keeps its historical meaning.
    assert "bioapex_retrieval_cache_misses_total 1" in exposition

    # The turn kept running and produced the downstream token event.
    assert any(event["type"] == "token" for event in events)


@pytest.mark.asyncio
async def test_agent_astream_uses_configured_executor_recursion_limit(isolated_chat_state):
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    captured_config = {}

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            captured_config["value"] = config
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Loaded."})()},
            }

    agent_manager.tools = []
    agent_manager.memory_indexer = MagicMock()

    try:
        with patch("config.get_rag_mode", return_value=False), patch(
            "graph.agent.get_agent_runtime_limit",
            return_value=1000,
        ), patch(
            "graph.agent.create_agent",
            return_value=FakeAgent(),
        ):
            events = [
                event
                async for event in agent_manager.astream(
                    "Check the configured recursion limit.",
                    [],
                )
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer

    assert any(event["type"] == "token" for event in events)
    assert captured_config["value"] == {"recursion_limit": 1000}


@pytest.mark.asyncio
async def test_agent_astream_routes_prompt_to_relevant_skill_subset(isolated_chat_state):
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    captured_prompt = {}

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Loaded."})()},
            }

    skills_dir = isolated_chat_state / "skills"
    (skills_dir / "dilution_calculator").mkdir(parents=True)
    (skills_dir / "dilution_calculator" / "SKILL.md").write_text(
        (
            "---\n"
            "name: dilution_calculator\n"
            "description: Calculate wet-lab dilutions.\n"
            "category: bio/molecular_lab\n"
            "requires_tools: [read_file]\n"
            "requires_network: false\n"
            "user_invocable: true\n"
            "tags: [dilution, serial-dilution, wet-lab]\n"
            "aliases: [serial_dilution_planner]\n"
            "species: any\n"
            "modality: wet_lab\n"
            "stage: utilities\n"
            "stability: stable\n"
            "safety_level: low\n"
            "---\n"
            "# Body\n"
        ),
        encoding="utf-8",
    )
    (skills_dir / "paper_triage").mkdir(parents=True)
    (skills_dir / "paper_triage" / "SKILL.md").write_text(
        (
            "---\n"
            "name: paper_triage\n"
            "description: Classify relevance of a paper abstract.\n"
            "category: bio/literature\n"
            "requires_tools: [read_file]\n"
            "requires_network: false\n"
            "user_invocable: true\n"
            "tags: [paper, abstract, literature]\n"
            "species: any\n"
            "modality: literature\n"
            "stage: interpretation\n"
            "stability: experimental\n"
            "safety_level: low\n"
            "---\n"
            "# Body\n"
        ),
        encoding="utf-8",
    )

    agent_manager.tools = []
    agent_manager.memory_indexer = MagicMock()

    def _capture_agent(_llm, _tools, *, system_prompt):
        captured_prompt["system_prompt"] = system_prompt
        return FakeAgent()

    try:
        with patch("config.get_rag_mode", return_value=False), patch(
            "graph.agent.create_agent",
            side_effect=_capture_agent,
        ):
            events = [
                event
                async for event in agent_manager.astream(
                    "Can you calculate a dilution series for a 24-well plate?",
                    [],
                )
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer

    assert any(event["type"] == "token" for event in events)
    assert "dilution_calculator" in captured_prompt["system_prompt"]
    assert "paper_triage" not in captured_prompt["system_prompt"]


@pytest.mark.asyncio
async def test_agent_astream_routes_prompt_from_recent_history_path_traces(isolated_chat_state):
    from graph.agent import agent_manager

    original_tools = agent_manager.tools
    original_memory_indexer = agent_manager.memory_indexer
    captured_prompt = {}

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Loaded."})()},
            }

    skills_dir = isolated_chat_state / "skills"
    (skills_dir / "runtime_debugger").mkdir(parents=True)
    (skills_dir / "runtime_debugger" / "SKILL.md").write_text(
        (
            "---\n"
            "name: runtime_debugger\n"
            "description: Inspect backend runtime paths.\n"
            "category: bio/compute\n"
            "requires_tools: [read_file]\n"
            "requires_network: false\n"
            "user_invocable: true\n"
            "paths: [backend/runtime/**]\n"
            "species: any\n"
            "modality: compute\n"
            "stage: utilities\n"
            "stability: stable\n"
            "safety_level: low\n"
            "---\n"
            "# Body\n"
        ),
        encoding="utf-8",
    )
    (skills_dir / "paper_triage").mkdir(parents=True)
    (skills_dir / "paper_triage" / "SKILL.md").write_text(
        (
            "---\n"
            "name: paper_triage\n"
            "description: Classify relevance of a paper abstract.\n"
            "category: bio/literature\n"
            "requires_tools: [read_file]\n"
            "requires_network: false\n"
            "user_invocable: true\n"
            "species: any\n"
            "modality: literature\n"
            "stage: interpretation\n"
            "stability: experimental\n"
            "safety_level: low\n"
            "---\n"
            "# Body\n"
        ),
        encoding="utf-8",
    )

    history = [
        {
            "role": "assistant",
            "content": "Opened the runtime file.",
            "blocks": [
                {
                    "type": "tool_result",
                    "tool": "read_file",
                    "output": "runtime body",
                    "result": {
                        "structured_payload": {"path": "backend/runtime/query_engine.py"},
                        "metadata": {"requested_path": "backend/runtime/query_engine.py"},
                    },
                }
            ],
        }
    ]

    agent_manager.tools = []
    agent_manager.memory_indexer = MagicMock()

    def _capture_agent(_llm, _tools, *, system_prompt):
        captured_prompt["system_prompt"] = system_prompt
        return FakeAgent()

    try:
        with patch("config.get_rag_mode", return_value=False), patch(
            "graph.agent.create_agent",
            side_effect=_capture_agent,
        ):
            events = [
                event
                async for event in agent_manager.astream(
                    "Please continue from the file we just opened.",
                    history,
                )
            ]
    finally:
        agent_manager.tools = original_tools
        agent_manager.memory_indexer = original_memory_indexer

    assert any(event["type"] == "token" for event in events)
    assert "runtime_debugger" in captured_prompt["system_prompt"]
    assert "paper_triage" not in captured_prompt["system_prompt"]


@pytest.mark.asyncio
async def test_chat_stream_persists_retrievals_in_history(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {
            "type": "retrieval",
            "query": "Find BRCA1 notes",
            "results": [
                {
                    "text": "BRCA1 notes mention differential expression follow-up.",
                    "score": 0.82,
                    "source": "memory/project/brca1-notes.md#follow-up",
                    "memory_type": "project_fact",
                    "memory_type_label": "project fact",
                    "memory_name": "BRCA1 follow-up notes",
                    "memory_description": "Points to the follow-up evidence location.",
                },
                {
                    "text": "Protocol SOP-DEG-003 is the default analysis recipe.",
                    "score": 0.74,
                    "source": "memory/project/analysis-recipes.md#sop-deg-003",
                },
            ],
        }
        yield {"type": "token", "content": "Retrieved context loaded."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="Find BRCA1 notes", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    retrieval = next(item for item in payloads if item["type"] == "retrieval")
    assert len(retrieval["results"]) == 2
    assert retrieval["results"][0]["source"] == "memory/project/brca1-notes.md#follow-up"
    assert retrieval["results"][0]["memory_type"] == "project_fact"
    assert retrieval["results"][0]["memory_name"] == "BRCA1 follow-up notes"

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["retrievals"] == retrieval["results"]
    retrieval_block = next(
        block for block in assistant_messages[0]["blocks"] if block["type"] == "retrieval"
    )
    assert retrieval_block == {
        "type": "retrieval",
        "query": "Find BRCA1 notes",
        "results": retrieval["results"],
    }
    assert assistant_messages[0]["blocks"][-1] == {
        "type": "text",
        "text": "Retrieved context loaded.",
    }


@pytest.mark.asyncio
async def test_chat_blocks_non_local_clients_without_bearer_token(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    with pytest.raises(HTTPException) as exc_info:
        await chat(
            ChatRequest(message="Read memory", session_id=session_id),
            _request("/api/chat", host="10.0.0.8"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_chat_allows_non_local_clients_with_execution_bearer_token(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    config_path = isolated_chat_state / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "production_hardening": {
                    "api": {
                        "allow_loopback_without_auth": False,
                        "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "Done"}
        yield {"type": "done"}

    headers = [(b"authorization", b"Bearer execution-token")]
    with patch("config._CONFIG_FILE", config_path), patch.dict(
        os.environ,
        {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
        clear=False,
    ), patch.object(agent_manager, "astream", fake_astream):
        response = await chat(
            ChatRequest(message="Read memory", session_id=session_id),
            _request("/api/chat", host="10.0.0.8", headers=headers),
        )
        payloads = await _collect_sse_payloads(response)

    assert any(item["type"] == "done" for item in payloads)


@pytest.mark.asyncio
async def test_chat_stream_emits_monotonic_event_index_and_terminal_done(
    isolated_chat_state,
):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "Sequenced response."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(ChatRequest(message="Observe this turn", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    assert payloads[-1]["type"] == "done"
    assert payloads[-1]["content"] == "Sequenced response."
    assert [item["event_index"] for item in payloads] == list(
        range(1, len(payloads) + 1)
    )
    assert len({item["request_id"] for item in payloads}) == 1
    assert payloads[-1]["exit"] == {"reason": "success", "exit_code": 0}
    assert payloads[-1]["schema_version"] == 2


@pytest.mark.asyncio
async def test_chat_stream_emits_schema_version_deprecation_warning_for_v1_clients(
    isolated_chat_state,
):
    """Issue #90: v1 clients should receive a one-shot ``warning`` with
    ``kind="schema_version_deprecated"`` before the stream body so callers
    know to migrate to reading ``done.exit``.
    """
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "ok"}
        yield {"type": "done"}

    http_request = _request(
        "/api/chat",
        headers=[(b"x-runtime-event-schema-version", b"1")],
    )
    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(
            ChatRequest(message="anything", session_id=session_id),
            http_request=http_request,
        )
        payloads = await _collect_sse_payloads(response)

    warnings = [item for item in payloads if item["type"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["kind"] == "schema_version_deprecated"
    assert "done.exit" in warnings[0]["message"]
    assert payloads[-1]["type"] == "done"
    assert payloads[-1]["exit"]["reason"] == "success"


@pytest.mark.asyncio
async def test_chat_stream_omits_deprecation_warning_when_header_matches_current(
    isolated_chat_state,
):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "ok"}
        yield {"type": "done"}

    http_request = _request(
        "/api/chat",
        headers=[(b"x-runtime-event-schema-version", b"2")],
    )
    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(
            ChatRequest(message="anything", session_id=session_id),
            http_request=http_request,
        )
        payloads = await _collect_sse_payloads(response)

    assert not any(item["type"] == "warning" for item in payloads)


@pytest.mark.asyncio
async def test_chat_persists_user_message_before_executor_failure(isolated_chat_state):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def failing_astream(_message, _history):
        if False:
            yield {}
        raise RuntimeError("executor boom")

    with patch.object(agent_manager, "astream", failing_astream):
        response = await chat(ChatRequest(message="Read memory", session_id=session_id))
        payloads = await _collect_sse_payloads(response)

    error_payload = next(item for item in payloads if item["type"] == "error")
    assert error_payload["error"] == "executor boom"

    history = agent_manager.session_manager.load_session(session_id)
    user_messages = [msg for msg in history if msg["role"] == "user"]
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "Read memory"
    assert assistant_messages == []


@pytest.mark.asyncio
async def test_chat_stream_preserves_tokens_around_optional_evidence_review_tool_calls(
    isolated_chat_state,
):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "Unreviewed preamble before the tool call."}
        yield {
            "type": "tool_start",
            "tool": "evidence_review",
            "input": '{"question":"Summarize the evidence for TP53 stress response"}',
            "run_id": "tool-run-review-1",
        }
        yield {
            "type": "tool_end",
            "tool": "evidence_review",
            "output": "Reviewed 1 evidence card(s); support status: supported; confidence: medium.",
            "run_id": "tool-run-review-1",
            "result": {
                "contract_version": "tool_result.v1",
                "tool_name": "evidence_review",
                "summary": "Reviewed 1 evidence card(s); support status: supported; confidence: medium.",
                "structured_payload": {
                    "question": "Summarize the evidence for TP53 stress response",
                    "review_status": "supported",
                    "confidence": "medium",
                    "unsupported_claims_present": False,
                    "evidence_included": [
                        {
                            "artifact_type": "evidence_card",
                            "path": "artifacts/literature-retrieval/demo/evidence_card.yaml",
                        }
                    ],
                    "evidence_excluded": [],
                    "limitations": [],
                    "unresolved_conflicts": [],
                    "source_facts": [
                        {
                            "statement": "TP53 mediates a stress response.",
                            "claim_id": "claim-1",
                        }
                    ],
                    "synthesized_conclusions": [
                        {
                            "statement": "Retrieved evidence supports a medium-confidence conclusion.",
                            "support_status": "supported",
                            "confidence": "medium",
                        }
                    ],
                },
                "artifact_refs": [
                    {
                        "path": "artifacts/evidence-review/demo/evidence_review.json",
                        "artifact_type": "evidence_review",
                    }
                ],
                "warnings": [],
                "status": "success",
                "outcome": "success",
                "error": None,
                "metadata": {"review_status": "supported"},
                "source_payload": None,
            },
        }
        yield {"type": "token", "content": "Reviewed answer only."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(
            ChatRequest(
                message="Summarize the evidence for TP53 stress response",
                session_id=session_id,
            )
        )
        payloads = await _collect_sse_payloads(response)

    token_text = " ".join(item["content"] for item in payloads if item["type"] == "token")
    assert "Unreviewed preamble" in token_text
    assert "Reviewed answer only." in token_text

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert "Unreviewed preamble before the tool call." in assistant_messages[0]["content"]
    assert "Reviewed answer only." in assistant_messages[0]["content"]
    tool_calls = assistant_messages[0].get("tool_calls", [])
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool"] == "evidence_review"


@pytest.mark.asyncio
async def test_chat_stream_does_not_buffer_answer_tokens_for_biology_questions(
    isolated_chat_state,
):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "TP53 definitely controls stress response."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(
            ChatRequest(
                message="What is the evidence for TP53 stress response?",
                session_id=session_id,
            )
        )
        payloads = await _collect_sse_payloads(response)

    token_text = " ".join(item["content"] for item in payloads if item["type"] == "token")
    assert "TP53 definitely controls stress response." in token_text

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["content"] == "TP53 definitely controls stress response."
    assert assistant_messages[0].get("tool_calls", []) == []


@pytest.mark.asyncio
async def test_chat_rejects_overlapping_turn_for_same_session_with_409(
    isolated_chat_state,
):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    async def fake_astream(_message, _history):
        yield {"type": "token", "content": "first turn"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        # First call acquires the per-session turn lock synchronously before
        # returning the StreamingResponse; the lock stays held until the
        # response body is iterated to completion.
        response_first = await chat(
            ChatRequest(message="first", session_id=session_id)
        )

        # Second call for the same session_id must fail fast with 409 while the
        # first turn's stream has not yet been drained.
        with pytest.raises(HTTPException) as exc_info:
            await chat(ChatRequest(message="second", session_id=session_id))
        assert exc_info.value.status_code == 409

        # A different session_id is unaffected by the lock on ``session_id``.
        other_session_id = agent_manager.session_manager.create_session()
        response_other = await chat(
            ChatRequest(message="sibling", session_id=other_session_id)
        )
        payloads_other = await _collect_sse_payloads(response_other)
        assert any(item["type"] == "done" for item in payloads_other)

        # Drain the first stream — this releases the per-session lock.
        payloads_first = await _collect_sse_payloads(response_first)
        assert any(item["type"] == "done" for item in payloads_first)

        # After release, a follow-up turn on the original session succeeds.
        response_third = await chat(
            ChatRequest(message="third", session_id=session_id)
        )
        payloads_third = await _collect_sse_payloads(response_third)
        assert any(item["type"] == "done" for item in payloads_third)


@pytest.mark.asyncio
async def test_chat_serializes_concurrent_turns_for_same_session(isolated_chat_state):
    """When two turns race for the same session, the second must not execute
    concurrently with the first. With the 409 fast-fail contract, the second
    call raises HTTPException(409) rather than interleaving writes."""
    import asyncio

    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()

    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def paused_astream(message, _history):
        if message == "first":
            first_started.set()
            await release_first.wait()
        yield {"type": "token", "content": f"turn:{message}"}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", paused_astream):
        response_first = await chat(
            ChatRequest(message="first", session_id=session_id)
        )

        async def drain(response):
            return await _collect_sse_payloads(response)

        drain_first = asyncio.create_task(drain(response_first))

        # Wait until the first turn has actually entered the executor. At this
        # point the per-session lock is held by the in-flight generator.
        await first_started.wait()

        second_error: HTTPException | None = None
        try:
            await chat(ChatRequest(message="second", session_id=session_id))
        except HTTPException as exc:
            second_error = exc

        assert second_error is not None
        assert second_error.status_code == 409

        release_first.set()
        first_payloads = await drain_first
        # After the first turn drained and released the lock, a fresh attempt
        # must succeed — demonstrating the lock's bounded lifetime.
        response_follow = await chat(
            ChatRequest(message="follow", session_id=session_id)
        )
        follow_payloads = await _collect_sse_payloads(response_follow)

    tokens_first = [
        item["content"] for item in first_payloads if item["type"] == "token"
    ]
    tokens_follow = [
        item["content"] for item in follow_payloads if item["type"] == "token"
    ]
    assert tokens_first == ["turn:first"]
    assert tokens_follow == ["turn:follow"]


@pytest.mark.asyncio
async def test_chat_stream_uses_normal_agent_dispatch_without_workflow_state(
    isolated_chat_state,
):
    from api.chat import ChatRequest, chat
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    calls: list[tuple[str, list[dict]]] = []

    async def fake_astream(message, history):
        calls.append((message, history))
        yield {"type": "token", "content": "Handled as normal chat."}
        yield {"type": "done"}

    with patch.object(agent_manager, "astream", fake_astream):
        response = await chat(
            ChatRequest(
                message="Run the RNA-seq QC workflow",
                session_id=session_id,
            )
        )
        payloads = await _collect_sse_payloads(response)

    assert len(calls) == 1
    assert any(
        item["type"] == "token" and item["content"] == "Handled as normal chat."
        for item in payloads
    )
    assert not any(item["type"].startswith("workflow_") for item in payloads)
    assert [item for item in payloads if item["type"] == "tool_end"] == []

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["content"] == "Handled as normal chat."
