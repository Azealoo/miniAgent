"""
Safe allowlisted file writer. The agent can only write under memory/, skills/, and knowledge/.
Path traversal is blocked. Used to update MEMORY.md, create/edit skills, or cache to knowledge.
"""
from pathlib import Path
from typing import Type

from audit.store import append_file_written_event
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .contracts import (
    artifact_ref,
    blocked_result,
    execution_error_result,
    invalid_input_result,
    success_result,
)

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
    response_format: str = "content_and_artifact"
    root_dir: str = ""

    def _run(self, path: str, content: str) -> tuple[str, dict]:
        try:
            root = Path(self.root_dir).resolve()
            path_clean = path.strip().lstrip("/").removeprefix("./")
            byte_count = len(content.encode("utf-8"))

            def _audit(outcome: str, *, reason: str | None = None, path_value: str | None = None) -> None:
                append_file_written_event(
                    root,
                    path=path_value or path_clean or path,
                    source="write_file_tool",
                    outcome=outcome,
                    byte_count=byte_count,
                    tool_name=self.name,
                    reason=reason,
                )

            if ".." in path_clean.split("/"):
                _audit("blocked", reason="Path traversal (..) is not allowed.")
                return blocked_result(
                    self.name,
                    "Path traversal (..) is not allowed.",
                    metadata={"requested_path": path, "sanitized_path": path_clean},
                )

            if not any(path_clean.startswith(p) for p in _ALLOWED_PREFIXES):
                _audit(
                    "blocked",
                    reason=(
                        f"Path must be under one of: {list(_ALLOWED_PREFIXES)}. "
                        f"Got: {path_clean!r}"
                    ),
                )
                return blocked_result(
                    self.name,
                    (
                        f"Path must be under one of: {list(_ALLOWED_PREFIXES)}. "
                        f"Got: {path_clean!r}"
                    ),
                    metadata={"requested_path": path, "sanitized_path": path_clean},
                )

            target = (root / path_clean).resolve()
            # Use relative_to() instead of startswith() to avoid prefix attacks
            # e.g. /project/backend_evil would falsely pass startswith(/project/backend)
            try:
                target.relative_to(root)
            except ValueError:
                _audit(
                    "blocked",
                    reason="Resolved path is outside the project directory.",
                    path_value=str(target),
                )
                return blocked_result(
                    self.name,
                    "Resolved path is outside the project directory.",
                    metadata={"requested_path": path, "resolved_path": str(target)},
                )

            if len(content) > _MAX_CONTENT:
                _audit(
                    "invalid_input",
                    reason=f"Content exceeds maximum length ({_MAX_CONTENT} characters).",
                )
                return invalid_input_result(
                    self.name,
                    f"Content exceeds maximum length ({_MAX_CONTENT} characters).",
                    metadata={"requested_path": path, "character_count": len(content)},
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            memory_index_rebuilt = False
            skills_rescanned = False

            if path_clean == "memory/MEMORY.md":
                # Rebuild memory vector index so RAG retrieval sees the new content.
                try:
                    from graph.agent import agent_manager
                    if agent_manager.memory_indexer:
                        agent_manager.memory_indexer.rebuild_index()
                        memory_index_rebuilt = True
                except Exception:
                    pass

            if path_clean.startswith("skills/"):
                # Rescan skills so SKILLS_SNAPSHOT.md is updated immediately and
                # the agent sees the new skill in its system prompt on the next turn.
                try:
                    from tools.skills_scanner import scan_skills
                    from graph.agent import agent_manager
                    if agent_manager.base_dir:
                        scan_skills(agent_manager.base_dir)
                        skills_rescanned = True
                except Exception:
                    pass

            _audit("written")
            return success_result(
                self.name,
                f"Wrote {path_clean} ({len(content)} characters).",
                structured_payload={
                    "path": path_clean,
                    "resolved_path": str(target),
                    "character_count": len(content),
                    "byte_count": len(content.encode("utf-8")),
                    "memory_index_rebuilt": memory_index_rebuilt,
                    "skills_rescanned": skills_rescanned,
                },
                artifact_refs=[artifact_ref(path=str(target), label="written_file")],
                metadata={"requested_path": path},
            )
        except Exception as exc:
            append_file_written_event(
                Path(self.root_dir).resolve(),
                path=path,
                source="write_file_tool",
                outcome="execution_failure",
                byte_count=len(content.encode("utf-8")),
                tool_name=self.name,
                reason=str(exc),
            )
            return execution_error_result(
                self.name,
                str(exc),
                metadata={"requested_path": path},
            )

    async def _arun(self, path: str, content: str) -> tuple[str, dict]:  # type: ignore[override]
        return self._run(path, content)
