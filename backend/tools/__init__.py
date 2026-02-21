"""
Tool factory — returns the 5 core tools configured for a given project root.
"""
from pathlib import Path

from .fetch_url_tool import FetchURLTool
from .python_repl_tool import PythonReplTool
from .read_file_tool import ReadFileTool
from .search_knowledge_tool import SearchKnowledgeBaseTool
from .terminal_tool import TerminalTool
from .write_file_tool import WriteFileTool


def get_all_tools(base_dir: Path) -> list:
    return [
        TerminalTool(base_dir=str(base_dir)),
        PythonReplTool(),
        FetchURLTool(),
        ReadFileTool(root_dir=str(base_dir)),
        WriteFileTool(root_dir=str(base_dir)),
        SearchKnowledgeBaseTool(
            knowledge_dir=str(base_dir / "knowledge"),
            storage_dir=str(base_dir / "storage"),
        ),
    ]
