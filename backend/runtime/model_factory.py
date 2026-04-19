from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import config
from langchain_core.messages import BaseMessage
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

_logger = logging.getLogger(__name__)

ModelRole = Literal["executor", "planner", "verifier", "title"]
ModelProvider = Literal["deepseek", "openai"]


@dataclass(frozen=True)
class RoleModelConfig:
    role: ModelRole
    provider: ModelProvider
    model: str
    api_key: str
    base_url: str
    temperature: float
    streaming: bool
    seed: int | None = None
    max_tokens: int = 0
    escalated_max_tokens: int = 0


_ROLE_DEFAULTS: dict[ModelRole, dict[str, object]] = {
    "executor": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.3,
        "streaming": True,
    },
    "planner": {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.2,
        "streaming": True,
    },
    "verifier": {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.2,
        "streaming": True,
    },
    "title": {
        "provider": "openai",
        "model": "gpt-5-mini",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.2,
        "streaming": False,
    },
}


def _role_env_prefix(role: ModelRole) -> str:
    return f"BIOAPEX_{role.upper()}"


def _resolve_provider(raw: object, *, fallback: ModelProvider) -> ModelProvider:
    if not isinstance(raw, str):
        return fallback
    normalized = raw.strip().lower()
    if normalized in {"openai", "chatgpt"}:
        return "openai"
    if normalized == "deepseek":
        return "deepseek"
    return fallback


def _resolve_temperature(raw: object, *, fallback: float) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return fallback
    return fallback


def _resolve_streaming(raw: object, *, fallback: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return fallback


def get_role_model_config(role: ModelRole, *, streaming: bool | None = None) -> RoleModelConfig:
    defaults = _ROLE_DEFAULTS[role]
    execution_settings = config.get_execution_backend_settings()
    llm_settings = execution_settings.get("llm", {})
    if not isinstance(llm_settings, dict):
        llm_settings = {}

    roles = llm_settings.get("roles", {})
    if not isinstance(roles, dict):
        roles = {}
    role_settings = roles.get(role, {})
    if not isinstance(role_settings, dict):
        role_settings = {}

    fallback_provider = _resolve_provider(
        llm_settings.get("provider"),
        fallback=defaults["provider"],  # type: ignore[arg-type]
    )
    provider = _resolve_provider(
        os.getenv(f"{_role_env_prefix(role)}_PROVIDER") or role_settings.get("provider"),
        fallback=fallback_provider,
    )

    fallback_model = role_settings.get("model")
    if not isinstance(fallback_model, str) or not fallback_model.strip():
        fallback_model = llm_settings.get("model")
    if not isinstance(fallback_model, str) or not fallback_model.strip():
        fallback_model = defaults["model"]

    model = (
        os.getenv(f"{_role_env_prefix(role)}_MODEL")
        or (
            os.getenv("DEEPSEEK_MODEL")
            if provider == "deepseek" and role == "executor"
            else os.getenv("OPENAI_MODEL")
            if provider == "openai"
            else None
        )
        or fallback_model
    )
    assert isinstance(model, str)

    default_base_url = defaults["base_url"]
    base_url = (
        os.getenv(f"{_role_env_prefix(role)}_BASE_URL")
        or role_settings.get("base_url")
        or (
            os.getenv("DEEPSEEK_BASE_URL")
            if provider == "deepseek"
            else os.getenv("OPENAI_BASE_URL")
        )
        or default_base_url
    )
    assert isinstance(base_url, str)

    api_key = (
        os.getenv(f"{_role_env_prefix(role)}_API_KEY")
        or (
            os.getenv("DEEPSEEK_API_KEY")
            if provider == "deepseek"
            else os.getenv("OPENAI_API_KEY")
        )
        or ""
    )

    temperature = _resolve_temperature(
        os.getenv(f"{_role_env_prefix(role)}_TEMPERATURE") or role_settings.get("temperature"),
        fallback=float(defaults["temperature"]),
    )
    resolved_streaming = (
        streaming
        if streaming is not None
        else _resolve_streaming(
            os.getenv(f"{_role_env_prefix(role)}_STREAMING") or role_settings.get("streaming"),
            fallback=bool(defaults["streaming"]),
        )
    )

    seed = config.get_deterministic_seed()
    if seed is not None:
        # Deterministic mode pins temperature to 0 regardless of per-role setting.
        temperature = 0.0

    default_cap, escalated_cap = config.get_llm_output_token_caps()

    return RoleModelConfig(
        role=role,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        streaming=resolved_streaming,
        seed=seed,
        max_tokens=default_cap,
        escalated_max_tokens=escalated_cap,
    )


def role_model_is_configured(role: ModelRole) -> bool:
    return bool(get_role_model_config(role).api_key.strip())


def build_chat_model(
    role: ModelRole,
    *,
    streaming: bool | None = None,
    max_tokens_override: int | None = None,
):
    settings = get_role_model_config(role, streaming=streaming)
    kwargs: dict[str, object] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "temperature": settings.temperature,
        "streaming": settings.streaming,
    }
    if settings.seed is not None:
        kwargs["seed"] = settings.seed
    resolved_cap = (
        max_tokens_override
        if max_tokens_override is not None
        else settings.max_tokens
    )
    if resolved_cap and resolved_cap > 0:
        kwargs["max_tokens"] = int(resolved_cap)
    if settings.provider == "deepseek":
        return ChatDeepSeek(**kwargs)
    if settings.provider == "openai":
        return ChatOpenAI(**kwargs)
    raise ValueError(f"Unsupported provider for role {role!r}: {settings.provider!r}")


