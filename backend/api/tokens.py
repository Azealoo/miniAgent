"""
Token counting endpoints with lazy exact tokenizer resolution and deterministic fallback.

GET  /api/tokens/session/{id}   - count tokens for a session
POST /api/tokens/files          - batch token count for file paths (whitelisted only)
"""

import importlib
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from access_control import require_inspection_access
from hardening import is_secret_like_path
from pydantic import BaseModel

router = APIRouter()

_TOKENIZER_BACKEND_EXACT = "tiktoken_cl100k_base"
_TOKENIZER_BACKEND_FALLBACK = "deterministic_fallback"
_TOKENIZER_ACCURACY_EXACT = "model_aligned"
_TOKENIZER_ACCURACY_FALLBACK = "approximate"

# Mirrors the file whitelist used by api/files.py so token counting cannot read
# arbitrary paths outside the supported BioAPEX workspace roots.
_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_MAX_PATHS = 50


@dataclass(frozen=True)
class _TokenizerRuntime:
    backend: str
    accuracy: str
    count_text: Callable[[str], int]


def _count_with_deterministic_fallback(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text.encode("utf-8")) / 4))


@lru_cache(maxsize=1)
def _get_tokenizer_runtime() -> _TokenizerRuntime:
    try:
        tiktoken = importlib.import_module("tiktoken")
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:
        return _TokenizerRuntime(
            backend=_TOKENIZER_BACKEND_FALLBACK,
            accuracy=_TOKENIZER_ACCURACY_FALLBACK,
            count_text=_count_with_deterministic_fallback,
        )

    def _count_with_exact_tokenizer(text: str) -> int:
        return len(encoding.encode(text))

    return _TokenizerRuntime(
        backend=_TOKENIZER_BACKEND_EXACT,
        accuracy=_TOKENIZER_ACCURACY_EXACT,
        count_text=_count_with_exact_tokenizer,
    )


def _count(text: str) -> int:
    runtime = _get_tokenizer_runtime()
    return runtime.count_text(text)


def _get_tokenizer_metadata() -> tuple[str, str]:
    runtime = _get_tokenizer_runtime()
    return runtime.backend, runtime.accuracy


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
    clean = rel_path.strip().lstrip("/").removeprefix("./")
    if not clean:
        return None
    if ".." in clean.split("/"):
        return None
    allowed = any(clean.startswith(prefix) for prefix in _ALLOWED_PREFIXES) or (
        clean in _ALLOWED_ROOT_FILES
    )
    if not allowed:
        return None
    if is_secret_like_path(clean):
        return None
    target = (base / clean).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def _get_model_name() -> str:
    from config import get_execution_backend_settings

    execution_backends = get_execution_backend_settings()
    llm = execution_backends.get("llm")
    if isinstance(llm, dict):
        roles = llm.get("roles")
        if isinstance(roles, dict):
            executor = roles.get("executor")
            if isinstance(executor, dict):
                model = executor.get("model")
                if isinstance(model, str) and model.strip():
                    return model
    return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


@router.get("/tokens/session/{session_id}")
def session_tokens(session_id: str, request: Request = None):
    require_inspection_access(request)
    from graph.session_manager import _validate_session_id

    try:
        _validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session_id") from exc

    from config import get_rag_mode
    from graph.agent import agent_manager
    from graph.prompt_builder import build_system_prompt

    tokenizer_backend, tokenizer_accuracy = _get_tokenizer_metadata()
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
        "model_name": _get_model_name(),
        "tokenizer_backend": tokenizer_backend,
        "tokenizer_accuracy": tokenizer_accuracy,
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
