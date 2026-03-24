"""Connector capability discovery, config validation, and registry helpers."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import config as cfg
from audit.store import append_connector_action_event

from .models import (
    ConnectorActionResult,
    ConnectorCapabilities,
    ConnectorConfigField,
    ConnectorConfigSummary,
    ConnectorDefinition,
    ConnectorGuardrails,
    ConnectorRegistryEntry,
    ConnectorValidationIssue,
    normalize_identifier,
)

_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _builtin_connector_definitions() -> tuple[ConnectorDefinition, ...]:
    shared_guardrails = ConnectorGuardrails(
        requires_compliance_gate=True,
        requires_provenance_records=True,
        requires_artifact_registration=True,
        allow_destructive_sync=False,
    )
    return (
        ConnectorDefinition(
            name="eln_file_drop",
            display_name="ELN File Drop",
            description="Exports BioAPEX ELN bundles to a shared file-drop directory without changing internal artifacts.",
            system_kind="eln",
            external_system="eln",
            capabilities=ConnectorCapabilities(
                supported_actions=["configure", "validate", "export", "sync_status"],
                transport_patterns=["file_drop"],
                artifact_domains=["eln_export", "workflow_run", "protocol_run", "report_bundle_manifest", "report_bundle"],
                guardrails=shared_guardrails,
            ),
            config_fields=[
                ConnectorConfigField(
                    key="outgoing_dir",
                    kind="directory_path",
                    description="Shared directory where ELN export bundles will be copied.",
                ),
                ConnectorConfigField(
                    key="include_archive",
                    kind="boolean",
                    description="Whether the portable ELN archive should be included in the file drop.",
                    required=False,
                ),
            ],
            notes=[
                "Build exports only from persisted ELN artifacts already materialized on disk.",
                "File-drop sync must remain additive and leave canonical BioAPEX run artifacts untouched.",
            ],
        ),
        ConnectorDefinition(
            name="lims_rest_bridge",
            display_name="LIMS REST Bridge",
            description="Maps BioAPEX dataset and workflow records to a LIMS-facing REST API contract.",
            system_kind="lims",
            external_system="lims",
            capabilities=ConnectorCapabilities(
                supported_actions=["configure", "validate", "import", "export", "sync_status"],
                transport_patterns=["rest_api"],
                artifact_domains=["dataset_manifest", "workflow_run", "protocol_run", "compliance_report"],
                guardrails=shared_guardrails,
            ),
            config_fields=[
                ConnectorConfigField(
                    key="base_url",
                    kind="url",
                    description="Base HTTPS endpoint for the external LIMS API.",
                ),
                ConnectorConfigField(
                    key="project_slug",
                    kind="string",
                    description="Normalized project or workspace identifier in the remote LIMS.",
                ),
                ConnectorConfigField(
                    key="auth_strategy",
                    kind="enum",
                    description="Authentication approach for the remote API.",
                    allowed_values=["none", "token_env", "basic_auth_env"],
                ),
                ConnectorConfigField(
                    key="credential_env_var",
                    kind="env_var",
                    description="Environment variable name holding the remote credential or token.",
                    required=False,
                    secret_reference=True,
                ),
            ],
            notes=[
                "Remote identifiers should remain references layered on top of canonical BioAPEX artifacts.",
                "Connector config stores secret references, not raw secrets.",
            ],
        ),
        ConnectorDefinition(
            name="instrument_webhook_ingest",
            display_name="Instrument Webhook Ingest",
            description="Accepts instrument or external-service callbacks and translates them into BioAPEX-managed artifacts.",
            system_kind="instrument",
            external_system="instrument",
            capabilities=ConnectorCapabilities(
                supported_actions=["configure", "validate", "import", "sync_status"],
                transport_patterns=["webhook_callback"],
                artifact_domains=["dataset_manifest", "workflow_run", "qa_report"],
                guardrails=shared_guardrails,
            ),
            config_fields=[
                ConnectorConfigField(
                    key="callback_path",
                    kind="route_path",
                    description="HTTP callback path the upstream system will target.",
                ),
                ConnectorConfigField(
                    key="shared_secret_env",
                    kind="env_var",
                    description="Environment variable name for verifying callback signatures.",
                    secret_reference=True,
                ),
                ConnectorConfigField(
                    key="accepted_event_types",
                    kind="string_list",
                    description="Allowed upstream event types for import or sync updates.",
                ),
            ],
            notes=[
                "Webhook ingestion must validate signatures and materialize imported state as canonical BioAPEX artifacts.",
                "Callbacks should update sync status without mutating prior records destructively.",
            ],
        ),
    )


_CONNECTOR_DEFINITIONS = {item.name: item for item in _builtin_connector_definitions()}


def list_connector_definitions() -> list[ConnectorDefinition]:
    return [definition.model_copy(deep=True) for definition in _CONNECTOR_DEFINITIONS.values()]


def get_connector_definition(connector_name: str) -> ConnectorDefinition:
    normalized_name = connector_name.strip()
    try:
        definition = _CONNECTOR_DEFINITIONS[normalized_name]
    except KeyError as exc:
        raise KeyError(f"Unknown connector: {connector_name}") from exc
    return definition.model_copy(deep=True)


def _has_config_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _configured_field_names(definition: ConnectorDefinition, config: dict[str, Any]) -> list[str]:
    return [
        field.key
        for field in definition.config_fields
        if field.key in config and _has_config_value(config.get(field.key))
    ]


def _normalized_issue_field_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        normalized = value.strip()
        if not normalized:
            return None
        return normalized if normalize_identifier(normalized) == normalized else None
    except Exception:
        return None


def summarize_connector_config(
    definition: ConnectorDefinition,
    config: dict[str, Any],
) -> ConnectorConfigSummary:
    configured_fields = _configured_field_names(definition, config)
    missing_required = [
        field.key
        for field in definition.config_fields
        if field.required and field.key not in configured_fields
    ]
    uses_secret_references = any(
        field.secret_reference and field.key in configured_fields
        for field in definition.config_fields
    )
    return ConnectorConfigSummary(
        configured=bool(configured_fields),
        configured_fields=configured_fields,
        missing_required_fields=missing_required,
        uses_secret_references=uses_secret_references,
    )


def list_connector_registry_entries() -> list[ConnectorRegistryEntry]:
    entries: list[ConnectorRegistryEntry] = []
    for definition in list_connector_definitions():
        stored = cfg.get_connector_entry(definition.name)
        config_payload = stored["config"]
        validation_result = validate_connector_entry(
            definition.name,
            config=config_payload,
        )
        entries.append(
            ConnectorRegistryEntry(
                name=definition.name,
                display_name=definition.display_name,
                description=definition.description,
                system_kind=definition.system_kind,
                external_system=definition.external_system,
                capabilities=definition.capabilities,
                config_fields=definition.config_fields,
                enabled=stored["enabled"],
                config_summary=summarize_connector_config(definition, config_payload),
                validation_result=validation_result,
                notes=definition.notes,
            )
        )
    return sorted(entries, key=lambda item: item.name)


def get_connector_registry_entry(connector_name: str) -> ConnectorRegistryEntry:
    definition = get_connector_definition(connector_name)
    stored = cfg.get_connector_entry(definition.name)
    validation_result = validate_connector_entry(
        definition.name,
        config=stored["config"],
    )
    return ConnectorRegistryEntry(
        name=definition.name,
        display_name=definition.display_name,
        description=definition.description,
        system_kind=definition.system_kind,
        external_system=definition.external_system,
        capabilities=definition.capabilities,
        config_fields=definition.config_fields,
        enabled=stored["enabled"],
        config_summary=summarize_connector_config(definition, stored["config"]),
        validation_result=validation_result,
        notes=definition.notes,
    )


def _validate_string(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field.key} must be a non-empty string."
    return None


def _validate_url(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field.key} must be a non-empty URL."
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"{field.key} must use an http or https URL."
    return None


def _validate_directory_path(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field.key} must be a non-empty directory path."
    candidate = Path(value.strip())
    if not candidate.is_absolute():
        rel = PurePosixPath(value.strip())
        if any(part == ".." for part in rel.parts):
            return f"{field.key} must not contain '..' when using a relative path."
    return None


def _validate_route_path(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field.key} must be a non-empty callback path."
    cleaned = value.strip()
    if not cleaned.startswith("/"):
        return f"{field.key} must start with '/'."
    if " " in cleaned:
        return f"{field.key} must not contain spaces."
    return None


def _validate_env_var(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field.key} must name an environment variable."
    if _ENV_VAR_RE.fullmatch(value.strip()) is None:
        return f"{field.key} must use an uppercase environment variable name."
    return None


def _validate_string_list(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return f"{field.key} must be a non-empty list of strings."
    if not all(isinstance(item, str) and item.strip() for item in value):
        return f"{field.key} must contain only non-empty strings."
    return None


def _validate_boolean(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, bool):
        return f"{field.key} must be a boolean value."
    return None


def _validate_enum(field: ConnectorConfigField, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{field.key} must be one of: {', '.join(field.allowed_values)}."
    if value.strip() not in field.allowed_values:
        return f"{field.key} must be one of: {', '.join(field.allowed_values)}."
    return None


def validate_connector_config(
    definition: ConnectorDefinition,
    config: dict[str, Any],
) -> list[ConnectorValidationIssue]:
    issues: list[ConnectorValidationIssue] = []
    allowed_keys = {field.key for field in definition.config_fields}

    for raw_key in sorted(config):
        if raw_key in allowed_keys:
            continue
        issues.append(
            ConnectorValidationIssue(
                field=_normalized_issue_field_name(raw_key),
                code="unknown_field",
                message=f"Unknown config field {raw_key!r} for connector {definition.name}.",
            )
        )

    validators = {
        "string": _validate_string,
        "url": _validate_url,
        "directory_path": _validate_directory_path,
        "route_path": _validate_route_path,
        "env_var": _validate_env_var,
        "string_list": _validate_string_list,
        "boolean": _validate_boolean,
        "enum": _validate_enum,
    }

    for field in definition.config_fields:
        field_present = field.key in config and _has_config_value(config.get(field.key))
        if field.required and not field_present:
            issues.append(
                ConnectorValidationIssue(
                    field=field.key,
                    code="missing_required_field",
                    message=f"{field.key} is required for connector {definition.name}.",
                )
            )
            continue
        if not field_present:
            continue
        error = validators[field.kind](field, config.get(field.key))
        if error is not None:
            issues.append(
                ConnectorValidationIssue(
                    field=field.key,
                    code="invalid_field_value",
                    message=error,
                )
            )

    if definition.name == "lims_rest_bridge":
        auth_strategy = config.get("auth_strategy")
        if auth_strategy in {"token_env", "basic_auth_env"} and not _has_config_value(config.get("credential_env_var")):
            issues.append(
                ConnectorValidationIssue(
                    field="credential_env_var",
                    code="missing_required_field",
                    message="credential_env_var is required when auth_strategy uses environment-backed credentials.",
                )
            )
    return issues


def _build_action_result(
    definition: ConnectorDefinition,
    *,
    action: str,
    config: dict[str, Any],
    issues: list[ConnectorValidationIssue],
    summary: str,
) -> ConnectorActionResult:
    config_summary = summarize_connector_config(definition, config)
    if issues:
        return ConnectorActionResult(
            connector_name=definition.name,
            action=action,
            status="failed",
            outcome="invalid_input",
            summary=summary,
            failure_mode="invalid_configuration",
            issues=issues,
            config_summary=config_summary,
            metadata={
                "transport_patterns": definition.capabilities.transport_patterns,
                "artifact_domains": definition.capabilities.artifact_domains,
                "configured_fields": config_summary.configured_fields,
            },
        )

    return ConnectorActionResult(
        connector_name=definition.name,
        action=action,
        status="success",
        outcome="success",
        summary=summary,
        config_summary=config_summary,
        metadata={
            "transport_patterns": definition.capabilities.transport_patterns,
            "artifact_domains": definition.capabilities.artifact_domains,
            "configured_fields": config_summary.configured_fields,
        },
    )


def validate_connector_entry(
    connector_name: str,
    *,
    config: dict[str, Any] | None = None,
    base_dir: Path | str | None = None,
) -> ConnectorActionResult:
    definition = get_connector_definition(connector_name)
    resolved_config = cfg.get_connector_entry(definition.name)["config"] if config is None else dict(config)
    issues = validate_connector_config(definition, resolved_config)
    summary = (
        f"Connector {definition.name} configuration is valid."
        if not issues
        else f"Connector {definition.name} configuration is incomplete or invalid."
    )
    result = _build_action_result(
        definition,
        action="validate",
        config=resolved_config,
        issues=issues,
        summary=summary,
    )
    if base_dir is not None:
        append_connector_action_event(
            base_dir,
            connector_name=definition.name,
            action="validate",
            outcome=result.outcome,
            status=result.status,
            failure_mode=result.failure_mode,
            external_systems=[definition.external_system],
            details={
                "issues": [issue.model_dump(mode="json") for issue in result.issues],
                "config_summary": result.config_summary.model_dump(mode="json") if result.config_summary else None,
                "transport_patterns": definition.capabilities.transport_patterns,
                "artifact_domains": definition.capabilities.artifact_domains,
                "guardrails": definition.capabilities.guardrails.model_dump(mode="json"),
            },
        )
    return result


def configure_connector_entry(
    connector_name: str,
    *,
    enabled: bool,
    config: dict[str, Any] | None = None,
    base_dir: Path | str | None = None,
) -> tuple[ConnectorRegistryEntry, ConnectorActionResult]:
    definition = get_connector_definition(connector_name)
    stored = cfg.get_connector_entry(definition.name)
    resolved_config = stored["config"] if config is None else dict(config)
    should_validate = enabled or config is not None
    issues = validate_connector_config(definition, resolved_config) if should_validate else []
    summary = (
        f"Connector {definition.name} configured."
        if not issues
        else f"Connector {definition.name} configuration could not be saved."
    )
    result = _build_action_result(
        definition,
        action="configure",
        config=resolved_config,
        issues=issues,
        summary=summary,
    )
    if not issues:
        cfg.set_connector_entry(definition.name, enabled=enabled, config=resolved_config)

    entry = get_connector_registry_entry(definition.name)
    if result.status == "success":
        result.config_summary = entry.config_summary

    if base_dir is not None:
        append_connector_action_event(
            base_dir,
            connector_name=definition.name,
            action="configure",
            outcome=result.outcome,
            status=result.status,
            failure_mode=result.failure_mode,
            external_systems=[definition.external_system],
            details={
                "enabled": enabled,
                "issues": [issue.model_dump(mode="json") for issue in result.issues],
                "config_summary": result.config_summary.model_dump(mode="json") if result.config_summary else None,
                "transport_patterns": definition.capabilities.transport_patterns,
                "artifact_domains": definition.capabilities.artifact_domains,
                "guardrails": definition.capabilities.guardrails.model_dump(mode="json"),
            },
        )
    return entry, result
