from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import config
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

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
    fallback_model: str | None = None


_ROLE_DEFAULTS: dict[ModelRole, dict[str, object]] = {
    "executor": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.3,
        "streaming": True,
        "fallback_model": None,
    },
    "planner": {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.2,
        "streaming": True,
        "fallback_model": None,
    },
    "verifier": {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.2,
        "streaming": True,
        "fallback_model": None,
    },
    "title": {
        "provider": "openai",
        "model": "gpt-5-mini",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.2,
        "streaming": False,
        "fallback_model": None,
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

    fallback_model_setting = (
        os.getenv(f"{_role_env_prefix(role)}_FALLBACK_MODEL")
        or role_settings.get("fallback_model")
        or llm_settings.get("fallback_model")
        or defaults.get("fallback_model")
    )
    if isinstance(fallback_model_setting, str):
        fallback_model_setting = fallback_model_setting.strip() or None
    elif fallback_model_setting is not None:
        fallback_model_setting = None

    return RoleModelConfig(
        role=role,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        streaming=resolved_streaming,
        seed=seed,
        fallback_model=fallback_model_setting,
    )


def role_model_is_configured(role: ModelRole) -> bool:
    return bool(get_role_model_config(role).api_key.strip())


def _instantiate_chat_model(settings: RoleModelConfig, *, model_override: str | None = None):
    kwargs: dict[str, object] = {
        "model": model_override or settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "temperature": settings.temperature,
        "streaming": settings.streaming,
    }
    if settings.seed is not None:
        kwargs["seed"] = settings.seed
    if settings.provider == "deepseek":
        return ChatDeepSeek(**kwargs)
    if settings.provider == "openai":
        return ChatOpenAI(**kwargs)
    raise ValueError(
        f"Unsupported provider for role {settings.role!r}: {settings.provider!r}"
    )


def build_chat_model(role: ModelRole, *, streaming: bool | None = None):
    settings = get_role_model_config(role, streaming=streaming)
    return _instantiate_chat_model(settings)


def build_fallback_chat_model(role: ModelRole, *, streaming: bool | None = None):
    """Return a chat model client built with the role's ``fallback_model``.

    Returns ``None`` when the role has no ``fallback_model`` configured —
    callers should treat this as "no fallback available" and re-raise the
    original overload/timeout exception.
    """
    settings = get_role_model_config(role, streaming=streaming)
    if not settings.fallback_model:
        return None
    return _instantiate_chat_model(settings, model_override=settings.fallback_model)
