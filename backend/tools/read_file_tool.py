"""
Sandboxed file reader. The agent can read files under root_dir or under
any path in extra_allowed_roots (for skills in .agents/skills or configurable dirs).
"""
import re
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .contracts import (
    artifact_ref,
    blocked_result,
    empty_result,
    invalid_input_result,
    success_result,
    truncate_text,
)

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
    response_format: str = "content_and_artifact"
    root_dir: str = ""
    extra_allowed_roots: list[str] = []

    def _run(self, path: str) -> tuple[str, dict]:
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
                return blocked_result(
                    self.name,
                    "Access denied — path is outside allowed directories.",
                    metadata={"requested_path": path, "resolved_path": str(target)},
                )

            if _is_credential_file(target):
                return blocked_result(
                    self.name,
                    "Reading credential / secret files is not allowed.",
                    metadata={"requested_path": path, "resolved_path": str(target)},
                )

            if not target.exists():
                return invalid_input_result(
                    self.name,
                    f"File not found: {path}",
                    metadata={"requested_path": path, "resolved_path": str(target)},
                )

            if not target.is_file():
                return invalid_input_result(
                    self.name,
                    f"Not a file: {path}",
                    metadata={"requested_path": path, "resolved_path": str(target)},
                )

            full_content = target.read_text(encoding="utf-8")
            content, truncated = truncate_text(
                full_content,
                _MAX_OUTPUT,
                marker="\n...[output truncated]",
            )
            structured_payload = {
                "path": path,
                "resolved_path": str(target),
                "content": content,
                "truncated": truncated,
                "character_count": len(full_content),
                "is_absolute_input": Path(path_str).is_absolute(),
            }
            warnings = ["output_truncated"] if truncated else []
            refs = [artifact_ref(path=str(target), label="read_file_target")]

            if not full_content:
                return empty_result(
                    self.name,
                    "(empty file)",
                    structured_payload=structured_payload,
                    artifact_refs=refs,
                    warnings=warnings,
                    metadata={"requested_path": path},
                )

            return success_result(
                self.name,
                content,
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings,
                metadata={"requested_path": path},
            )

        except Exception as exc:
            return invalid_input_result(
                self.name,
                str(exc),
                metadata={"requested_path": path},
            )

    async def _arun(self, path: str) -> tuple[str, dict]:  # type: ignore[override]
        return self._run(path)
