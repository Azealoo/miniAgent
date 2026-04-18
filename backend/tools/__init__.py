"""
Tool factory — returns core tools configured for a given project root.
"""
from pathlib import Path

import config

from .policy_wrappers import build_policy_wrapped_tools
from .registry import ToolManifestEntry, ToolRegistry, build_tool_registry
from .ensembl_api_tool import EnsemblApiTool
from .fetch_url_tool import FetchURLTool
from .http_json_tool import HttpJsonTool
from .ncbi_eutils_tool import NcbiEutilsTool
from .plan_agent_tool import PlanAgentTool
from .python_repl_tool import PythonReplTool
from .read_file_tool import ReadFileTool
from .search_knowledge_tool import SearchKnowledgeBaseTool
from .terminal_tool import TerminalTool
from .uniprot_api_tool import UniprotApiTool
from .verification_agent_tool import VerificationAgentTool
from .write_file_tool import WriteFileTool


def _instantiate_all_tools(base_dir: Path) -> list:
    from .evidence_retrieval_tool import EvidenceRetrievalTool
    from .evidence_review_tool import EvidenceReviewTool
    from .entity_grounding_tool import EntityGroundingTool

    extra_roots = [str(p) for p in config.get_read_file_extra_roots(base_dir)]
    return [
        TerminalTool(base_dir=str(base_dir)),
        PythonReplTool(base_dir=str(base_dir)),
        FetchURLTool(),
        HttpJsonTool(),
        NcbiEutilsTool(),
        EvidenceRetrievalTool(base_dir=str(base_dir)),
        EvidenceReviewTool(base_dir=str(base_dir)),
        EntityGroundingTool(base_dir=str(base_dir)),
        PlanAgentTool(),
        VerificationAgentTool(),
        UniprotApiTool(),
        EnsemblApiTool(),
        ReadFileTool(root_dir=str(base_dir), extra_allowed_roots=extra_roots),
        WriteFileTool(root_dir=str(base_dir)),
        SearchKnowledgeBaseTool(
            knowledge_dir=str(base_dir / "knowledge"),
            storage_dir=str(base_dir / "storage"),
        ),
    ]


def get_all_tools(base_dir: Path) -> list:
    return _instantiate_all_tools(base_dir)


def get_tool_registry(base_dir: Path) -> ToolRegistry:
    return build_tool_registry(base_dir, _instantiate_all_tools(base_dir))


def get_tool_manifest_entries(base_dir: Path) -> tuple[ToolManifestEntry, ...]:
    return get_tool_registry(base_dir).manifests


def get_runtime_tools(base_dir: Path) -> list:
    return build_policy_wrapped_tools(get_tool_registry(base_dir))
