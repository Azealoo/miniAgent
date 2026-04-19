import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hardening import (
    DEFAULT_POSTURE,
    VALID_POSTURES,
    ProductionHardeningPolicy,
)
from runtime_config import load_runtime_config, resolve_runtime_config_paths
from runtime_config_types import LoadedRuntimeConfig, validate_runtime_config

_CONFIG_FILE = Path(__file__).parent / "config.json"

# Env var that lets dev machines opt back into live config reloads. When set to
# "1", writes to tracked runtime config files are permitted; otherwise a turn
# treats ``backend/config.json`` + env overrides as frozen.
ALLOW_CONFIG_RELOAD_ENV_VAR = "BIOAPEX_ALLOW_CONFIG_RELOAD"
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

_DEFAULT_LLM_PROBE_MIN_FILES = 10
_DEFAULT_LLM_PROBE_MAX_CHARS = 8_000

# Wall-clock budgets. ``max_turn_wallclock_s`` caps how long a single turn may
# run before the runtime raises ``asyncio.TimeoutError`` at the turn loop.
# ``tool_wallclock.default_seconds`` is the default per-tool wall-clock budget
# applied inside ``PolicyWrappedTool._arun`` when a tool does not declare its
# own ``SandboxSpec.max_wall_clock_seconds``. ``tool_wallclock.overrides``
# maps a tool name to a per-tool override (wins over both the sandbox default
# and the ``default_seconds`` fallback). A value ``<= 0`` disables the cap.
_DEFAULT_MAX_TURN_WALLCLOCK_S = 0.0
_DEFAULT_TOOL_WALLCLOCK_DEFAULT_S = 0.0

# Upper bound on the number of sections a single markdown memory file may
# produce in ``MemoryIndexer._split_document_sections``. Long files fragment
# at every H2-H6 heading and can otherwise yield thousands of tiny sections
# that bloat the index.
_DEFAULT_MAX_SECTIONS_PER_FILE = 64

# Normalized values for rag_mode. Historically this was a plain bool
# (False = no RAG, True = keyword BM25/lexical retrieval). The string form
# ("off" / "keyword" / "llm_probe") is a superset that unlocks the LLM-probe
# retrieval mode without breaking existing configs that set a bool.
RAG_MODE_OFF = "off"
RAG_MODE_KEYWORD = "keyword"
RAG_MODE_LLM_PROBE = "llm_probe"
_VALID_RAG_MODES = (RAG_MODE_OFF, RAG_MODE_KEYWORD, RAG_MODE_LLM_PROBE)


