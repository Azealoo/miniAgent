"""Typed connector contracts, capability discovery models, and action results."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artifacts.naming import is_valid_run_id
from artifacts.schemas import normalize_identifier

CONNECTOR_ACTION_CONTRACT_VERSION = "connector_action.v1"

ConnectorAction = Literal["configure", "validate", "import", "export", "sync_status"]
ConnectorExecutionAction = Literal["import", "export", "sync_status"]
ConnectorActionStatus = Literal["success", "failed"]
ConnectorActionOutcome = Literal["success", "invalid_input", "blocked", "unsupported", "execution_failure"]
ConnectorFailureMode = Literal[
    "invalid_configuration",
    "unsupported_capability",
    "blocked_action",
    "remote_failure",
    "sync_conflict",
    "partial_result",
]
ConnectorTransportPattern = Literal["file_drop", "rest_api", "webhook_callback"]
ConnectorConfigFieldKind = Literal[
    "string",
    "url",
    "directory_path",
    "route_path",
    "env_var",
    "string_list",
    "boolean",
    "enum",
]
ConnectorSystemKind = Literal["eln", "lims", "instrument", "external_service"]
ConnectorArtifactDomain = Literal[
    "dataset_manifest",
    "workflow_run",
    "protocol_run",
    "evidence_card",
    "evidence_review",
    "entity_grounding",
    "claim_graph",
    "compliance_report",
    "qa_report",
    "eln_export",
    "report_bundle",
    "report_bundle_manifest",
]


def _clean_text(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def _normalize_relative_path(value: str, *, field_name: str) -> str:
    cleaned = _clean_text(value, field_name=field_name)
    candidate = PurePosixPath(cleaned)
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative, not absolute.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{field_name} must not contain '..'.")
    if candidate.parts == (".",):
        raise ValueError(f"{field_name} must not resolve to '.'.")
    return str(candidate)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if raw in seen:
            continue
        seen.add(raw)
        result.append(raw)
    return result


class ConnectorGuardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requires_compliance_gate: bool = True
    requires_provenance_records: bool = True
    requires_artifact_registration: bool = True
    allow_destructive_sync: bool = False


class ConnectorConfigField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    kind: ConnectorConfigFieldKind
    description: str
    required: bool = True
    allowed_values: list[str] = Field(default_factory=list)
    secret_reference: bool = False

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        return normalize_identifier(value)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _clean_text(value, field_name="description")

    @field_validator("allowed_values")
    @classmethod
    def _validate_allowed_values(cls, value: list[str]) -> list[str]:
        cleaned = [_clean_text(item, field_name="allowed_values entry") for item in value]
        return _dedupe_preserving_order(cleaned)

    @model_validator(mode="after")
    def _validate_enum_fields(self) -> "ConnectorConfigField":
        if self.kind == "enum" and not self.allowed_values:
            raise ValueError("Enum config fields must declare allowed_values.")
        if self.kind != "enum" and self.allowed_values:
            raise ValueError("allowed_values are only valid for enum config fields.")
        return self


class ConnectorCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported_actions: list[ConnectorAction]
    transport_patterns: list[ConnectorTransportPattern]
    artifact_domains: list[ConnectorArtifactDomain]
    guardrails: ConnectorGuardrails = Field(default_factory=ConnectorGuardrails)

    @field_validator("supported_actions", "transport_patterns", "artifact_domains")
    @classmethod
    def _dedupe_values(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Capability lists must not be empty.")
        return _dedupe_preserving_order(value)


class ConnectorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    description: str
    system_kind: ConnectorSystemKind
    external_system: str
    capabilities: ConnectorCapabilities
    config_fields: list[ConnectorConfigField] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return normalize_identifier(value)

    @field_validator("display_name", "description", "external_system")
    @classmethod
    def _validate_text(cls, value: str, info) -> str:
        return _clean_text(value, field_name=info.field_name)

    @field_validator("notes")
    @classmethod
    def _validate_notes(cls, value: list[str]) -> list[str]:
        return [_clean_text(item, field_name="note") for item in value]


class ConnectorConfigSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    configured_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    uses_secret_references: bool = False

    @field_validator("configured_fields", "missing_required_fields")
    @classmethod
    def _validate_fields(cls, value: list[str]) -> list[str]:
        normalized = [normalize_identifier(item) for item in value]
        return _dedupe_preserving_order(normalized)


class ConnectorActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    artifact_path: str | None = None
    payload: dict[str, Any] | None = None
    compliance_artifact_path: str | None = None
    provenance_artifact_paths: list[str] = Field(default_factory=list)
    event_type: str | None = None
    delivery_signature: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    workflow_id: str | None = None

    @field_validator("artifact_path")
    @classmethod
    def _validate_artifact_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value, field_name="artifact_path")

    @field_validator("compliance_artifact_path")
    @classmethod
    def _validate_compliance_artifact_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value, field_name="compliance_artifact_path")

    @field_validator("provenance_artifact_paths")
    @classmethod
    def _validate_provenance_artifact_paths(cls, value: list[str]) -> list[str]:
        normalized = [_normalize_relative_path(item, field_name="provenance_artifact_path") for item in value]
        return _dedupe_preserving_order(normalized)

    @field_validator("event_type", "delivery_signature")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name=info.field_name)

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name="session_id")

    @field_validator("run_id")
    @classmethod
    def _validate_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value, field_name="run_id")
        if not is_valid_run_id(cleaned):
            raise ValueError(f"Invalid run_id format: {cleaned!r}")
        return cleaned

    @field_validator("workflow_id")
    @classmethod
    def _validate_workflow_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_identifier(value)


class ConnectorRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    description: str
    system_kind: ConnectorSystemKind
    external_system: str
    capabilities: ConnectorCapabilities
    config_fields: list[ConnectorConfigField] = Field(default_factory=list)
    enabled: bool = False
    config_summary: ConnectorConfigSummary
    notes: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return normalize_identifier(value)


class ConnectorValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    code: str
    message: str

    @field_validator("field")
    @classmethod
    def _validate_optional_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_identifier(value)

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        return normalize_identifier(value)

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        return _clean_text(value, field_name="message")


class ConnectorActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = CONNECTOR_ACTION_CONTRACT_VERSION
    connector_name: str
    action: ConnectorAction
    status: ConnectorActionStatus
    outcome: ConnectorActionOutcome
    summary: str
    action_supported: bool = True
    non_destructive: bool = True
    failure_mode: ConnectorFailureMode | None = None
    issues: list[ConnectorValidationIssue] = Field(default_factory=list)
    config_summary: ConnectorConfigSummary | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    external_paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("connector_name")
    @classmethod
    def _validate_connector_name(cls, value: str) -> str:
        return normalize_identifier(value)

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _clean_text(value, field_name="summary")

    @field_validator("artifact_paths")
    @classmethod
    def _validate_artifact_paths(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item, field_name="artifact_path") for item in value]

    @field_validator("external_paths")
    @classmethod
    def _validate_external_paths(cls, value: list[str]) -> list[str]:
        return [_clean_text(item, field_name="external_path") for item in value]

    @model_validator(mode="after")
    def _validate_status_fields(self) -> "ConnectorActionResult":
        if self.outcome == "success" and self.status != "success":
            raise ValueError("Successful connector outcomes must use status='success'.")
        if self.outcome != "success" and self.status != "failed":
            raise ValueError("Failed connector outcomes must use status='failed'.")
        if self.status == "success" and self.failure_mode is not None:
            raise ValueError("failure_mode is only valid for failed connector actions.")
        return self
