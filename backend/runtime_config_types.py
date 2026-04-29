from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RuntimeConfigLayerName = Literal["defaults", "user", "project", "env", "local"]


@dataclass(frozen=True)
class RuntimeConfigLayer:
    name: RuntimeConfigLayerName
    path: str | None
    exists: bool
    applied: bool
    keys: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfigFieldProvenance:
    """Provenance for one effective leaf field in the merged runtime config."""

    value: Any
    source_layer: RuntimeConfigLayerName
    path: str | None


@dataclass(frozen=True)
class LoadedRuntimeConfig:
    data: dict[str, Any]
    layers: tuple[RuntimeConfigLayer, ...]
    field_provenance: dict[str, RuntimeConfigFieldProvenance]


# ───────────────────────────────────────────────────────────────────────────
# Pydantic models for the merged runtime config.
#
# Every top-level section is declared here so that a malformed
# ``backend/config.json`` (bad type, typo in a field name, invalid enum) fails
# loudly with a ``pydantic.ValidationError`` at app startup instead of at
# first tool dispatch. The getter API in ``config.py`` still returns plain
# dicts — these models gate the load path, not the callers.
# ───────────────────────────────────────────────────────────────────────────


RagMode = Literal["off", "keyword", "llm_probe"]
HardeningPostureLiteral = Literal["dev", "trusted-lab", "hosted-strict"]
ApprovalThresholdLiteral = Literal["none", "destructive_only", "all_risky"]
ModelRoleName = Literal["executor", "planner", "verifier", "title"]
PermissionEffect = Literal["allow", "deny", "ask"]


class PromptContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_git_context: bool = False
    memory_stale_days: int = Field(default=30, ge=0)
    llm_probe_min_files: int = Field(default=10, ge=0)
    llm_probe_max_chars: int = Field(default=8_000, ge=0)


class PromptBudgetModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_max_chars: int = Field(default=20_000, ge=0)
    project_instruction_file_max_chars: int = Field(default=2_000, ge=0)
    project_instruction_total_max_chars: int = Field(default=8_000, ge=0)
    git_context_max_chars: int = Field(default=2_000, ge=0)
    retrieved_memory_block_max_chars: int = Field(default=1_600, ge=0)
    retrieved_memory_item_max_chars: int = Field(default=280, ge=0)
    scoped_memory_block_max_chars: int = Field(default=4_000, ge=0)
    memory_index_max_chars: int = Field(default=2_048, ge=0)
    total_max_chars: int = Field(default=0, ge=0)


class AgentRuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_recursion_limit: int = Field(default=1000, ge=0)
    helper_agent_recursion_limit: int = Field(default=1000, ge=0)


class VerificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry_on_repair_required: bool = True
    max_repair_attempts: int = Field(default=1, ge=0)
    verifier_max_wall_s: float = Field(default=0.0, ge=0)
    verifier_max_tokens: int = Field(default=0, ge=0)


class LLMOutputTokenCapModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: int = Field(default=8_000, ge=0)
    escalated: int = Field(default=65_536, ge=0)


class ToolPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allow_without_context: bool = True
    warn_on_missing_artifact_refs: bool = True


class PermissionRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    effect: PermissionEffect


class PermissionsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    rules: list[PermissionRuleModel] = Field(default_factory=list)
    cache_max_entries_per_session: int = Field(default=256, ge=0)


class AccessDefaultsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_loopback_without_auth: bool = True


class ToolHardeningInputModel(BaseModel):
    """Partial override block for the posture-derived tool defaults."""

    model_config = ConfigDict(extra="forbid")

    terminal_enabled: bool | None = None
    python_repl_enabled: bool | None = None
    slurm_enabled: bool | None = None
    slurm_legacy_commands_enabled: bool | None = None
    write_file_enabled: bool | None = None


class ApiHardeningInputModel(BaseModel):
    """Partial override block for the posture-derived api defaults."""

    model_config = ConfigDict(extra="forbid")

    files_write_enabled: bool | None = None
    allow_loopback_without_auth: bool | None = None
    trust_forwarded_loopback_headers: bool | None = None
    inspection_bearer_token_env_var: str | None = None
    execution_bearer_token_env_var: str | None = None
    admin_bearer_token_env_var: str | None = None
    cors_allowed_origins: list[str] | None = None


class ProductionHardeningInputModel(BaseModel):
    """Validate the ``production_hardening`` block from config.json.

    This mirrors the shape accepted by
    ``hardening.ProductionHardeningPolicy.from_posture(posture, overrides=...)``:
    a ``posture`` picks one of the known postures, and the remaining fields
    (``tools``, ``api``, ``host_binding``, ``approval_threshold``,
    ``file_write_whitelist``) layer on top as overrides.
    """

    model_config = ConfigDict(extra="forbid")

    posture: HardeningPostureLiteral = "dev"
    tools: ToolHardeningInputModel = Field(default_factory=ToolHardeningInputModel)
    api: ApiHardeningInputModel = Field(default_factory=ApiHardeningInputModel)
    host_binding: str | None = None
    approval_threshold: ApprovalThresholdLiteral | None = None
    file_write_whitelist: list[str] | None = None