_DEFAULT: dict = {
    "rag_mode": False,
    "deterministic_seed": None,
    "max_tokens_per_turn": _DEFAULT_MAX_TOKENS_PER_TURN,
    "max_turn_wallclock_s": _DEFAULT_MAX_TURN_WALLCLOCK_S,
    "tool_wallclock": {
        "default_seconds": _DEFAULT_TOOL_WALLCLOCK_DEFAULT_S,
        "overrides": {},
    },
    "production_hardening": {"posture": DEFAULT_POSTURE},
    "prompt_context": {
        "include_git_context": False,
        "memory_stale_days": _DEFAULT_MEMORY_STALE_DAYS,
        "llm_probe_min_files": _DEFAULT_LLM_PROBE_MIN_FILES,
        "llm_probe_max_chars": _DEFAULT_LLM_PROBE_MAX_CHARS,
    },
    "prompt_budget": dict(_DEFAULT_PROMPT_BUDGET),
    "agent_runtime": {
        "executor_recursion_limit": 1000,
        "helper_agent_recursion_limit": 1000,
    },
    "verification": {
        "retry_on_repair_required": True,
        # Wallclock seconds allowed for the verifier + single repair retry,
        # measured from the first ``verification_result`` helper event. 0
        # disables the cap. Breach emits a ``verifier_cap_exceeded`` error
        # through the same path as the per-turn token budget breach.
        "verifier_max_wall_s": 0,
        # Output-token ceiling for the verifier + single repair retry,
        # measured as the delta from the first ``verification_result`` helper
        # event. 0 disables the cap.
        "verifier_max_tokens": 0,
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
    "permissions": {
        "enabled": False,
        "rules": [],
        "cache_max_entries_per_session": 256,
    },
    "access_defaults": {
        "allow_loopback_without_auth": True,
    },
    "api_rate_limits": {
        "files_read": {"rate": 30, "period_seconds": 60, "enabled": True},
        "files_write": {"rate": 10, "period_seconds": 60, "enabled": True},
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
                    "fallback_model": None,
                },
                "planner": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "temperature": 0.2,
                    "streaming": True,
                    "fallback_model": None,
                },
                "verifier": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "temperature": 0.2,
                    "streaming": True,
                    "fallback_model": None,
                },
                "title": {
                    "provider": "openai",
                    "model": "gpt-5-mini",
                    "temperature": 0.2,
                    "streaming": False,
                    "fallback_model": None,
                },
            },
        }
    },
    "skills": {
        "extra_dirs": [],
        "entries": {},
    },
    "memory_indexer": {
        "max_sections_per_file": _DEFAULT_MAX_SECTIONS_PER_FILE,
    },
    "read_file_extra_roots": [],
    "retention": {
        # Off by default — callers opt in per-directory. ``dry_run`` in the
        # config acts as the global default; ``apply_retention(dry_run=...)``
        # can override it per invocation.
        "dry_run": False,
        "enabled_on_startup": False,
        "paths": {},
    },
}


_CACHED_LOADED_RUNTIME: LoadedRuntimeConfig | None = None
_CACHED_LOADED_RUNTIME_SIGNATURE: tuple | None = None


def _layer_stat_signature(layer_name: str, path: Path) -> tuple:
    try:
        st = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return (layer_name, str(path), None, None)
    return (layer_name, str(path), st.st_mtime_ns, st.st_size)


def _runtime_config_signature() -> tuple:
    paths = resolve_runtime_config_paths(_CONFIG_FILE)
    parts: list[tuple] = []
    for layer_name in ("user", "project", "env", "local"):
        path = paths[layer_name]
        if path is None:
            # ``env`` is the only layer that can be absent (when BIOAPEX_ENV is
            # unset). Keep it in the signature so flipping the env profile on
            # or off — or switching between profiles — invalidates the cache.
            parts.append((layer_name, None, None, None))
        else:
            parts.append(_layer_stat_signature(layer_name, path))
    return tuple(parts)


def _load_loaded_runtime() -> LoadedRuntimeConfig:
    # Cache the merged config keyed by each layer file's (path, mtime_ns,
    # size). Writes to tracked layer files are rejected by the file API
    # unless BIOAPEX_ALLOW_CONFIG_RELOAD=1, so the signature stays stable
    # within a turn; when the override is set, the next accessor sees the
    # new mtime and reparses.
    global _CACHED_LOADED_RUNTIME, _CACHED_LOADED_RUNTIME_SIGNATURE
    signature = _runtime_config_signature()
    cached = _CACHED_LOADED_RUNTIME
    if cached is not None and _CACHED_LOADED_RUNTIME_SIGNATURE == signature:
        return cached
    loaded = load_runtime_config(
        default_config=_DEFAULT,
        project_config_path=_CONFIG_FILE,
    )
    # Fail loud at startup (app import / first snapshot) if the merged config
    # has bad types, invalid enums, or unknown fields — better than surfacing
    # the same problem later at first tool dispatch. See
    # ``runtime_config_types.RuntimeConfigModel`` for the schema.
    validate_runtime_config(loaded.data)
    _CACHED_LOADED_RUNTIME = loaded
    _CACHED_LOADED_RUNTIME_SIGNATURE = signature
    return loaded


def _load_runtime() -> dict:
    return _load_loaded_runtime().data


