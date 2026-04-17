import asyncio
import logging
import sys
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry


class _RaisingTool(BaseTool):
    name: str = "raising_tool"
    description: str = "Always raises."
    response_format: str = "content_and_artifact"
    exc_factory: object = None

    def _run(self, *args, **kwargs):
        raise self.exc_factory()  # type: ignore[misc]

    async def _arun(self, *args, **kwargs):
        raise self.exc_factory()  # type: ignore[misc]


def _manifest(name: str = "raising_tool") -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="Always raises.",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_policy_wrapper_exceptions",
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


def _wrap(exc_factory) -> PolicyWrappedTool:
    raising = _RaisingTool(exc_factory=exc_factory)
    return PolicyWrappedTool(
        name=raising.name,
        description=raising.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=raising,
        manifest=_manifest(raising.name),
    )


@pytest.fixture
def allow_ctx():
    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-1",
            request_id="request-1",
            allowed_access_scope="execution",
        )
    ):
        yield


def test_sync_tool_exception_returns_execution_error_envelope(allow_ctx, caplog):
    wrapper = _wrap(lambda: RuntimeError("boom"))

    with caplog.at_level(logging.ERROR, logger="tools.policy_wrappers"):
        result = wrapper._run()

    assert result is not None
    summary, artifact = result
    assert isinstance(summary, str) and summary
    assert artifact["status"] == "error"
    assert artifact["outcome"] == "execution_failure"
    assert artifact["error"] is not None
    assert artifact["error"]["code"] == "execution_failure"
    assert artifact["error"]["retriable"] is False
    assert "boom" in artifact["error"]["message"]
    assert artifact["metadata"]["exception_type"] == "RuntimeError"
    assert artifact["metadata"]["exception_source"] == "tool_execution"
    assert any(
        "raising_tool" in record.getMessage() and record.exc_info is not None
        for record in caplog.records
    ), "expected structured exception log with traceback"


def test_sync_tool_exception_never_returns_none(allow_ctx):
    wrapper = _wrap(lambda: ValueError("bad input"))

    result = wrapper._run()

    assert result is not None
    summary, artifact = result
    assert summary is not None
    assert artifact is not None
    assert artifact["status"] == "error"


def test_sync_tool_timeout_classified_as_retriable(allow_ctx):
    wrapper = _wrap(lambda: TimeoutError("upstream took too long"))

    _, artifact = wrapper._run()

    assert artifact["status"] == "error"
    assert artifact["outcome"] == "retriable_failure"
    assert artifact["error"]["code"] == "retriable_failure"
    assert artifact["error"]["retriable"] is True


def test_async_tool_exception_returns_execution_error_envelope(allow_ctx):
    wrapper = _wrap(lambda: RuntimeError("async boom"))

    result = asyncio.run(wrapper._arun())

    assert result is not None
    summary, artifact = result
    assert artifact["status"] == "error"
    assert artifact["outcome"] == "execution_failure"
    assert artifact["error"]["code"] == "execution_failure"
    assert "async boom" in artifact["error"]["message"]
