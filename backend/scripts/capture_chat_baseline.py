"""
Capture baseline chat traces from the live chat/session route functions.

This script exercises the current /api/chat and /api/sessions logic using
deterministic stub agent events, then writes raw capture artifacts under:

  context/baselines/01-baseline-freeze/captures/

The goal is to freeze the current SSE translation and session-persistence
behavior in durable files that can be regenerated later.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
CAPTURE_DIR = REPO_ROOT / "context" / "baselines" / "01-baseline-freeze" / "captures"

sys.path.insert(0, str(BACKEND_ROOT))

from graph.agent import agent_manager
from graph.session_manager import SessionManager


async def _fake_title(*args, **kwargs) -> str:
    return "Captured Baseline Title"


async def _capture_scenario(
    name: str,
    message: str,
    internal_events: list[dict[str, Any]],
) -> dict[str, Any]:
    async def fake_astream(incoming_message: str, history: list[dict[str, Any]]):
        assert incoming_message == message
        assert history == []
        for ev in internal_events:
            yield ev

    from api import chat as chat_api
    from api import sessions as sessions_api

    session_id = sessions_api.create_session()["id"]

    with patch.object(agent_manager, "astream", fake_astream), patch.object(
        chat_api, "_generate_title_only", _fake_title
    ):
        response = await chat_api.chat(
            chat_api.ChatRequest(
                message=message,
                session_id=session_id,
                stream=True,
            )
        )
        chunks = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk.decode("utf-8"))
            else:
                chunks.append(str(chunk))

    lines = [line for line in "".join(chunks).splitlines() if line]
    sse_events = [
        json.loads(line.removeprefix("data: "))
        for line in lines
        if line.startswith("data: ")
    ]

    return {
        "scenario": name,
        "request": {
            "message": message,
            "session_id": session_id,
            "stream": True,
        },
        "sse_events": sse_events,
        "stored_history": sessions_api.get_history(session_id),
    }


async def main() -> None:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        agent_manager.session_manager = SessionManager(base_dir=tmp_path)
        agent_manager.base_dir = tmp_path
        agent_manager.llm = MagicMock()
        agent_manager.memory_indexer = None
        captures = [
            await _capture_scenario(
                name="normal-chat",
                message="Summarize the current feature status.",
                internal_events=[
                    {"type": "token", "content": "All "},
                    {"type": "token", "content": "good."},
                    {"type": "done"},
                ],
            ),
            await _capture_scenario(
                name="tool-using-chat",
                message="Read the current feature file and tell me its status.",
                internal_events=[
                    {"type": "token", "content": "Let me check that."},
                    {
                        "type": "tool_start",
                        "tool": "read_file",
                        "input": "context/current-feature.md",
                        "run_id": "run-read-file",
                    },
                    {
                        "type": "tool_end",
                        "tool": "read_file",
                        "output": "# Current Feature",
                        "run_id": "run-read-file",
                    },
                    {"type": "new_response"},
                    {"type": "token", "content": "The current feature is in progress."},
                    {"type": "done"},
                ],
            ),
            await _capture_scenario(
                name="rag-enabled-chat",
                message="What do you remember about my main project?",
                internal_events=[
                    {
                        "type": "retrieval",
                        "query": "What do you remember about my main project?",
                        "results": [
                            {
                                "text": "Main project is Perturb-seq on T cells.",
                                "score": 0.91,
                                "source": "memory/MEMORY.md",
                            }
                        ],
                    },
                    {
                        "type": "token",
                        "content": "Based on memory, your main project is Perturb-seq on T cells.",
                    },
                    {"type": "done"},
                ],
            ),
        ]

    index = {}
    for capture in captures:
        out_path = CAPTURE_DIR / f"{capture['scenario']}.json"
        out_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
        index[capture["scenario"]] = str(out_path.relative_to(REPO_ROOT))

    (CAPTURE_DIR / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote {len(captures)} capture files to {CAPTURE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
