"""Connector registry and validation endpoints."""

from __future__ import annotations

from typing import Any

from access_control import require_admin_access, require_inspection_access
import config as cfg
from audit.store import append_connector_action_event
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from connectors.models import ConnectorActionRequest, ConnectorExecutionAction
from connectors.registry import (
    configure_connector_entry,
    get_connector_registry_entry,
    list_connector_registry_entries,
    validate_connector_entry,
)
from connectors.runtime import execute_connector_action

router = APIRouter()


def _base_dir():
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _policy_blocked(connector_name: str, *, action: str, policy_key: str) -> None:
    append_connector_action_event(
        _base_dir(),
        connector_name=connector_name,
        action=action,
        outcome="blocked",
        status="blocked",
        failure_mode="policy_disabled",
        details={"policy_key": policy_key},
    )
    raise HTTPException(403, f"{action} is disabled by production hardening policy.")


class ConnectorEntryUpdate(BaseModel):
    enabled: bool
    config: dict[str, Any] | None = None


class ConnectorValidationRequest(BaseModel):
    config: dict[str, Any] | None = Field(default=None)


@router.get("/connectors/registry")
def list_connector_registry(request: Request = None):
    require_inspection_access(request)
    return {
        "connectors": [entry.model_dump(mode="json") for entry in list_connector_registry_entries()],
    }


@router.get("/connectors/registry/{connector_name}")
def get_connector_registry_detail(connector_name: str, request: Request = None):
    require_inspection_access(request)
    try:
        entry = get_connector_registry_entry(connector_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return entry.model_dump(mode="json")


@router.get("/connectors/registry/{connector_name}/admin-detail")
def get_connector_registry_admin_detail(
    connector_name: str,
    request: Request = None,
):
    require_admin_access(request)
    try:
        entry = get_connector_registry_entry(connector_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    stored = cfg.get_connector_entry(entry.name)
    return {
        "connector_name": entry.name,
        "enabled": stored["enabled"],
        "config": stored["config"],
        "validation_result": entry.validation_result.model_dump(mode="json"),
    }


@router.put("/connectors/registry/{connector_name}")
def update_connector_registry_entry(
    connector_name: str,
    body: ConnectorEntryUpdate,
    request: Request = None,
):
    require_admin_access(request)
    policy = cfg.get_production_hardening_policy()
    if not policy.api.connectors_configuration_enabled:
        _policy_blocked(
            connector_name,
            action="configure",
            policy_key="production_hardening.api.connectors_configuration_enabled",
        )
    try:
        entry, result = configure_connector_entry(
            connector_name,
            enabled=body.enabled,
            config=body.config,
            base_dir=_base_dir(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result.status == "failed":
        raise HTTPException(status_code=400, detail=result.model_dump(mode="json"))
    return {
        "connector": entry.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }


@router.post("/connectors/registry/{connector_name}/validate")
def validate_connector_registry_entry(
    connector_name: str,
    body: ConnectorValidationRequest | None = None,
    request: Request = None,
):
    require_admin_access(request)
    request_body = body or ConnectorValidationRequest()
    try:
        result = validate_connector_entry(
            connector_name,
            config=request_body.config,
            base_dir=_base_dir(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/connectors/registry/{connector_name}/actions/{action}")
def run_connector_registry_action(
    connector_name: str,
    action: ConnectorExecutionAction,
    body: ConnectorActionRequest | None = None,
    request: Request = None,
):
    require_admin_access(request)
    policy = cfg.get_production_hardening_policy()
    if not policy.api.connectors_runtime_actions_enabled:
        _policy_blocked(
            connector_name,
            action=action,
            policy_key="production_hardening.api.connectors_runtime_actions_enabled",
        )
    request_body = body or ConnectorActionRequest()
    try:
        result = execute_connector_action(
            connector_name,
            action=action,
            request=request_body,
            base_dir=_base_dir(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")
