"""
File read/write endpoints with path whitelist protection.

GET  /api/files?path=<relative>   — read file content
POST /api/files                   — save file (Monaco editor)
GET  /api/skills                  — list available skills
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

# Paths the API is allowed to serve (relative to base_dir)
_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_MAX_SAVE_BYTES = 500_000  # 500 KB limit for writes via the editor API


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _check_path(relative_path: str) -> tuple[Path, str]:
    """Validate path against whitelist.

    Returns (resolved_absolute_path, normalized_relative_path).
    Raises HTTPException on any violation.
    """
    # Strip leading slash or ./
    clean = relative_path.strip().lstrip("/").removeprefix("./")

    # Traversal guard (before whitelist check)
    if ".." in clean.split("/"):
        raise HTTPException(403, "Path traversal is not allowed.")

    base = _base_dir()
    target = (base / clean).resolve()

    # Use relative_to() instead of startswith() to prevent prefix-name attacks:
    # e.g. /project/backend_evil would falsely pass startswith(/project/backend)
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(403, "Path is outside the project directory.")

    # Whitelist check
    allowed = any(clean.startswith(p) for p in _ALLOWED_PREFIXES) or (
        clean in _ALLOWED_ROOT_FILES
    )
    if not allowed:
        raise HTTPException(
            403,
            f"Access denied. Allowed: {list(_ALLOWED_PREFIXES)} + {list(_ALLOWED_ROOT_FILES)}",
        )

    return target, clean


# ------------------------------------------------------------------ #
# Read                                                                 #
# ------------------------------------------------------------------ #


@router.get("/files")
def read_file(path: str = Query(..., description="Relative file path")):
    target, _ = _check_path(path)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    content = target.read_text(encoding="utf-8")
    return {"path": path, "content": content}


# ------------------------------------------------------------------ #
# Write                                                                #
# ------------------------------------------------------------------ #


class SaveRequest(BaseModel):
    path: str
    content: str


@router.post("/files")
def save_file(body: SaveRequest):
    if len(body.content.encode("utf-8")) > _MAX_SAVE_BYTES:
        raise HTTPException(
            400, f"Content too large: max {_MAX_SAVE_BYTES // 1000} KB."
        )

    target, clean = _check_path(body.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")

    # Rebuild memory index if MEMORY.md was updated.
    # Compare against the *normalized* path to handle ./memory/MEMORY.md, etc.
    if clean == "memory/MEMORY.md":
        try:
            from graph.agent import agent_manager

            if agent_manager.memory_indexer:
                agent_manager.memory_indexer.rebuild_index()
        except Exception:
            pass

    return {"path": body.path, "saved": True}


# ------------------------------------------------------------------ #
# Skills list                                                          #
# ------------------------------------------------------------------ #


@router.get("/skills")
def list_skills():
    base = _base_dir()
    skills_dir = base / "skills"
    skills = []
    if skills_dir.exists():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            relative = str(skill_md.relative_to(base))
            skills.append(
                {
                    "name": skill_md.parent.name,
                    "path": relative,
                }
            )
    return skills
