"""
Sandboxed file reader. The agent can read files under root_dir or under
any path in extra_allowed_roots (for skills in .agents/skills or configurable dirs).
"""
import re
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_MAX_OUTPUT = 10_000

# File name/extension patterns that must never be read (credential / secret files)
_BLOCKED_FILENAMES = {".env"}
_BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
_BLOCKED_PATTERNS_RE = [
    re.compile(r"^\.env(\..+)?$", re.I),  # .env, .env.local, .env.production, etc.
    re.compile(r"^.*\.env$", re.I),        # any file ending with .env
]


def _is_credential_file(path: Path) -> bool:
    name = path.name.lower()
    if name in _BLOCKED_FILENAMES:
        return True
    if path.suffix.lower() in _BLOCKED_SUFFIXES:
        return True
    return any(p.match(path.name) for p in _BLOCKED_PATTERNS_RE)


class ReadFileInput(BaseModel):
    path: str = Field(
        description="Path to the file: relative to project root, or absolute if under allowed roots."
    )


class ReadFileTool(BaseTool):
    name: str = "read_file"
    description: str = (
        "Read the contents of a file in the project directory. "
        "Path can be relative to the project root or absolute if under allowed roots. "
        "Use this to read SKILL.md files, config files, or any project document."
    )
    args_schema: Type[BaseModel] = ReadFileInput
    root_dir: str = ""
    extra_allowed_roots: list[str] = []

    def _run(self, path: str) -> str:
        try:
            root = Path(self.root_dir).resolve()
            path_str = path.strip()
            if Path(path_str).is_absolute():
                target = Path(path_str).resolve()
            else:
                target = (root / path_str).resolve()

            allowed = [root] + [Path(r).resolve() for r in self.extra_allowed_roots]
            # Use relative_to() to avoid prefix attacks where a sibling directory
            # name starts with an allowed root's name (e.g. /project/backend_evil).
            def _is_under(t: Path, base: Path) -> bool:
                try:
                    t.relative_to(base)
                    return True
                except ValueError:
                    return False

            if not any(_is_under(target, a) for a in allowed):
                return "[BLOCKED] Access denied — path is outside allowed directories."

            if _is_credential_file(target):
                return "[BLOCKED] Reading credential / secret files is not allowed."

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
