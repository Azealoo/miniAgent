"""
Safe allowlisted file writer. The agent can only write under memory/, skills/, and knowledge/.
Path traversal is blocked. Used to update MEMORY.md, create/edit skills, or cache to knowledge.
"""
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_ALLOWED_PREFIXES = ("memory/", "skills/", "knowledge/")
_MAX_CONTENT = 50_000


class WriteFileInput(BaseModel):
    path: str = Field(
        description="Relative path under memory/, skills/, or knowledge/ (e.g. memory/MEMORY.md, knowledge/cache/source/id.md)."
    )
    content: str = Field(
        description="Full file content to write. Use UTF-8 text. File will be overwritten."
    )


class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = (
        "Write or overwrite a file under memory/, skills/, or knowledge/. "
        "Use this to update MEMORY.md, create or edit skill SKILL.md files, or save cached content to knowledge/. "
        "Path must be relative and start with one of: memory/, skills/, knowledge/. "
        "Input: path (relative) and content (full file content)."
    )
    args_schema: Type[BaseModel] = WriteFileInput
    root_dir: str = ""

    def _run(self, path: str, content: str) -> str:
        try:
            root = Path(self.root_dir).resolve()
            path_clean = path.strip().lstrip("/").removeprefix("./")

            if ".." in path_clean.split("/"):
                return "[BLOCKED] Path traversal (..) is not allowed."

            if not any(path_clean.startswith(p) for p in _ALLOWED_PREFIXES):
                return (
                    f"[BLOCKED] Path must be under one of: {list(_ALLOWED_PREFIXES)}. "
                    f"Got: {path_clean!r}"
                )

            target = (root / path_clean).resolve()
            if not str(target).startswith(str(root)):
                return "[BLOCKED] Resolved path is outside the project directory."

            if len(content) > _MAX_CONTENT:
                return f"[ERROR] Content exceeds maximum length ({_MAX_CONTENT} characters)."

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

            if path_clean == "memory/MEMORY.md":
                try:
                    from graph.agent import agent_manager
                    if agent_manager.memory_indexer:
                        agent_manager.memory_indexer.rebuild_index()
                except Exception:
                    pass

            return f"Wrote {path_clean} ({len(content)} characters)."
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, path: str, content: str) -> str:  # type: ignore[override]
        return self._run(path, content)
