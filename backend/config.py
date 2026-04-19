import os
from pathlib import Path
from typing import Any

from hardening import (
    DEFAULT_POSTURE,
    VALID_POSTURES,
    ProductionHardeningPolicy,
)
from runtime_config import load_runtime_config
from runtime_config_types import LoadedRuntimeConfig

_CONFIG_FILE = Path(__file__).parent / "config.json"
_DEFAULT_MEMORY_STALE_DAYS = 30
_DEFAULT_MAX_TOKENS_PER_TURN = 200_000
_DEFAULT_LLM_OUTPUT_TOKEN_CAP = 8_000
_DEFAULT_LLM_OUTPUT_TOKEN_CAP_ESCALATED = 65_536

# Per-section character budgets used by graph.prompt_builder. Each value is the
# upper bound for one assembled section; the prompt builder truncates a section
# in place once it exceeds its cap (with a visible truncation marker). The
# optional ``total_max_chars`` (0 = disabled) is a global ceiling that, when
# set, triggers section eviction in the documented priority order.
_DEFAULT_PROMPT_BUDGET: dict = {
    "component_max_chars": 20_000,
    "project_instruction_file_max_chars": 2_000,
    "project_instruction_total_max_chars": 8_000,
    "git_context_max_chars": 2_000,
    "retrieved_memory_block_max_chars": 1_600,
    "retrieved_memory_item_max_chars": 280,
    "scoped_memory_block_max_chars": 4_000,
    "memory_index_max_chars": 2_048,
    "total_max_chars": 0,
}

_DEFAULT: dict = {
    "rag_mode": False,
    "deterministic_seed": None,
    "max_tokens_per_turn": _DEFAULT_MAX_TOKENS_PER_TURN,
    "production_hardening": {"posture": DEFAULT_POSTURE},
    "prompt_context": {
        "include_git_context": False,
        "memory_stale_days": _DEFAULT_MEMORY_STALE_DAYS,
    },
    "prompt_budget": dict(_DEFAULT_PROMPT_BUDGET),
    "agent_runtime": {
        "executor_recursion_limit": 1000,
        "helper_agent_recursion_limit": 1000,
    },
    "verification": {
        "retry_on_repair_required": True,
    },
    "llm_output_token_cap": {
        "default": _DEFAULT_LLM_OUTPUT_TOKEN_CAP,
        "escalated": _DEFAULT_LLM_OUTPUT_TOKEN_CAP_ESCALATED,
    },
    "tool_policy": {
        "enabled": True,
        "allow_without_context": True,
        "warn_on_missing_artifact_refs": True,
    },
    "access_defaults": {
        "allow_loopback_without_auth": True,
    },
    "execution_backends": {
        "llm": {
            "provider": "deepseek",
            "roles": {
                "executor": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "temperature": 0.3,
                    "streaming": True,
                },
                "planner": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "temperature": 0.2,
                    "streaming": True,
                },
                "verifier": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "temperature": 0.2,
                    "streaming": True,
                },
                "title": {
                    "provider": "openai",
                    "model": "gpt-5-mini",
                    "temperature": 0.2,
                    "streaming": False,
                },
            },
        }
    },
    "skills": {
        "extra_dirs": [],
        "entries": {},
    },
    "read_file_extra_roots": [],
}


def _load_loaded_runtime() -> LoadedRuntimeConfig:
    return load_runtime_config(
        default_config=_DEFAULT,
        project_config_path=_CONFIG_FILE,
    )


def _load_runtime() -> dict:
    return _load_loaded_runtime().data


def get_loaded_runtime_config() -> LoadedRuntimeConfig:
    """Return the merged runtime config together with per-layer provenance."""
    return _load_loaded_runtime()

def get_prompt_context_settings() -> dict[str, Any]:
    prompt_context = _load_runtime().get("prompt_context", {})
    return dict(prompt_context) if isinstance(prompt_context, dict) else {}


def get_memory_stale_days() -> int:
    """Return the staleness threshold in days for scoped memory entries.

    Resolution order: BIOAPEX_PROMPT_MEMORY_STALE_DAYS env var, runtime
    `prompt_context.memory_stale_days`, then the built-in default.
    """
    env_override = os.getenv("BIOAPEX_PROMPT_MEMORY_STALE_DAYS", "").strip()
    if env_override:
        try:
            return max(0, int(env_override))
        except ValueError:
            pass
    raw = get_prompt_context_settings().get("memory_stale_days", _DEFAULT_MEMORY_STALE_DAYS)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_MEMORY_STALE_DAYS


