import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)

    payloads: list[dict] = []
    for event in "".join(chunks).split("\n\n"):
        for line in event.split("\n"):
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))
    return payloads


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

    with patch.object(agent_manager, "astream", fake_astream), patch(
        "api.chat._generate_title_only",
        new=AsyncMock(return_value=""),
    ):
        response = await chat(
            ChatRequest(message="Read memory", session_id=session_id, stream=True)
        )
        payloads = await _collect_sse_payloads(response)

    tool_start = next(item for item in payloads if item["type"] == "tool_start")
    tool_end = next(item for item in payloads if item["type"] == "tool_end")

    assert tool_start["run_id"] == "tool-run-1"
    assert tool_end["run_id"] == "tool-run-1"
    assert tool_end["result"]["tool_name"] == "read_file"
    assert tool_end["result"]["structured_payload"]["path"] == "memory/MEMORY.md"

    history = agent_manager.session_manager.load_session(session_id)
    assistant_messages = [msg for msg in history if msg["role"] == "assistant"]
    assert assistant_messages
    assert assistant_messages[0]["tool_calls"][0]["run_id"] == "tool-run-1"
    assert assistant_messages[0]["tool_calls"][0]["result"]["tool_name"] == "read_file"
