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
async def test_run_scoped_agent_preserves_partial_output_on_tool_failure():
    from langchain_core.messages import ToolMessage

    from runtime.helper_agent_runner import run_scoped_agent

    partial_stdout = (
        "stdout line 1\nstdout line 2\n[ERROR] command exited with non-zero status"
    )

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_tool_start",
                "name": "terminal",
                "run_id": "run-1",
                "data": {"input": {"command": "do_thing"}},
            }
            yield {
                "event": "on_tool_end",
                "name": "terminal",
                "run_id": "run-1",
                "data": {
                    "output": ToolMessage(
                        content=partial_stdout,
                        status="error",
                        tool_call_id="tc-1",
                        name="terminal",
                    ),
                },
            }
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("Chunk", (), {"content": "done"})()},
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
            system_prompt="sys",
            user_prompt="go",
        )

    assert len(result.tool_trace) == 1
    trace = result.tool_trace[0]
    envelope = trace["result"]
    assert envelope["status"] == "error"
    partial = envelope.get("partial_output")
    # The ToolMessage path already preserves content in summary, so
    # partial_output may stay None when it would just duplicate summary. What
    # matters is that the trace keeps the pre-error text somewhere.
    preserved_text = partial or envelope.get("summary", "")
    assert "stdout line 1" in preserved_text
    assert "stdout line 2" in preserved_text


@pytest.mark.asyncio
async def test_run_scoped_agent_captures_partial_output_when_summary_drops_it():
    from runtime.helper_agent_runner import run_scoped_agent

    pre_error_text = "progress: step 1 ok\nprogress: step 2 ok"

    # Simulate a raw event payload where the text carrying the partial output
    # differs from what normalize_tool_output collapses into the envelope
    # summary. Using a bare `[ERROR] ...` string forces summary == error
    # message; we splice the partial output in via a ToolMessage whose
    # artifact is an envelope with a short summary but whose content retains
    # the pre-error stdout.
    from langchain_core.messages import ToolMessage
    from tools.contracts import execution_error_result

    _, error_envelope = execution_error_result("terminal", "command failed")

    class FakeAgent:
        async def astream_events(self, payload, version="v2", config=None):
            yield {
                "event": "on_tool_start",
                "name": "terminal",
                "run_id": "run-2",
                "data": {"input": {"command": "do_thing"}},
            }
            yield {
                "event": "on_tool_end",
                "name": "terminal",
                "run_id": "run-2",
                "data": {
                    "output": ToolMessage(
                        content=pre_error_text,
                        artifact=error_envelope,
                        status="error",
                        tool_call_id="tc-2",
                        name="terminal",
                    ),
                },
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
            system_prompt="sys",
            user_prompt="go",
        )

    assert len(result.tool_trace) == 1
    envelope = result.tool_trace[0]["result"]
    assert envelope["status"] == "error"
    # The envelope summary came from the structured artifact and does NOT
    # contain the pre-error stdout. The runner must surface it as
    # partial_output so the trace still exposes it.
    assert "progress: step 1 ok" not in envelope["summary"]
    assert envelope["partial_output"] is not None
    assert "progress: step 1 ok" in envelope["partial_output"]
    assert "progress: step 2 ok" in envelope["partial_output"]


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
