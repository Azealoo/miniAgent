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


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _check_path(relative_path: str) -> Path:
    """Validate path against whitelist and return the resolved absolute path."""
    # Strip leading slash or ./
    clean = relative_path.lstrip("/").removeprefix("./")

    # Traversal guard (before whitelist check)
    if ".." in clean.split("/"):
        raise HTTPException(403, "Path traversal is not allowed.")

    base = _base_dir()
    target = (base / clean).resolve()

    # Make sure it's still inside base_dir
    if not str(target).startswith(str(base.resolve())):
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

    return target


# ------------------------------------------------------------------ #
# Read                                                                 #
# ------------------------------------------------------------------ #


@router.get("/files")
def read_file(path: str = Query(..., description="Relative file path")):
    target = _check_path(path)
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
    target = _check_path(body.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")

    # Rebuild memory index if MEMORY.md was updated
    if body.path.rstrip("/") in ("memory/MEMORY.md", "./memory/MEMORY.md"):
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