_CAP_STOP_REASONS: frozenset[str] = frozenset({"length", "max_tokens"})


def _extract_stop_reason(response: Any) -> str | None:
    """Pull the normalized cap signal out of a LangChain chat-model response.

    LangChain stores provider-specific finish reasons under
    ``response_metadata['finish_reason']`` for OpenAI/DeepSeek and
    ``response_metadata['stop_reason']`` for Anthropic. We inspect both so
    the escalation logic works uniformly if the provider ever changes.
    """
    metadata = getattr(response, "response_metadata", None)
    if not isinstance(metadata, dict):
        return None
    for key in ("finish_reason", "stop_reason"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _response_hit_cap(response: Any) -> bool:
    return _extract_stop_reason(response) in _CAP_STOP_REASONS


async def invoke_with_escalation(
    role: ModelRole,
    messages: Sequence[BaseMessage],
    *,
    model: Any | None = None,
    base_dir: Path | str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    streaming: bool | None = False,
) -> Any:
    """Invoke a role's chat model with the default output-token cap and
    escalate once to the larger cap when the provider reports the response
    was truncated at the cap.

    Each escalation (successful retry, retry failure, or still-capped result)
    is recorded to the audit log via ``append_llm_escalation_event`` when
    ``base_dir`` is provided. Non-streaming ``ainvoke`` is used so the caller
    receives a single materialised ``AIMessage`` whose ``response_metadata``
    can be inspected — streaming callsites need a different strategy.

    ``model`` may be a pre-built chat model (e.g. the instance the
    ``AgentManager`` already holds). The retry always rebuilds through
    ``build_chat_model`` so the escalated cap reaches the provider kwargs.
    """
    settings = get_role_model_config(role, streaming=streaming)
    default_cap = settings.max_tokens
    escalated_cap = settings.escalated_max_tokens

    if model is None:
        model = build_chat_model(role, streaming=streaming)
    response = await model.ainvoke(list(messages))

    if (
        default_cap <= 0
        or escalated_cap <= default_cap
        or not _response_hit_cap(response)
    ):
        return response

    stop_reason = _extract_stop_reason(response)
    _logger.info(
        "llm output-token cap hit for role=%s model=%s (stop_reason=%s); "
        "escalating %d -> %d",
        role,
        settings.model,
        stop_reason,
        default_cap,
        escalated_cap,
    )

    escalated_model = build_chat_model(
        role,
        streaming=streaming,
        max_tokens_override=escalated_cap,
    )

    retry_error: str | None = None
    retry_response: Any = None
    try:
        retry_response = await escalated_model.ainvoke(list(messages))
    except Exception as exc:  # noqa: BLE001 — classify at the boundary
        retry_error = str(exc)

    if retry_error is not None:
        outcome = "retry_failed"
    elif _response_hit_cap(retry_response):
        outcome = "still_capped"
    else:
        outcome = "retried"

    if base_dir is not None:
        from audit.store import append_llm_escalation_event

        append_llm_escalation_event(
            base_dir,
            role=role,
            provider=settings.provider,
            model=settings.model,
            default_max_tokens=default_cap,
            escalated_max_tokens=escalated_cap,
            outcome=outcome,
            session_id=session_id,
            run_id=run_id,
            stop_reason=stop_reason,
            error=retry_error,
        )

    if retry_error is not None:
        return response
    return retry_response
