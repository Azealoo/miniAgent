import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import get_runtime_tools
from tools.policy import (
    active_skill_specs_from_entries,
    set_active_skills_on_current_context,
    tool_policy_context,
)
from tools.policy_types import ActiveSkillSpec, ToolPolicyExecutionContext


def test_policy_wrapper_allows_execution_tool_and_keeps_policy_metadata(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    terminal = next(tool for tool in runtime_tools if tool.name == "terminal")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-1",
            request_id="request-1",
            allowed_access_scope="execution",
            approved_tool_runs=frozenset({"terminal"}),
        )
    ):
        summary, artifact = terminal._run(command="pwd")

    assert str(tmp_path) in summary
    assert artifact["outcome"] == "success"
    assert artifact["metadata"]["policy"]["block_reason"] is None
    assert artifact["metadata"]["policy"]["status"] == "allow"
    assert artifact["warnings"] == []


def test_policy_wrapper_short_circuits_to_needs_approval_for_gated_tool(tmp_path):
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

    assert summary.startswith("[NEEDS_APPROVAL]")
    assert artifact["outcome"] == "needs_approval"
    assert artifact["status"] == "error"
    assert artifact["error"]["code"] == "needs_approval"
    assert artifact["metadata"]["policy"]["status"] == "needs_approval"
    assert artifact["metadata"]["policy"]["approval_reason"] == "requires_approval"
    assert artifact["metadata"]["contract"]["requires_approval"] is True


def test_policy_wrapper_skips_approval_when_run_already_approved(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    write_file = next(tool for tool in runtime_tools if tool.name == "write_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-1",
            request_id="request-1",
            allowed_access_scope="execution",
            approved_tool_runs=frozenset({"write_file"}),
        )
    ):
        summary, artifact = write_file._run(
            path="memory/notes.txt",
            content="approved write",
        )

    assert artifact["outcome"] == "success"
    assert "Wrote memory/notes.txt" in summary
    assert artifact["metadata"]["policy"]["status"] == "allow"


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


# ──────────────────────────────────────────────────────────────────────────────
# Skill tools_allowed enforcement
# ──────────────────────────────────────────────────────────────────────────────


def test_active_skill_tools_allowed_permits_listed_tool(tmp_path):
    note_path = tmp_path / "notes.md"
    note_path.write_text("listed tool ok\n", encoding="utf-8")
    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-skill-allow",
            request_id="request-skill-allow",
            allowed_access_scope="execution",
            active_skills=(
                ActiveSkillSpec(
                    name="paper_triage",
                    tools_allowed=("read_file", "search_knowledge_base"),
                ),
            ),
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert artifact["outcome"] == "success"
    assert "listed tool ok" in summary
    assert artifact["metadata"]["policy"]["status"] == "allow"
    assert artifact["metadata"]["policy"]["block_reason"] is None


def test_active_skill_tools_allowed_blocks_unlisted_tool(tmp_path):
    note_path = tmp_path / "notes.md"
    note_path.write_text("should never be read\n", encoding="utf-8")
    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-skill-deny",
            request_id="request-skill-deny",
            allowed_access_scope="execution",
            active_skills=(
                ActiveSkillSpec(
                    name="paper_triage",
                    tools_allowed=("search_knowledge_base",),
                ),
            ),
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert summary.startswith("[BLOCKED]")
    assert artifact["outcome"] == "blocked"
    policy = artifact["metadata"]["policy"]
    assert policy["status"] == "blocked"
    assert policy["block_reason"] == "skill_tools_allowed_violation"
    # The tool was short-circuited before ever touching the file.
    assert artifact.get("structured_payload") != {"path": "notes.md"}


def test_union_across_active_skills_permits_tool_listed_anywhere(tmp_path):
    note_path = tmp_path / "notes.md"
    note_path.write_text("union ok\n", encoding="utf-8")
    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-skill-union",
            request_id="request-skill-union",
            allowed_access_scope="execution",
            active_skills=(
                ActiveSkillSpec(
                    name="paper_triage",
                    tools_allowed=("search_knowledge_base",),
                ),
                ActiveSkillSpec(
                    name="data_location_help",
                    tools_allowed=("read_file",),
                ),
            ),
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert artifact["outcome"] == "success"
    assert "union ok" in summary


def test_skill_without_tools_allowed_does_not_restrict_anything(tmp_path):
    note_path = tmp_path / "notes.md"
    note_path.write_text("no restriction\n", encoding="utf-8")
    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-skill-empty",
            request_id="request-skill-empty",
            allowed_access_scope="execution",
            active_skills=(
                ActiveSkillSpec(name="paper_triage", tools_allowed=()),
            ),
        )
    ):
        summary, artifact = read_file._run(path="notes.md")

    assert artifact["outcome"] == "success"
    assert artifact["metadata"]["policy"]["status"] == "allow"


def test_exposure_flags_round_trip_through_active_skill_spec():
    specs = active_skill_specs_from_entries(
        [
            {
                "name": "planner_hidden_skill",
                "tools_allowed": ["read_file"],
                "planner_visible": False,
                "verifier_visible": True,
            },
            {
                "name": "verifier_hidden_skill",
                "tools_allowed": [],
                "planner_visible": True,
                "verifier_visible": False,
            },
            {
                # Missing name is skipped to keep the spec tuple clean.
                "tools_allowed": ["read_file"],
            },
        ]
    )

    assert [spec.name for spec in specs] == [
        "planner_hidden_skill",
        "verifier_hidden_skill",
    ]
    assert specs[0].planner_visible is False
    assert specs[0].verifier_visible is True
    assert specs[0].tools_allowed == ("read_file",)
    assert specs[1].planner_visible is True
    assert specs[1].verifier_visible is False
    assert specs[1].tools_allowed == ()


def test_set_active_skills_on_current_context_mutates_in_flight_context(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    read_file = next(tool for tool in runtime_tools if tool.name == "read_file")
    note_path = tmp_path / "notes.md"
    note_path.write_text("late binding\n", encoding="utf-8")

    with tool_policy_context(
        ToolPolicyExecutionContext(
            session_id="session-skill-late",
            request_id="request-skill-late",
            allowed_access_scope="execution",
        )
    ):
        set_active_skills_on_current_context(
            [{"name": "paper_triage", "tools_allowed": ["search_knowledge_base"]}]
        )
        summary, artifact = read_file._run(path="notes.md")

    assert artifact["outcome"] == "blocked"
    assert (
        artifact["metadata"]["policy"]["block_reason"]
        == "skill_tools_allowed_violation"
    )
    assert summary.startswith("[BLOCKED]")
