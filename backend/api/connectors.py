"""Connector registry and validation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
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


class ConnectorEntryUpdate(BaseModel):
    enabled: bool
    config: dict[str, Any] | None = None


class ConnectorValidationRequest(BaseModel):
    config: dict[str, Any] | None = Field(default=None)


@router.get("/connectors/registry")
def list_connector_registry():
    return {
        "connectors": [entry.model_dump(mode="json") for entry in list_connector_registry_entries()],
    }


@router.get("/connectors/registry/{connector_name}")
def get_connector_registry_detail(connector_name: str):
    try:
        entry = get_connector_registry_entry(connector_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return entry.model_dump(mode="json")


@router.put("/connectors/registry/{connector_name}")
def update_connector_registry_entry(connector_name: str, body: ConnectorEntryUpdate):
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
def validate_connector_registry_entry(connector_name: str, body: ConnectorValidationRequest | None = None):
    request = body or ConnectorValidationRequest()
    try:
        result = validate_connector_entry(
            connector_name,
            config=request.config,
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
):
    request = body or ConnectorActionRequest()
    try:
        result = execute_connector_action(
            connector_name,
            action=action,
            request=request,
            base_dir=_base_dir(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")
