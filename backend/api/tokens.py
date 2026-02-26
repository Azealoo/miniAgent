"""
Token counting endpoints using tiktoken (cl100k_base, GPT-4 compatible).

GET  /api/tokens/session/{id}   — count tokens for a session
POST /api/tokens/files          — batch token count for file paths (whitelisted only)
"""
from pathlib import Path

import tiktoken
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_ENCODING = tiktoken.get_encoding("cl100k_base")

# Only these prefixes (relative to base_dir) may have their tokens counted.
# Mirrors the whitelist used by api/files.py to prevent reading arbitrary files.
_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_MAX_PATHS = 50


def _count(text: str) -> int:
    return len(_ENCODING.encode(text))


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _validate_token_path(rel_path: str, base: Path) -> Path | None:
    """
    Return the validated absolute path, or None if the path is disallowed.
    Applies the same whitelist and traversal checks as api/files.py._check_path.
    """
    clean = rel_path.strip().lstrip("/").removeprefix("./")
    if not clean:
        return None
    # Block traversal components
    if ".." in clean.split("/"):
        return None
    # Whitelist check
    allowed = any(clean.startswith(p) for p in _ALLOWED_PREFIXES) or (
        clean in _ALLOWED_ROOT_FILES
    )
    if not allowed:
        return None
    # Resolve and confirm it stays inside base_dir
    target = (base / clean).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


@router.get("/tokens/session/{session_id}")
def session_tokens(session_id: str):
    from graph.session_manager import _validate_session_id

    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    from graph.agent import agent_manager
    from graph.prompt_builder import build_system_prompt
    from config import get_rag_mode

    system_prompt = build_system_prompt(agent_manager.base_dir, get_rag_mode())  # type: ignore[arg-type]
    system_tokens = _count(system_prompt)

    messages = agent_manager.session_manager.load_session(session_id)  # type: ignore[union-attr]
    message_tokens = sum(
        _count(m.get("content", "")) for m in messages
    )

    return {
        "session_id": session_id,
        "system_tokens": system_tokens,
        "message_tokens": message_tokens,
        "total_tokens": system_tokens + message_tokens,
    }


class FilesTokenRequest(BaseModel):
    paths: list[str]


@router.post("/tokens/files")
def files_tokens(body: FilesTokenRequest):
    if len(body.paths) > _MAX_PATHS:
        raise HTTPException(400, f"Too many paths: max {_MAX_PATHS} per request.")
    base = _base_dir()
    results = []
    for rel_path in body.paths:
        abs_path = _validate_token_path(rel_path, base)
        if abs_path is None or not abs_path.exists() or not abs_path.is_file():
            tokens = 0
        else:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
            tokens = _count(text)
        results.append({"path": rel_path, "tokens": tokens})
    return results
