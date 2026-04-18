"""Shared production-hardening policy models and secret-path helpers.

`ProductionHardeningPolicy` is driven by a named `posture`
(`dev | trusted-lab | hosted-strict`) that expands into every downstream
flag — loopback auth, host binding, tool risk tiers, approval thresholds,
file-write whitelist, and CORS origins. Individual fields remain available
as optional escape hatches that layer on top of the posture defaults.

Posture semantics track `.omx/research/claude-code-src-hardening-leverage-2026-04-02.md`:

- ``dev``            — current permissive defaults, loopback-only local use.
- ``trusted-lab``    — shared-hosted middle: bearer-auth required, REPL off,
                       legacy slurm off, listens on the lab network.
- ``hosted-strict``  — the ``fail_closed()`` baseline: every tool disabled,
                       remote writes disabled, CORS empty, host loopback.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HardeningPosture = Literal["dev", "trusted-lab", "hosted-strict"]
ApprovalThreshold = Literal["none", "destructive_only", "all_risky"]

VALID_POSTURES: tuple[HardeningPosture, ...] = ("dev", "trusted-lab", "hosted-strict")
DEFAULT_POSTURE: HardeningPosture = "dev"

_LOCAL_FRONTEND_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
)

_DEFAULT_FILE_WRITE_WHITELIST: tuple[str, ...] = (
    "workspace/",
    "memory/",
    "skills/",
    "knowledge/",
)


def _default_cors_allowed_origins() -> list[str]:
    return list(_LOCAL_FRONTEND_CORS_ORIGINS)


class ToolHardeningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminal_enabled: bool = True
    python_repl_enabled: bool = True
    slurm_enabled: bool = True
    slurm_legacy_commands_enabled: bool = True
    write_file_enabled: bool = True

    @classmethod
    def fail_closed(cls) -> "ToolHardeningPolicy":
        return cls(
            terminal_enabled=False,
            python_repl_enabled=False,
            slurm_enabled=False,
            slurm_legacy_commands_enabled=False,
            write_file_enabled=False,
        )


class ApiHardeningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files_write_enabled: bool = True
    allow_loopback_without_auth: bool = True
    trust_forwarded_loopback_headers: bool = False
    inspection_bearer_token_env_var: str | None = None
    execution_bearer_token_env_var: str | None = None
    admin_bearer_token_env_var: str | None = None
    cors_allowed_origins: list[str] = Field(default_factory=_default_cors_allowed_origins)

    @classmethod
    def fail_closed(cls) -> "ApiHardeningPolicy":
        return cls(
            files_write_enabled=False,
            allow_loopback_without_auth=False,
            trust_forwarded_loopback_headers=False,
            cors_allowed_origins=[],
        )


_POSTURE_DEFAULTS: dict[HardeningPosture, dict[str, Any]] = {
    "dev": {
        "posture": "dev",
        "tools": {
            "terminal_enabled": True,
            "python_repl_enabled": True,
            "slurm_enabled": True,
            "slurm_legacy_commands_enabled": True,
            "write_file_enabled": True,
        },
        "api": {
            "files_write_enabled": True,
            "allow_loopback_without_auth": True,
            "trust_forwarded_loopback_headers": False,
            "inspection_bearer_token_env_var": None,
            "execution_bearer_token_env_var": None,
            "admin_bearer_token_env_var": None,
            "cors_allowed_origins": list(_LOCAL_FRONTEND_CORS_ORIGINS),
        },
        "host_binding": "127.0.0.1",
        "approval_threshold": "none",
        "file_write_whitelist": list(_DEFAULT_FILE_WRITE_WHITELIST),
    },
    "trusted-lab": {
        "posture": "trusted-lab",
        "tools": {
            "terminal_enabled": True,
            "python_repl_enabled": False,
            "slurm_enabled": True,
            "slurm_legacy_commands_enabled": False,
            "write_file_enabled": True,
        },
        "api": {
            "files_write_enabled": True,
            "allow_loopback_without_auth": False,
            "trust_forwarded_loopback_headers": False,
            "inspection_bearer_token_env_var": None,
            "execution_bearer_token_env_var": None,
            "admin_bearer_token_env_var": None,
            "cors_allowed_origins": list(_LOCAL_FRONTEND_CORS_ORIGINS),
        },
        "host_binding": "0.0.0.0",
        "approval_threshold": "destructive_only",
        "file_write_whitelist": list(_DEFAULT_FILE_WRITE_WHITELIST),
    },
    "hosted-strict": {
        "posture": "hosted-strict",
        "tools": {
            "terminal_enabled": False,
            "python_repl_enabled": False,
            "slurm_enabled": False,
            "slurm_legacy_commands_enabled": False,
            "write_file_enabled": False,
        },
        "api": {
            "files_write_enabled": False,
            "allow_loopback_without_auth": False,
            "trust_forwarded_loopback_headers": False,
            "inspection_bearer_token_env_var": None,
            "execution_bearer_token_env_var": None,
            "admin_bearer_token_env_var": None,
            "cors_allowed_origins": [],
        },
        "host_binding": "127.0.0.1",
        "approval_threshold": "all_risky",
        "file_write_whitelist": [],
    },
}


def posture_defaults(posture: HardeningPosture) -> dict[str, Any]:
    """Return a deep copy of the fully-expanded default dict for a posture."""
    if posture not in _POSTURE_DEFAULTS:
        raise ValueError(f"Unknown hardening posture: {posture!r}")
    return copy.deepcopy(_POSTURE_DEFAULTS[posture])


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class ProductionHardeningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posture: HardeningPosture = DEFAULT_POSTURE
    tools: ToolHardeningPolicy = Field(default_factory=ToolHardeningPolicy)
    api: ApiHardeningPolicy = Field(default_factory=ApiHardeningPolicy)
    host_binding: str = "127.0.0.1"
    approval_threshold: ApprovalThreshold = "none"
    file_write_whitelist: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_FILE_WRITE_WHITELIST)
    )

    @classmethod
    def from_posture(
        cls,
        posture: HardeningPosture,
        overrides: dict[str, Any] | None = None,
    ) -> "ProductionHardeningPolicy":
        """Build a policy with posture-derived defaults plus optional overrides."""
        if posture not in _POSTURE_DEFAULTS:
            raise ValueError(f"Unknown hardening posture: {posture!r}")
        base = posture_defaults(posture)
        if overrides:
            base = _deep_merge(base, overrides)
            base["posture"] = posture
        return cls.model_validate(base)

    @classmethod
    def fail_closed(cls) -> "ProductionHardeningPolicy":
        return cls.from_posture("hosted-strict")


_BLOCKED_SECRET_FILENAMES = frozenset({".env"})
_BLOCKED_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".crt", ".cer"})
_BLOCKED_SECRET_PATTERNS = (
    re.compile(r"^\.env(\..+)?$", re.I),
    re.compile(r"^.*\.env$", re.I),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)$", re.I),
)


def is_secret_like_path(path: str | Path) -> bool:
    candidate = Path(str(path).strip())
    name = candidate.name.lower()
    if name in _BLOCKED_SECRET_FILENAMES:
        return True
    if candidate.suffix.lower() in _BLOCKED_SECRET_SUFFIXES:
        return True
    return any(pattern.match(name) for pattern in _BLOCKED_SECRET_PATTERNS)


__all__ = [
    "ApiHardeningPolicy",
    "ApprovalThreshold",
    "DEFAULT_POSTURE",
    "HardeningPosture",
    "ProductionHardeningPolicy",
    "ToolHardeningPolicy",
    "VALID_POSTURES",
    "is_secret_like_path",
    "posture_defaults",
]