class RoleBackendModel(BaseModel):
    """One entry under ``execution_backends.llm.roles.<role>``."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    streaming: bool | None = None
    fallback_model: str | None = None
    api_key: str | None = None


class LLMBackendModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    fallback_model: str | None = None
    roles: dict[ModelRoleName, RoleBackendModel] = Field(default_factory=dict)


class ExecutionBackendsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: LLMBackendModel = Field(default_factory=LLMBackendModel)


class SkillEntryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True


class SkillsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extra_dirs: list[str] = Field(default_factory=list)
    entries: dict[str, SkillEntryModel] = Field(default_factory=dict)


class MemoryIndexerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_sections_per_file: int = Field(default=64, ge=0)


class RetentionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    enabled_on_startup: bool = False
    paths: dict[str, Any] = Field(default_factory=dict)


class ApiRateLimitModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: int = Field(default=0, ge=0)
    period_seconds: int = Field(default=60, ge=0)
    enabled: bool = True


class ToolWallclockModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_seconds: float = Field(default=0.0, ge=0)
    overrides: dict[str, Any] = Field(default_factory=dict)


class RuntimeConfigModel(BaseModel):
    """Pydantic model of the merged runtime config.

    Used to validate the dict produced by ``load_runtime_config`` at startup.
    Validation errors surface at app import (or the first snapshot) so that a
    malformed ``backend/config.json`` cannot slip through and only fail later
    at tool-dispatch time.

    ``rag_mode`` keeps backward compat with the legacy bool form
    (``True`` → ``"keyword"``, ``False`` → ``"off"``) via a ``mode="before"``
    validator that mirrors ``config._normalize_rag_mode``.
    """

    model_config = ConfigDict(extra="forbid")

    rag_mode: RagMode = "off"
    deterministic_seed: int | None = None
    max_tokens_per_turn: int = Field(default=200_000, ge=0)
    max_turn_wallclock_s: float = Field(default=0.0, ge=0)
    tool_wallclock: ToolWallclockModel = Field(default_factory=ToolWallclockModel)
    production_hardening: ProductionHardeningInputModel = Field(
        default_factory=ProductionHardeningInputModel
    )
    prompt_context: PromptContextModel = Field(default_factory=PromptContextModel)
    prompt_budget: PromptBudgetModel = Field(default_factory=PromptBudgetModel)
    agent_runtime: AgentRuntimeModel = Field(default_factory=AgentRuntimeModel)
    verification: VerificationModel = Field(default_factory=VerificationModel)
    llm_output_token_cap: LLMOutputTokenCapModel = Field(
        default_factory=LLMOutputTokenCapModel
    )
    tool_policy: ToolPolicyModel = Field(default_factory=ToolPolicyModel)
    permissions: PermissionsModel = Field(default_factory=PermissionsModel)
    access_defaults: AccessDefaultsModel = Field(default_factory=AccessDefaultsModel)
    execution_backends: ExecutionBackendsModel = Field(
        default_factory=ExecutionBackendsModel
    )
    skills: SkillsModel = Field(default_factory=SkillsModel)
    read_file_extra_roots: list[str] = Field(default_factory=list)
    memory_indexer: MemoryIndexerModel = Field(default_factory=MemoryIndexerModel)
    retention: RetentionModel = Field(default_factory=RetentionModel)
    api_rate_limits: dict[str, ApiRateLimitModel] = Field(default_factory=dict)

    @field_validator("rag_mode", mode="before")
    @classmethod
    def _coerce_rag_mode(cls, raw: Any) -> Any:
        """Mirror ``config._normalize_rag_mode`` for backward compatibility.

        Legacy configs used a plain bool; the string form
        (``off`` / ``keyword`` / ``llm_probe``) is the current schema. Unknown
        strings silently fall back to ``off`` to preserve the older
        silently-lenient behavior for this single field. Non-bool/non-string
        inputs raise a ValidationError.
        """
        if isinstance(raw, bool):
            return "keyword" if raw else "off"
        if isinstance(raw, str):
            token = raw.strip().lower()
            if token in ("off", "keyword", "llm_probe"):
                return token
            if token in {"true", "on", "bm25", "lexical"}:
                return "keyword"
            if token in {"false", ""}:
                return "off"
            return "off"
        raise ValueError(
            f"rag_mode must be a bool or one of 'off'/'keyword'/'llm_probe'; "
            f"got {type(raw).__name__}"
        )


def validate_runtime_config(data: dict[str, Any]) -> None:
    """Validate a merged runtime-config dict.

    Raises ``pydantic.ValidationError`` when the dict has malformed fields.
    The dict is left unchanged — the merged data continues to flow through
    ``LoadedRuntimeConfig.data`` so existing getters and provenance paths are
    unaffected.
    """
    RuntimeConfigModel.model_validate(data)
