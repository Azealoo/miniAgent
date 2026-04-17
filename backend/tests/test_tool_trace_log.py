from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry


class _EchoTool(BaseTool):
    name: str = "echo_tool"
    description: str = "Echoes a message."
    response_format: str = "content_and_artifact"

    def _run(self, message: str = "ok", **kwargs):
        return f"echoed: {message}"

    async def _arun(self, message: str = "ok", **kwargs):
        return f"echoed: {message}"


class _RaisingTool(BaseTool):
    name: str = "raising_tool"
    description: str = "Always raises."
    response_format: str = "content_and_artifact"

    def _run(self, *args, **kwargs):
        raise RuntimeError("boom")

    async def _arun(self, *args, **kwargs):
        raise RuntimeError("boom")


def _manifest(name: str) -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="test tool",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_trace_log",
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


def _wrap(tool: BaseTool) -> PolicyWrappedTool:
    return PolicyWrappedTool(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=tool,
        manifest=_manifest(tool.name),
    )


@pytest.fixture
def trace_dir() -> Path:
    return Path(os.environ["BIOAPEX_TOOL_TRACE_DIR"])


@pytest.fixture
def exec_ctx():
    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-trace",
            request_id="req-1",
            turn_id="turn-1",
            allowed_access_scope="execution",
        )
    ):
        yield


def _read_trace_lines(trace_dir: Path, session_id: str) -> list[dict]:
    path = trace_dir / f"{session_id}.jsonl"
    assert path.exists(), f"expected trace file at {path}"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_happy_path_emits_one_trace_line(exec_ctx, trace_dir):
    wrapper = _wrap(_EchoTool())

    wrapper._run(message="hello")

    records = _read_trace_lines(trace_dir, "session-trace")
    assert len(records) == 1
    record = records[0]
    assert set(record.keys()) == {
        "ts",
        "session_id",
        "turn_id",
        "tool_name",
        "args_summary",
        "result_summary",
        "duration_ms",
        "error",
    }
    assert record["session_id"] == "session-trace"
    assert record["turn_id"] == "turn-1"
    assert record["tool_name"] == "echo_tool"
    assert "hello" in record["args_summary"]
    assert "hello" in record["result_summary"]
    assert record["error"] is None
    assert isinstance(record["duration_ms"], (int, float))
    assert record["duration_ms"] >= 0


def test_error_path_populates_error_field(exec_ctx, trace_dir):
    wrapper = _wrap(_RaisingTool())

    wrapper._run()

    records = _read_trace_lines(trace_dir, "session-trace")
    assert len(records) == 1
    record = records[0]
    assert record["tool_name"] == "raising_tool"
    assert record["error"] is not None
    assert record["error"]["code"] == "execution_failure"
    assert "boom" in record["error"]["message"]
    assert record["error"]["retriable"] is False
    assert "execution_failure" in record["result_summary"]
    assert "boom" in record["result_summary"]


def test_sensitive_kwargs_are_redacted(exec_ctx, trace_dir):
    wrapper = _wrap(_EchoTool())

    wrapper._run(
        message="hi",
        token="super-secret-token",
        api_key="AKIA_FAKE",
        password="hunter2",
        Authorization="Bearer xyz",
    )

    records = _read_trace_lines(trace_dir, "session-trace")
    assert len(records) == 1
    summary = records[0]["args_summary"]
    assert "super-secret-token" not in summary
    assert "AKIA_FAKE" not in summary
    assert "hunter2" not in summary
    assert "Bearer xyz" not in summary
    assert "<redacted>" in summary


def test_external_absolute_paths_are_redacted(exec_ctx, trace_dir):
    wrapper = _wrap(_EchoTool())

    wrapper._run(message="/etc/passwd")

    records = _read_trace_lines(trace_dir, "session-trace")
    assert len(records) == 1
    summary = records[0]["args_summary"]
    assert "/etc/passwd" not in summary
    assert "<redacted-path>" in summary


def test_trace_file_is_named_after_session_id(exec_ctx, trace_dir):
    wrapper = _wrap(_EchoTool())
    wrapper._run(message="ok")

    assert (trace_dir / "session-trace.jsonl").is_file()
