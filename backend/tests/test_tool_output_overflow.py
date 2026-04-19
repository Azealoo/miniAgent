"""Large tool outputs spill to an artifact and keep a transcript preview.

Regression coverage for issue #129: when a tool returns a summary that
blows the transcript budget, PolicyWrappedTool must persist the full
content to disk, append a typed ``tool_output_overflow`` artifact ref, and
leave a truncated preview in the envelope.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.contracts import MAX_STRUCTURED_PAYLOAD_JSON_CHARS
from tools.policy import tool_policy_context
from tools.policy_types import SandboxSpec, ToolPolicyExecutionContext
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry


def _manifest(name: str, *, sandbox: SandboxSpec | None = None) -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="Returns a large fixture payload.",
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_output_overflow",
        read_only=True,
        destructive=False,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        tool_validates_input=False,
        activity_summary_hint="inspect",
        result_summary_hint="result",
        sandbox=sandbox,
    )


class _HugeTextTool(BaseTool):
    """Returns a configurable multi-line fixture."""

    name: str = "huge_text"
    description: str = "Emits a large text blob."
    response_format: str = "content_and_artifact"
    line_count: int = 100_000

    def _run(self) -> str:
        # 100K distinct lines — easily past the default 16K-char cap.
        return "\n".join(f"line-{index:06d}-payload" for index in range(self.line_count))

    async def _arun(self) -> str:  # pragma: no cover - sync path is what we test
        return self._run()


def _wrap(tool: BaseTool, *, sandbox: SandboxSpec | None = None) -> PolicyWrappedTool:
    return PolicyWrappedTool(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=tool,
        manifest=_manifest(tool.name, sandbox=sandbox),
    )


@pytest.fixture
def run_context() -> ToolPolicyExecutionContext:
    return ToolPolicyExecutionContext(
        session_id="sess-overflow",
        request_id="req-overflow",
        turn_id="turn-7",
        allowed_access_scope="execution",
    )


def test_large_summary_spills_to_artifact_and_preserves_preview(
    run_context, tmp_path, monkeypatch
):
    """100K-line fixture: summary truncates, artifact_refs carries the spill."""

    monkeypatch.setenv("BIOAPEX_TOOL_OUTPUT_DIR", str(tmp_path / "tool-outputs"))

    tool = _HugeTextTool()
    expected_full_text = tool._run()
    assert len(expected_full_text.encode("utf-8")) > MAX_STRUCTURED_PAYLOAD_JSON_CHARS, (
        "fixture must exceed the default overflow threshold"
    )

    wrapper = _wrap(tool)
    with tool_policy_context(run_context):
        summary, artifact = wrapper._run()

    # (a) Summary in the transcript is truncated.
    assert "...[output truncated" in summary
    assert len(summary.encode("utf-8")) <= MAX_STRUCTURED_PAYLOAD_JSON_CHARS + 128
    assert "output_truncated" in artifact["warnings"]

    # (b) Envelope carries exactly one tool_output_overflow artifact ref.
    overflow_refs = [
        ref
        for ref in artifact["artifact_refs"]
        if ref.get("artifact_type") == "tool_output_overflow"
    ]
    assert len(overflow_refs) == 1, artifact["artifact_refs"]
    ref = overflow_refs[0]
    assert ref["path"], "artifact ref must include a path"
    assert ref["label"] == "huge_text full output"
    assert artifact["metadata"]["tool_output_overflow"]["triggered"] is True
    assert (
        artifact["metadata"]["tool_output_overflow"]["summary_bytes_before_cap"]
        == len(expected_full_text.encode("utf-8"))
    )

    # (c) The referenced file holds the full original text, not the preview.
    spill_path = (tmp_path / "tool-outputs").rglob("*.txt")
    spill_files = list(spill_path)
    assert len(spill_files) == 1, spill_files
    persisted = spill_files[0].read_text(encoding="utf-8")
    assert persisted == expected_full_text
    assert persisted.count("\n") == tool.line_count - 1


def test_sandbox_cap_still_spills_full_output(run_context, tmp_path, monkeypatch):
    """A tighter sandbox cap must not swallow the artifact spill behaviour."""

    monkeypatch.setenv("BIOAPEX_TOOL_OUTPUT_DIR", str(tmp_path / "tool-outputs"))

    tool = _HugeTextTool(line_count=500)
    wrapper = _wrap(tool, sandbox=SandboxSpec(max_output_bytes=256))

    expected_full_text = tool._run()
    with tool_policy_context(run_context):
        summary, artifact = wrapper._run()

    # Sandbox cap fires — existing marker/warning/metadata preserved.
    assert "[sandbox output truncated]" in summary
    assert "sandbox_output_truncated" in artifact["warnings"]
    assert artifact["metadata"]["sandbox"]["max_output_bytes"] == 256

    # Plus the new overflow artifact is emitted with the untruncated text.
    overflow_refs = [
        ref
        for ref in artifact["artifact_refs"]
        if ref.get("artifact_type") == "tool_output_overflow"
    ]
    assert len(overflow_refs) == 1
    persisted = Path((tmp_path / "tool-outputs")).rglob("*.txt")
    spill_files = list(persisted)
    assert len(spill_files) == 1
    assert spill_files[0].read_text(encoding="utf-8") == expected_full_text


def test_small_output_passes_through_unchanged(run_context, tmp_path, monkeypatch):
    """Short outputs must not trigger the overflow artifact path."""

    monkeypatch.setenv("BIOAPEX_TOOL_OUTPUT_DIR", str(tmp_path / "tool-outputs"))

    tool = _HugeTextTool(line_count=5)
    wrapper = _wrap(tool)

    with tool_policy_context(run_context):
        summary, artifact = wrapper._run()

    assert "truncated" not in summary
    assert not any(
        ref.get("artifact_type") == "tool_output_overflow"
        for ref in artifact["artifact_refs"]
    )
    assert not (tmp_path / "tool-outputs").exists() or not any(
        (tmp_path / "tool-outputs").rglob("*.txt")
    )
