"""
Token counting endpoints using tiktoken (cl100k_base, GPT-4 compatible).

GET  /api/tokens/session/{id}   — count tokens for a session
POST /api/tokens/files          — batch token count for file paths (whitelisted only)
"""
import os
from pathlib import Path

import tiktoken
from fastapi import APIRouter, HTTPException, Request
from access_control import require_inspection_access
from hardening import is_secret_like_path
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


def _count_optional_text(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return _count(value)
    return _count(str(value))


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _get_configured_context_window_tokens() -> int | None:
    for env_var in ("MODEL_CONTEXT_WINDOW_TOKENS", "DEEPSEEK_CONTEXT_WINDOW_TOKENS"):
        raw_value = os.getenv(env_var)
        if not raw_value:
            continue
        try:
            parsed = int(raw_value)
        except ValueError:
            continue
        if parsed > 0:
            return parsed
    return None


def _count_tool_io_tokens(messages: list[dict]) -> int:
    token_total = 0
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            token_total += _count_optional_text(call.get("input"))
            token_total += _count_optional_text(call.get("output"))
    return token_total


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
    if is_secret_like_path(clean):
        return None
    # Resolve and confirm it stays inside base_dir
    target = (base / clean).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


@router.get("/tokens/session/{session_id}")
def session_tokens(session_id: str, request: Request = None):
    require_inspection_access(request)
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

    prompt_messages = agent_manager.session_manager.load_session_for_agent(session_id)  # type: ignore[union-attr]
    raw_messages = agent_manager.session_manager.load_session(session_id)  # type: ignore[union-attr]
    prompt_history_system_tokens = sum(
        _count_optional_text(message.get("content"))
        for message in prompt_messages
        if message.get("role") == "system"
    )
    user_tokens = sum(
        _count_optional_text(message.get("content"))
        for message in prompt_messages
        if message.get("role") == "user"
    )
    assistant_tokens = sum(
        _count_optional_text(message.get("content"))
        for message in prompt_messages
        if message.get("role") == "assistant"
    )
    message_tokens = prompt_history_system_tokens + user_tokens + assistant_tokens
    total_tokens = system_tokens + message_tokens
    tool_tokens = _count_tool_io_tokens(raw_messages)
    input_tokens = system_tokens + prompt_history_system_tokens + user_tokens
    output_tokens = assistant_tokens
    tracked_total_tokens = input_tokens + output_tokens + tool_tokens
    context_window_tokens = _get_configured_context_window_tokens()
    context_window_remaining_tokens = (
        max(context_window_tokens - total_tokens, 0)
        if context_window_tokens is not None
        else None
    )

    return {
        "session_id": session_id,
        "system_tokens": system_tokens,
        "message_tokens": message_tokens,
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_tokens": tool_tokens,
        "tracked_total_tokens": tracked_total_tokens,
        "context_window_tokens": context_window_tokens,
        "context_window_remaining_tokens": context_window_remaining_tokens,
        "model_name": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }


class FilesTokenRequest(BaseModel):
    paths: list[str]


@router.post("/tokens/files")
def files_tokens(body: FilesTokenRequest, request: Request = None):
    require_inspection_access(request)
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