def get_loaded_runtime_config() -> LoadedRuntimeConfig:
    """Return the merged runtime config together with per-layer provenance."""
    return _load_loaded_runtime()


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """A point-in-time capture of the merged runtime config.

    ``config`` is the ``LoadedRuntimeConfig`` produced by ``load_runtime_config``
    at capture time. ``loaded_at`` is the unix timestamp (seconds) when the
    snapshot was taken; it is stamped into session metadata so that a turn's
    decisions can be traced back to the exact config that was live when it
    started.
    """

    config: LoadedRuntimeConfig
    loaded_at: float


def snapshot_runtime_config() -> RuntimeConfigSnapshot:
    """Capture the current runtime config and the time it was read.

    Callers at turn-entry boundaries use this to freeze config for the
    duration of the turn. Mid-turn writes to the backing files are rejected
    at the file API layer, so later ``get_*`` calls in the same turn will
    return the same values the snapshot did.
    """
    return RuntimeConfigSnapshot(
        config=_load_loaded_runtime(),
        loaded_at=time.time(),
    )


def config_reload_allowed() -> bool:
    """Return True when the dev override env var lets callers rewrite config."""
    return os.getenv(ALLOW_CONFIG_RELOAD_ENV_VAR, "").strip() == "1"

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


def get_permissions_settings() -> dict[str, Any]:
    """Return the prose permission-rules config block.

    Schema:
      {
        "enabled": bool,
        "rules": [{"description": str, "effect": "allow"|"deny"|"ask"}],
        "cache_max_entries_per_session": int,
      }

    Rules are evaluated by a pluggable classifier registered via
    ``tools.prose_policy.set_prose_classifier``; when no classifier is
    registered the layer falls back to the hardcoded deny-list / ask-user
    ladder documented in ``tools/prose_policy.py``.
    """
    permissions = _load_runtime().get("permissions", {})
    return dict(permissions) if isinstance(permissions, dict) else {}


def get_access_defaults() -> dict[str, Any]:
    access_defaults = _load_runtime().get("access_defaults", {})
    return dict(access_defaults) if isinstance(access_defaults, dict) else {}


def get_api_rate_limits() -> dict[str, Any]:
    """Return the ``api_rate_limits`` block used by ``rate_limit.py``.

    Shape::

        {
          "<bucket_name>": {
            "rate": <int>,
            "period_seconds": <int>,
            "enabled": <bool>,
          },
          ...
        }

    Bucket names currently consumed by the backend: ``files_read`` and
    ``files_write``. Missing or malformed entries fall back to the
    built-in defaults declared in ``rate_limit.DEFAULT_LIMITS``.
    """
    raw = _load_runtime().get("api_rate_limits", {})
    return dict(raw) if isinstance(raw, dict) else {}


def get_execution_backend_settings() -> dict[str, Any]:
    execution_backends = _load_runtime().get("execution_backends", {})
    return dict(execution_backends) if isinstance(execution_backends, dict) else {}


def get_retention_settings() -> dict[str, Any]:
    """Return the ``retention`` config block (see ``runtime/retention.py``)."""
    retention = _load_runtime().get("retention", {})
    return dict(retention) if isinstance(retention, dict) else {}

def _normalize_rag_mode(raw: Any) -> str:
    """Coerce the configured rag_mode into one of ``_VALID_RAG_MODES``.

    Historical configs used a plain bool (False/True = off/keyword). Strings
    are matched case-insensitively; unknown values fall back to ``off``.
    """
    if isinstance(raw, bool):
        return RAG_MODE_KEYWORD if raw else RAG_MODE_OFF
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _VALID_RAG_MODES:
            return token
        if token in {"true", "on", "bm25", "lexical"}:
            return RAG_MODE_KEYWORD
        if token in {"false", ""}:
            return RAG_MODE_OFF
    return RAG_MODE_OFF


def get_rag_mode_name() -> str:
    """Return the normalized rag_mode: 'off' | 'keyword' | 'llm_probe'."""
    return _normalize_rag_mode(_load_runtime().get("rag_mode", False))


