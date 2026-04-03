"""Shared production-hardening policy models and secret-path helpers."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _default_cors_allowed_origins() -> list[str]:
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]


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


class ProductionHardeningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: ToolHardeningPolicy = Field(default_factory=ToolHardeningPolicy)
    api: ApiHardeningPolicy = Field(default_factory=ApiHardeningPolicy)

    @classmethod
    def fail_closed(cls) -> "ProductionHardeningPolicy":
        return cls(
            tools=ToolHardeningPolicy.fail_closed(),
            api=ApiHardeningPolicy.fail_closed(),
        )


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
    "ProductionHardeningPolicy",
    "ToolHardeningPolicy",
    "is_secret_like_path",
]
