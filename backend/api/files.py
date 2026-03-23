"""
File read/write endpoints with path whitelist protection.

GET  /api/files?path=<relative>   — read file content, including artifacts/
GET  /api/files/raw?path=<relative> — read raw file content for whitelisted files
POST /api/files                   — save file (Monaco editor)
GET  /api/skills                  — list available skills
"""
import json
import mimetypes
from pathlib import Path

from access_control import require_execution_access, require_inspection_access
import config as cfg
from audit.store import append_file_written_event
from artifacts.public_urls import public_raw_file_url
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from hardening import is_secret_like_path
from pydantic import BaseModel

router = APIRouter()

# Paths the API is allowed to serve (relative to base_dir)
_READ_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/", "artifacts/")
_WRITE_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_MAX_SAVE_BYTES = 500_000  # 500 KB limit for writes via the editor API
_REFERENCE_SCHEMA_PREFIX = "artifacts/reference_schemas/"


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _check_path(relative_path: str, *, write: bool = False) -> tuple[Path, str]:
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
    allowed_prefixes = _WRITE_ALLOWED_PREFIXES if write else _READ_ALLOWED_PREFIXES
    allowed = any(clean.startswith(p) for p in allowed_prefixes) or (
        clean in _ALLOWED_ROOT_FILES
    )
    if not allowed:
        mode = "write" if write else "read"
        raise HTTPException(
            403,
            f"Access denied for {mode}. Allowed: {list(allowed_prefixes)} + {list(_ALLOWED_ROOT_FILES)}",
        )

    if is_secret_like_path(clean):
        raise HTTPException(403, "Credential / secret files are not accessible via this API.")

    return target, clean


def _guess_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain; charset=utf-8"


def _read_raw_content(target: Path, clean_path: str) -> str:
    content = target.read_text(encoding="utf-8")
    if not clean_path.startswith(_REFERENCE_SCHEMA_PREFIX) or target.suffix.lower() != ".json":
        return content

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(payload, dict):
        return content

    payload["$id"] = public_raw_file_url(clean_path)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# ------------------------------------------------------------------ #
# Read                                                                 #
# ------------------------------------------------------------------ #


@router.get("/files")
def read_file(path: str = Query(..., description="Relative file path"), request: Request = None):
    require_inspection_access(request)
    target, _ = _check_path(path, write=False)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    content = target.read_text(encoding="utf-8")
    return {"path": path, "content": content}


@router.get("/files/raw")
def read_raw_file(path: str = Query(..., description="Relative file path"), request: Request = None):
    require_inspection_access(request)
    target, clean = _check_path(path, write=False)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    media_type = _guess_media_type(target)

    if clean.startswith(_REFERENCE_SCHEMA_PREFIX) and target.suffix.lower() == ".json":
        return Response(
            content=_read_raw_content(target, clean).encode("utf-8"),
            media_type=media_type,
        )

    return Response(content=target.read_bytes(), media_type=media_type)


# ------------------------------------------------------------------ #
# Write                                                                #
# ------------------------------------------------------------------ #


class SaveRequest(BaseModel):
    path: str
    content: str


@router.post("/files")
def save_file(body: SaveRequest, request: Request = None):
    require_execution_access(request)
    base_dir = _base_dir()
    byte_count = len(body.content.encode("utf-8"))
    policy = cfg.get_production_hardening_policy()
    if not policy.api.files_write_enabled:
        append_file_written_event(
            base_dir,
            path=body.path,
            source="api.files",
            outcome="blocked",
            byte_count=byte_count,
            reason="File editor writes disabled by production hardening policy.",
        )
        raise HTTPException(403, "File editor writes are disabled by production hardening policy.")

    if byte_count > _MAX_SAVE_BYTES:
        append_file_written_event(
            base_dir,
            path=body.path,
            source="api.files",
            outcome="invalid_input",
            byte_count=byte_count,
            reason=f"Content too large: max {_MAX_SAVE_BYTES // 1000} KB.",
        )
        raise HTTPException(
            400, f"Content too large: max {_MAX_SAVE_BYTES // 1000} KB."
        )

    try:
        target, clean = _check_path(body.path, write=True)
    except HTTPException as exc:
        append_file_written_event(
            base_dir,
            path=body.path,
            source="api.files",
            outcome="blocked" if exc.status_code == 403 else "invalid_input",
            byte_count=byte_count,
            reason=str(exc.detail),
        )
        raise

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
    except Exception as exc:
        append_file_written_event(
            base_dir,
            path=clean,
            source="api.files",
            outcome="execution_failure",
            byte_count=byte_count,
            reason=str(exc),
        )
        raise

    # Rebuild memory index if MEMORY.md was updated.
    # Compare against the *normalized* path to handle ./memory/MEMORY.md, etc.
    if clean == "memory/MEMORY.md":
        try:
            from graph.agent import agent_manager

            if agent_manager.memory_indexer:
                agent_manager.memory_indexer.rebuild_index()
        except Exception:
            pass

    append_file_written_event(
        base_dir,
        path=clean,
        source="api.files",
        outcome="written",
        byte_count=byte_count,
    )
    return {"path": body.path, "saved": True}


# ------------------------------------------------------------------ #
# Skills list                                                          #
# ------------------------------------------------------------------ #


@router.get("/skills")
def list_skills(request: Request = None):
    require_inspection_access(request)
    base = _base_dir()
    from tools.skills_scanner import collect_skill_entries

    skills = []
    for entry in collect_skill_entries(base, respect_enabled=False):
        skills.append(
            {
                "name": entry["name"],
                "path": entry["location"].removeprefix("./"),
                "category": entry.get("category", ""),
                "stage": entry.get("stage", ""),
            }
        )
    return skills
