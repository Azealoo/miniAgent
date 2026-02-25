"""
Tool factory — returns core tools configured for a given project root.
"""
from pathlib import Path

import config

from .ensembl_api_tool import EnsemblApiTool
from .fetch_url_tool import FetchURLTool
from .http_json_tool import HttpJsonTool
from .ncbi_eutils_tool import NcbiEutilsTool
from .python_repl_tool import PythonReplTool
from .read_file_tool import ReadFileTool
from .search_knowledge_tool import SearchKnowledgeBaseTool
from .slurm_tool import SlurmTool
from .terminal_tool import TerminalTool
from .uniprot_api_tool import UniprotApiTool
from .write_file_tool import WriteFileTool


def get_all_tools(base_dir: Path) -> list:
    extra_roots = [str(p) for p in config.get_read_file_extra_roots(base_dir)]
    return [
        TerminalTool(base_dir=str(base_dir)),
        PythonReplTool(),
        FetchURLTool(),
        HttpJsonTool(),
        NcbiEutilsTool(),
        UniprotApiTool(),
        EnsemblApiTool(),
        SlurmTool(base_dir=str(base_dir)),
        ReadFileTool(root_dir=str(base_dir), extra_allowed_roots=extra_roots),
        WriteFileTool(root_dir=str(base_dir)),
        SearchKnowledgeBaseTool(
            knowledge_dir=str(base_dir / "knowledge"),
            storage_dir=str(base_dir / "storage"),
        ),
    ]
