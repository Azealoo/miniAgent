import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_run_scoped_agent_uses_configured_helper_recursion_limit():
    from runtime.helper_agent_runner import run_scoped_agent

    captured_config = {}

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            captured_config["value"] = config
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Planner ready."})()},
            }

    with patch(
        "runtime.helper_agent_runner.create_agent",
        return_value=FakeAgent(),
    ), patch(
        "runtime.helper_agent_runner.get_agent_runtime_limit",
        return_value=1000,
    ):
        result = await run_scoped_agent(
            llm=object(),
            tools=[],
            system_prompt="Return only JSON.",
            user_prompt="Plan this work.",
        )

    assert result.response_text == "Planner ready."
    assert captured_config["value"] == {"recursion_limit": 1000}


@pytest.mark.asyncio
async def test_run_scoped_agent_explicit_recursion_limit_overrides_config():
    from runtime.helper_agent_runner import run_scoped_agent

    captured_config = {}

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            captured_config["value"] = config
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "Verifier ready."})()},
            }

    with patch(
        "runtime.helper_agent_runner.create_agent",
        return_value=FakeAgent(),
    ), patch(
        "runtime.helper_agent_runner.get_agent_runtime_limit",
        return_value=1000,
    ):
        result = await run_scoped_agent(
            llm=object(),
            tools=[],
            system_prompt="Return only JSON.",
            user_prompt="Verify this work.",
            recursion_limit=240,
        )

    assert result.response_text == "Verifier ready."
    assert captured_config["value"] == {"recursion_limit": 240}