def get_prompt_budget() -> dict[str, int]:
    """Return per-section prompt char budgets (graph.prompt_builder).

    Resolution order: runtime ``prompt_budget.<field>``, then the built-in
    default. Invalid values fall back silently to the default for that field.
    Negative values are clamped to 0. Behavior is unchanged when the
    ``prompt_budget`` block is absent from the config.
    """
    raw = _load_runtime().get("prompt_budget", {})
    if not isinstance(raw, dict):
        raw = {}
    resolved: dict[str, int] = {}
    for field, default in _DEFAULT_PROMPT_BUDGET.items():
        value = raw.get(field, default)
        try:
            resolved[field] = max(0, int(value))
        except (TypeError, ValueError):
            resolved[field] = int(default)
    return resolved


def get_agent_runtime_settings() -> dict[str, Any]:
    agent_runtime = _load_runtime().get("agent_runtime", {})
    return dict(agent_runtime) if isinstance(agent_runtime, dict) else {}


def get_agent_runtime_limit(limit_name: str, default: int) -> int:
    agent_runtime = get_agent_runtime_settings()
    raw_limit = agent_runtime.get(limit_name, default)
    try:
        resolved_limit = int(raw_limit)
    except (TypeError, ValueError):
        resolved_limit = default
    return max(25, resolved_limit)


def get_verification_settings() -> dict[str, Any]:
    verification = _load_runtime().get("verification", {})
    return dict(verification) if isinstance(verification, dict) else {}


def get_tool_policy_settings() -> dict[str, Any]:
    tool_policy = _load_runtime().get("tool_policy", {})
    return dict(tool_policy) if isinstance(tool_policy, dict) else {}


def get_access_defaults() -> dict[str, Any]:
    access_defaults = _load_runtime().get("access_defaults", {})
    return dict(access_defaults) if isinstance(access_defaults, dict) else {}


def get_execution_backend_settings() -> dict[str, Any]:
    execution_backends = _load_runtime().get("execution_backends", {})
    return dict(execution_backends) if isinstance(execution_backends, dict) else {}

def get_rag_mode() -> bool:
    return _load_runtime().get("rag_mode", False)


def get_llm_output_token_caps() -> tuple[int, int]:
    """Return (default, escalated) per-request output token caps.

    0 or negative values disable the cap (pass no ``max_tokens`` through).
    The escalated cap is the upper bound used after a single
    ``finish_reason="length"`` retry in ``invoke_with_escalation``.
    """
    raw = _load_runtime().get("llm_output_token_cap", {})
    if not isinstance(raw, dict):
        raw = {}

    def _resolve(key: str, default: int) -> int:
        value = raw.get(key, default)
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return default
        return max(0, resolved)

    return (
        _resolve("default", _DEFAULT_LLM_OUTPUT_TOKEN_CAP),
        _resolve("escalated", _DEFAULT_LLM_OUTPUT_TOKEN_CAP_ESCALATED),
    )


def get_max_tokens_per_turn() -> int:
    """Return the per-turn token budget. 0 or negative disables the cap."""
    raw = _load_runtime().get("max_tokens_per_turn", _DEFAULT_MAX_TOKENS_PER_TURN)
    try:
        resolved = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_TOKENS_PER_TURN
    return max(0, resolved)


def get_deterministic_seed() -> int | None:
    """Return the configured deterministic seed, or None when disabled."""
    raw = _load_runtime().get("deterministic_seed")
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def get_skills_extra_dirs(base_dir: Path) -> list[Path]:
    """Return list of extra skill directories (absolute paths)."""
    cfg = _load_runtime()
    extra = cfg.get("skills", {}).get("extra_dirs", [])
    result = []
    for p in extra:
        path = Path(p).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if path.exists():
            result.append(path)
    return result


def get_skill_enabled(skill_name: str) -> bool:
    """Return True if skill is enabled. Missing entry means enabled."""
    cfg = _load_runtime()
    entries = cfg.get("skills", {}).get("entries", {})
    if skill_name not in entries:
        return True
    return bool(entries[skill_name].get("enabled", True))


def get_read_file_extra_roots(base_dir: Path) -> list[Path]:
    """Return list of additional allowed roots for read_file (absolute paths)."""
    cfg = _load_runtime()
    raw = cfg.get("read_file_extra_roots", [])
    result = []
    for p in raw:
        path = Path(p).expanduser().resolve()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if path.exists():
            result.append(path)
    # Allow repo root .agents/skills by default
    repo_root = base_dir.parent
    agents_skills = repo_root / ".agents" / "skills"
    if agents_skills.exists() and repo_root not in result:
        result.append(repo_root)
    return result


def get_production_hardening_policy() -> ProductionHardeningPolicy:
    cfg = _load_runtime()
    raw = cfg.get("production_hardening", {})
    if not isinstance(raw, dict):
        return ProductionHardeningPolicy.fail_closed()
    posture = raw.get("posture", DEFAULT_POSTURE)
    if posture not in VALID_POSTURES:
        return ProductionHardeningPolicy.fail_closed()
    overrides = {k: v for k, v in raw.items() if k != "posture"}
    try:
        return ProductionHardeningPolicy.from_posture(posture, overrides=overrides)
    except Exception:
        return ProductionHardeningPolicy.fail_closed()
