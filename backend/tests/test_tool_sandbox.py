"""Per-dimension coverage for the typed execution sandbox contract.

The sandbox layer adds five enforcement dimensions on top of the existing
tool policy wrapper: declared file roots, allowed environment variables,
network scope, wall-clock budget, and output-byte cap. Each test below
exercises exactly one of those dimensions against the tool (or pair of
tools) the classifier tagged as high-risk.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from graph.approval_store import compute_args_hash
from tools import get_runtime_tools
from tools.policy import (
    evaluate_sandbox_arguments,
    scoped_environment,
    tool_policy_context,
)
from tools.policy_types import (
    SandboxSpec,
    ToolPolicyExecutionContext,
)
from tools.policy_wrappers import PolicyWrappedTool
from tools.registry import ToolManifestEntry


def _approved_context(*approved: tuple[str, str]) -> ToolPolicyExecutionContext:
    return ToolPolicyExecutionContext(
        session_id="session-1",
        request_id="request-1",
        allowed_access_scope="execution",
        approved_tool_runs=frozenset(approved),
    )


def _approved_for(tool_name: str, kwargs: dict | None = None) -> ToolPolicyExecutionContext:
    return _approved_context((tool_name, compute_args_hash(kwargs or {})))


def _find_tool(tools, name: str) -> PolicyWrappedTool:
    return next(tool for tool in tools if tool.name == name)


# -------------------------------------------------------------------------
# Declarative: every high-risk tool ships with a SandboxSpec on its manifest
# -------------------------------------------------------------------------


def test_high_risk_tools_declare_sandbox_spec(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    for name in ("python_repl", "fetch_url", "http_json", "write_file"):
        tool = _find_tool(runtime_tools, name)
        assert tool.manifest.sandbox is not None, (
            f"{name} manifest must declare a SandboxSpec"
        )
        assert tool.manifest.sandbox.max_wall_clock_seconds is not None
        assert tool.manifest.sandbox.max_output_bytes is not None


def test_workflow_runner_sandbox_specs_cover_all_runners():
    from workflows.runners import WORKFLOW_RUNNER_SANDBOX_SPECS

    expected = {
        "workflows.runners.rna_seq_qc",
        "workflows.runners.rnaseq_qc_de",
        "workflows.runners.perturb_seq",
    }
    assert expected.issubset(set(WORKFLOW_RUNNER_SANDBOX_SPECS))
    for spec in WORKFLOW_RUNNER_SANDBOX_SPECS.values():
        assert isinstance(spec, SandboxSpec)
        assert spec.network_scope in ("none", "public", "any")


# -------------------------------------------------------------------------
# Dimension 1: file-root scoping — write_file
# -------------------------------------------------------------------------


def test_write_file_sandbox_blocks_path_outside_allowed_roots(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    write_file = _find_tool(runtime_tools, "write_file")
    assert write_file.manifest.sandbox is not None

    call_kwargs = {"path": "artifacts/out.txt", "content": "hello"}
    with tool_policy_context(_approved_for("write_file", call_kwargs)):
        summary, artifact = write_file._run(**call_kwargs)

    assert summary.startswith("[BLOCKED]")
    assert artifact["outcome"] == "blocked"
    assert artifact["metadata"]["policy_block_reason"] == "sandbox_file_root_violation"
    assert artifact["metadata"]["policy"]["block_reason"] == "sandbox_file_root_violation"
    assert artifact["status"] == "error"


# -------------------------------------------------------------------------
# Dimension 2: network scope — fetch_url (scope="public" rejects loopback)
#                               http_json (scope="public" rejects loopback)
# -------------------------------------------------------------------------


def test_fetch_url_sandbox_blocks_loopback_url_before_dispatch(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    fetch_url = _find_tool(runtime_tools, "fetch_url")

    with tool_policy_context(_approved_for("fetch_url", {"url": "http://127.0.0.1:8080/admin"})):
        summary, artifact = fetch_url._run(url="http://127.0.0.1:8080/admin")

    assert summary.startswith("[BLOCKED]")
    assert artifact["outcome"] == "blocked"
    assert (
        artifact["metadata"]["policy_block_reason"]
        == "sandbox_network_scope_violation"
    )


def test_http_json_sandbox_blocks_private_ip_url_before_dispatch(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    http_json = _find_tool(runtime_tools, "http_json")

    http_kwargs = {"method": "GET", "url": "http://10.0.0.5/api"}
    with tool_policy_context(_approved_for("http_json", http_kwargs)):
        summary, artifact = http_json._run(**http_kwargs)

    assert summary.startswith("[BLOCKED]")
    assert artifact["outcome"] == "blocked"
    assert (
        artifact["metadata"]["policy_block_reason"]
        == "sandbox_network_scope_violation"
    )


# -------------------------------------------------------------------------
# Dimension 3: env-var scoping — only allowlisted variables are visible
# -------------------------------------------------------------------------


class _EnvProbeInput(BaseModel):
    key: str = Field(description="Environment variable to read.")


class _EnvProbeTool(BaseTool):
    name: str = "env_probe"
    description: str = "Read os.environ[key] and return it verbatim."
    args_schema: type[BaseModel] = _EnvProbeInput

    def _run(self, key: str) -> str:
        return os.environ.get(key, "<missing>")

    async def _arun(self, key: str) -> str:  # type: ignore[override]
        return os.environ.get(key, "<missing>")


def _env_probe_wrapper(sandbox: SandboxSpec) -> PolicyWrappedTool:
    probe = _EnvProbeTool()
    manifest = ToolManifestEntry(
        name=probe.name,
        description=probe.description,
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_sandbox",
        read_only=True,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        sandbox=sandbox,
    )
    return PolicyWrappedTool(
        name=probe.name,
        description=probe.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=probe,
        manifest=manifest,
    )


def test_sandbox_env_allowlist_hides_disallowed_vars_during_dispatch(monkeypatch):
    monkeypatch.setenv("ALLOWED_VAR", "keep-me")
    monkeypatch.setenv("SECRET_TOKEN", "hunter2")

    wrapper = _env_probe_wrapper(
        SandboxSpec(allowed_env_vars=("ALLOWED_VAR",))
    )

    with tool_policy_context(_approved_context()):
        allowed_summary, _ = wrapper._run(key="ALLOWED_VAR")
        secret_summary, _ = wrapper._run(key="SECRET_TOKEN")

    assert allowed_summary == "keep-me"
    assert secret_summary == "<missing>"
    # Environment is restored after the dispatch returns.
    assert os.environ.get("SECRET_TOKEN") == "hunter2"


def test_scoped_environment_restores_original_values(monkeypatch):
    monkeypatch.setenv("SAMPLE_VAR", "original")
    with scoped_environment(("PATH",)):
        assert os.environ.get("SAMPLE_VAR") is None
    assert os.environ["SAMPLE_VAR"] == "original"


# -------------------------------------------------------------------------
# Dimension 4: wall-clock cap — dispatch is aborted and returns blocked
# -------------------------------------------------------------------------


class _SlowInput(BaseModel):
    seconds: float = Field(description="How long to sleep.")


class _SlowTool(BaseTool):
    name: str = "slow_tool"
    description: str = "Sleeps for the requested duration."
    args_schema: type[BaseModel] = _SlowInput

    def _run(self, seconds: float) -> str:
        time.sleep(seconds)
        return "done"

    async def _arun(self, seconds: float) -> str:  # type: ignore[override]
        await asyncio.sleep(seconds)
        return "done"


def _slow_wrapper(max_wall_clock: float) -> PolicyWrappedTool:
    slow = _SlowTool()
    manifest = ToolManifestEntry(
        name=slow.name,
        description=slow.description,
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_sandbox",
        read_only=True,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        sandbox=SandboxSpec(max_wall_clock_seconds=max_wall_clock),
    )
    return PolicyWrappedTool(
        name=slow.name,
        description=slow.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=slow,
        manifest=manifest,
    )


def test_sandbox_wall_clock_exceeded_returns_blocked_envelope():
    wrapper = _slow_wrapper(max_wall_clock=0.1)

    with tool_policy_context(_approved_context()):
        summary, artifact = wrapper._run(seconds=0.6)

    assert summary.startswith("[BLOCKED]")
    assert artifact["outcome"] == "blocked"
    assert (
        artifact["metadata"]["policy_block_reason"] == "sandbox_wall_clock_exceeded"
    )
    assert artifact["metadata"]["sandbox_wall_clock_seconds"] == pytest.approx(0.1)


def test_sandbox_wall_clock_exceeded_returns_blocked_envelope_async():
    wrapper = _slow_wrapper(max_wall_clock=0.1)

    async def _exercise():
        with tool_policy_context(_approved_context()):
            return await wrapper._arun(seconds=0.6)

    summary, artifact = asyncio.run(_exercise())
    assert summary.startswith("[BLOCKED]")
    assert (
        artifact["metadata"]["policy_block_reason"] == "sandbox_wall_clock_exceeded"
    )


# -------------------------------------------------------------------------
# Dimension 5: max output bytes — summary is capped with a warning
# -------------------------------------------------------------------------


class _BigOutputTool(BaseTool):
    name: str = "big_output"
    description: str = "Returns a large string."

    def _run(self) -> str:
        return "x" * 5_000

    async def _arun(self) -> str:  # type: ignore[override]
        return "x" * 5_000


def test_sandbox_output_byte_cap_truncates_summary_and_warns():
    tool = _BigOutputTool()
    manifest = ToolManifestEntry(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        response_format="content_and_artifact",
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_sandbox",
        read_only=True,
        concurrency_safe=True,
        planner_exposed=True,
        verifier_exposed=True,
        interrupt_behavior="restartable",
        sandbox=SandboxSpec(max_output_bytes=128),
    )
    wrapper = PolicyWrappedTool(
        name=tool.name,
        description=tool.description,
        args_schema=None,
        response_format="content_and_artifact",
        wrapped_tool=tool,
        manifest=manifest,
    )

    with tool_policy_context(_approved_context()):
        summary, artifact = wrapper._run()

    assert "sandbox_output_truncated" in artifact["warnings"]
    assert "[sandbox output truncated]" in summary
    assert len(summary.encode("utf-8")) <= 128 + len("\n...[sandbox output truncated]")
    assert artifact["metadata"]["sandbox"]["output_truncated"] is True
    assert artifact["metadata"]["sandbox"]["max_output_bytes"] == 128


# -------------------------------------------------------------------------
# Wrapper-level assertion: a sandbox violation returns a typed envelope,
# never raises through the LangChain tool plumbing.
# -------------------------------------------------------------------------


def test_sandbox_violation_surfaces_as_typed_blocked_envelope(tmp_path):
    runtime_tools = get_runtime_tools(tmp_path)
    write_file = _find_tool(runtime_tools, "write_file")

    call_kwargs = {"path": "../etc/passwd", "content": "x"}
    with tool_policy_context(_approved_for("write_file", call_kwargs)):
        summary, artifact = write_file._run(**call_kwargs)

    assert artifact["contract_version"] == "tool_result.v1"
    assert artifact["tool_name"] == "write_file"
    assert artifact["status"] == "error"
    assert artifact["outcome"] == "blocked"
    assert artifact["error"] is not None
    assert artifact["error"]["code"] == "blocked"
    assert summary.startswith("[BLOCKED]")


# -------------------------------------------------------------------------
# Direct coverage of evaluate_sandbox_arguments so the helper is exercised
# independently of the PolicyWrappedTool dispatch path.
# -------------------------------------------------------------------------


def _manifest_with(sandbox: SandboxSpec, name: str = "probe") -> ToolManifestEntry:
    return ToolManifestEntry(
        name=name,
        description="",
        args_schema=None,
        response_format=None,
        access_scope="inspection",
        evidence_requirement="none",
        output_contract_version="tool_result.v1",
        source_module="tests.test_tool_sandbox",
        sandbox=sandbox,
    )


def test_evaluate_sandbox_arguments_no_sandbox_is_allow():
    manifest = _manifest_with(SandboxSpec())
    # With no file roots and network_scope="any", any path/url is fine.
    decision = evaluate_sandbox_arguments(manifest, (), {"path": "anywhere/file.txt"})
    assert decision.status == "allow"


def test_evaluate_sandbox_arguments_blocks_traversal_in_path_arg():
    manifest = _manifest_with(SandboxSpec(allowed_file_roots=("memory/",)))
    decision = evaluate_sandbox_arguments(
        manifest, (), {"path": "memory/../../escape.txt"}
    )
    assert decision.status == "blocked"
    assert decision.block_reason == "sandbox_file_root_violation"


def test_evaluate_sandbox_arguments_network_none_blocks_any_url():
    manifest = _manifest_with(SandboxSpec(network_scope="none"))
    decision = evaluate_sandbox_arguments(
        manifest, (), {"url": "https://example.com/data"}
    )
    assert decision.status == "blocked"
    assert decision.block_reason == "sandbox_network_scope_violation"


def test_public_network_blocks_loopback_ip_even_when_in_allowed_hosts():
    """Regression: an allowed_hosts entry of '127.0.0.1' must not admit loopback."""
    manifest = _manifest_with(
        SandboxSpec(network_scope="public", allowed_hosts=("127.0.0.1",))
    )
    decision = evaluate_sandbox_arguments(
        manifest, (), {"url": "http://127.0.0.1/admin"}
    )
    assert decision.status == "blocked"
    assert decision.block_reason == "sandbox_network_scope_violation"
    assert "private/reserved" in (decision.block_message or "")


def test_public_network_blocks_localhost_even_when_in_allowed_hosts():
    """Regression: an allowed_hosts entry of 'localhost' must not admit loopback resolution."""
    manifest = _manifest_with(
        SandboxSpec(network_scope="public", allowed_hosts=("localhost",))
    )
    decision = evaluate_sandbox_arguments(
        manifest, (), {"url": "http://localhost/admin"}
    )
    assert decision.status == "blocked"
    assert decision.block_reason == "sandbox_network_scope_violation"


def test_public_network_admits_valid_public_host_in_allowed_hosts():
    """The admit path still works for a genuinely public host."""
    manifest = _manifest_with(
        SandboxSpec(network_scope="public", allowed_hosts=("8.8.8.8",))
    )
    decision = evaluate_sandbox_arguments(
        manifest, (), {"url": "http://8.8.8.8/dns"}
    )
    assert decision.status == "allow"
