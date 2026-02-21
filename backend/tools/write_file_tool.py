from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from pathlib import Path

ALLOWED_PREFIXES = ("memory/", "skills/", "knowledge/")
MAX_CONTENT = 50_000


class WriteFileInput(BaseModel):
    path: str = Field(description="Relative path under the project root (memory/, skills/, or knowledge/ only)")
    content: str = Field(description="Full content to write to the file")


class WriteFileTool(BaseTool):
    name: str = "write_file"
    description: str = (
        "Write content to a file. Allowed paths: memory/, skills/, knowledge/. "
        "Always read the file first before overwriting to avoid losing data. "
        "Use this to update MEMORY.md or create/edit skill files."
    )
    args_schema: type[BaseModel] = WriteFileInput
    root_dir: str = ""

    def _run(self, path: str, content: str) -> str:
        # Whitelist check
        if not any(path.startswith(p) for p in ALLOWED_PREFIXES):
            return f"Error: path '{path}' is not in an allowed directory ({', '.join(ALLOWED_PREFIXES)})"
        # Path traversal protection
        root = Path(self.root_dir).resolve()
        target = (root / path).resolve()
        if not str(target).startswith(str(root)):
            return "Error: path traversal detected"
        # Content cap
        if len(content) > MAX_CONTENT:
            return f"Error: content too large ({len(content)} chars, max {MAX_CONTENT})"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        # Rebuild memory index if MEMORY.md was written
        if path == "memory/MEMORY.md":
            try:
                from graph.memory_indexer import memory_indexer
                memory_indexer.rebuild_index()
            except Exception:
                pass
        return f"Wrote {len(content)} characters to {path}"

    async def _arun(self, path: str, content: str) -> str:
        return self._run(path, content)
