import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import get_runtime_tools
from tools.policy import tool_policy_context
from tools.policy_types import ToolPolicyExecutionContext


def test_policy_wrapper_allows_execution_tool_and_keeps_policy_metadata(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    terminal = next(tool for tool in runtime_tools if tool.name == "terminal")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-1",
            request_id="request-1",
            allowed_access_scope="execution",
        )
    ):
        summary, artifact = terminal._run(command="pwd")

    assert str(tmp_path) in summary
    assert artifact["outcome"] == "success"
    assert artifact["metadata"]["policy"]["block_reason"] is None
    assert artifact["metadata"]["policy"]["status"] == "allow"
    assert artifact["warnings"] == []


def test_policy_wrapper_annotates_successful_tool_results(tmp_path):
    note_path = tmp_path / "notes.md"
    note_path.write_text("Hello from BioAPEX\n", encoding="utf-8")
    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-1",
            request_id="request-1",
            allowed_access_scope="execution",
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert "Hello from BioAPEX" in summary
    assert artifact["structured_payload"]["path"] == "notes.md"
    assert artifact["metadata"]["policy"]["access_scope"] == "inspection"
    assert artifact["metadata"]["policy"]["status"] == "allow"
    assert artifact["metadata"]["policy"]["context_available"] is True
    assert artifact["metadata"]["contract"]["interrupt_behavior"] == "restartable"
    assert artifact["metadata"]["contract"]["tool_validates_input"] is True
    assert artifact["metadata"]["contract"]["activity_summary_hint"]
    assert artifact["metadata"]["contract"]["result_summary_hint"]
    assert artifact["metadata"]["contract"]["planner_exposed"] is True
    assert artifact["metadata"]["contract"]["verifier_exposed"] is True
