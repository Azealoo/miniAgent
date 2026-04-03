from pathlib import Path
from typing import Any

from hardening import ProductionHardeningPolicy
from runtime_config import load_runtime_config

_CONFIG_FILE = Path(__file__).parent / "config.json"
_DEFAULT: dict = {
    "rag_mode": False,
    "prompt_context": {
        "include_git_context": False,
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


def _load_runtime() -> dict:
    return load_runtime_config(
        default_config=_DEFAULT,
        project_config_path=_CONFIG_FILE,
    ).data

def get_prompt_context_settings() -> dict[str, Any]:
    prompt_context = _load_runtime().get("prompt_context", {})
    return dict(prompt_context) if isinstance(prompt_context, dict) else {}


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
    if "production_hardening" not in cfg:
        return ProductionHardeningPolicy()
    raw = cfg.get("production_hardening", {})
    if not isinstance(raw, dict):
        return ProductionHardeningPolicy.fail_closed()
    try:
        return ProductionHardeningPolicy.model_validate(raw)
    except Exception:
        return ProductionHardeningPolicy.fail_closed()
