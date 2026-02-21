"""
Token counting endpoints using tiktoken (cl100k_base, GPT-4 compatible).

GET  /api/tokens/session/{id}   — count tokens for a session
POST /api/tokens/files          — batch token count for file paths
"""
from pathlib import Path

import tiktoken
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count(text: str) -> int:
    return len(_ENCODING.encode(text))


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


@router.get("/tokens/session/{session_id}")
def session_tokens(session_id: str):
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
    base = _base_dir()
    results = []
    for rel_path in body.paths:
        abs_path = base / rel_path.lstrip("/")
        if abs_path.exists() and abs_path.is_file():
            text = abs_path.read_text(encoding="utf-8", errors="replace")
            tokens = _count(text)
        else:
            tokens = 0
        results.append({"path": rel_path, "tokens": tokens})
    return results
