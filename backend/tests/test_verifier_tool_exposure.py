"""Pin which tools the verifier sub-agent can call.

The verifier needs read-only lookups (NCBI/UniProt/Ensembl/HTTP/file/KB) so it
can fact-check the draft instead of only critiquing prose. This test guards
against a regression where a registry edit silently hides those tools from the
verifier's exposure filter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


_LOOKUP_TOOL_NAMES = frozenset(
    {
        "fetch_url",
        "http_json",
        "ncbi_eutils",
        "uniprot_api",
        "ensembl_api",
        "evidence_retrieval",
        "read_file",
        "search_knowledge_base",
    }
)


@pytest.fixture
def verifier_tool_names(tmp_path: Path) -> frozenset[str]:
    # Imports are deferred and ordered to avoid a circular import between
    # tools/__init__.py and runtime.helper_agent_runner.
    from tools import get_runtime_tools
    from runtime.helper_agent_runner import filter_tools_by_exposure

    (tmp_path / "knowledge").mkdir()
    (tmp_path / "storage").mkdir()

    tools = get_runtime_tools(tmp_path)
    exposed = filter_tools_by_exposure(tools, "verifier")
    return frozenset(getattr(tool, "name", "") for tool in exposed)


def test_verifier_can_call_at_least_one_lookup_tool(
    verifier_tool_names: frozenset[str],
) -> None:
    assert verifier_tool_names & _LOOKUP_TOOL_NAMES, (
        "Verifier exposure must include at least one read-only lookup tool; "
        f"got {sorted(verifier_tool_names)!r}"
    )


def test_verifier_exposes_every_read_only_lookup(
    verifier_tool_names: frozenset[str],
) -> None:
    missing = _LOOKUP_TOOL_NAMES - verifier_tool_names
    assert not missing, (
        f"These read-only lookup tools are hidden from the verifier: {sorted(missing)!r}"
    )


def test_verifier_does_not_expose_destructive_tools(
    verifier_tool_names: frozenset[str],
) -> None:
    assert "write_file" not in verifier_tool_names
    assert "terminal" not in verifier_tool_names
    assert "python_repl" not in verifier_tool_names
