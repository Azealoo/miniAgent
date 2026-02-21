"""
Sandboxed file reader. The agent can only read files under root_dir.
"""
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_MAX_OUTPUT = 10_000


class ReadFileInput(BaseModel):
    path: str = Field(
        description="Relative path to the file (relative to the project root directory)."
    )


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = (
        "Read the contents of a file in the project directory. "
        "Path must be relative to the project root. "
        "Use this to read SKILL.md files, config files, or any project document."
    )
    args_schema: Type[BaseModel] = ReadFileInput
    root_dir: str = ""

    def _run(self, path: str) -> str:
        try:
            root = Path(self.root_dir).resolve()
            target = (root / path).resolve()

            # Path traversal guard
            if not str(target).startswith(str(root)):
                return "[BLOCKED] Access denied — path is outside the project directory."

            if not target.exists():
                return f"[ERROR] File not found: {path}"

            if not target.is_file():
                return f"[ERROR] Not a file: {path}"

            content = target.read_text(encoding="utf-8")
            if len(content) > _MAX_OUTPUT:
                content = content[:_MAX_OUTPUT] + "\n...[output truncated]"
            return content

        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, path: str) -> str:  # type: ignore[override]
        return self._run(path)