def get_rag_mode() -> bool:
    """Back-compat: True when retrieval-augmented memory is on (keyword or llm_probe)."""
    return get_rag_mode_name() != RAG_MODE_OFF


def get_llm_probe_min_files() -> int:
    """Minimum memory-file count that enables the LLM-probe path."""
    raw = get_prompt_context_settings().get(
        "llm_probe_min_files", _DEFAULT_LLM_PROBE_MIN_FILES
    )
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LLM_PROBE_MIN_FILES


def get_llm_probe_max_chars() -> int:
    """Char budget for the compact file-index payload sent to the probe LLM."""
    raw = get_prompt_context_settings().get(
        "llm_probe_max_chars", _DEFAULT_LLM_PROBE_MAX_CHARS
    )
    try:
        return max(500, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_LLM_PROBE_MAX_CHARS


def get_memory_indexer_settings() -> dict[str, Any]:
    memory_indexer = _load_runtime().get("memory_indexer", {})
    return dict(memory_indexer) if isinstance(memory_indexer, dict) else {}


def get_max_sections_per_file() -> int:
    """Return the per-file section cap used by ``MemoryIndexer``.

    Resolution order: runtime ``memory_indexer.max_sections_per_file``, then
    the built-in default. Invalid / non-positive values fall back to the
    default so a misconfigured value can never disable indexing entirely.
    """
    raw = get_memory_indexer_settings().get(
        "max_sections_per_file", _DEFAULT_MAX_SECTIONS_PER_FILE
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SECTIONS_PER_FILE
    return value if value >= 1 else _DEFAULT_MAX_SECTIONS_PER_FILE


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


def _coerce_positive_seconds(value: Any) -> float:
    """Return ``value`` coerced to a non-negative float; invalid values → 0."""
    if isinstance(value, bool):
        return 0.0
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return 0.0
    if resolved <= 0:
        return 0.0
    return resolved


def get_max_turn_wallclock_s() -> float:
    """Return the per-turn wall-clock budget in seconds. 0 disables the cap."""
    return _coerce_positive_seconds(
        _load_runtime().get("max_turn_wallclock_s", _DEFAULT_MAX_TURN_WALLCLOCK_S)
    )


def _tool_wallclock_block() -> dict[str, Any]:
    raw = _load_runtime().get("tool_wallclock", {})
    return dict(raw) if isinstance(raw, dict) else {}


def get_tool_wallclock_default_s() -> float:
    """Return the default per-tool wall-clock budget in seconds.

    Applied when a tool does not declare its own
    ``SandboxSpec.max_wall_clock_seconds`` and when no per-tool override
    exists for that name. 0 or negative disables the default.
    """
    return _coerce_positive_seconds(
        _tool_wallclock_block().get("default_seconds", _DEFAULT_TOOL_WALLCLOCK_DEFAULT_S)
    )


def get_tool_wallclock_override_s(tool_name: str) -> float | None:
    """Return the per-tool wall-clock override in seconds, or ``None``.

    A returned value of 0.0 means the operator explicitly disabled the cap
    for this tool — callers should treat that as "do not enforce" rather
    than falling back to the manifest sandbox default. Invalid override
    values (non-numeric strings like ``"30s"``, booleans, ...) are treated
    as absent so a typo cannot silently strip both the manifest timeout
    and the global default.
    """
    overrides = _tool_wallclock_block().get("overrides", {})
    if not isinstance(overrides, dict):
        return None
    if tool_name not in overrides:
        return None
    raw = overrides[tool_name]
    # bool is an int subclass; reject it so ``true``/``false`` cannot be
    # coerced to 1.0/0.0 and accidentally disable the cap.
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, (int, float, str)):
        return None
    try:
        resolved = float(raw)
    except (TypeError, ValueError):
        return None
    if resolved <= 0:
        return 0.0
    return resolved


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
