"""Artifact registry lookup and rebuild endpoints."""

from pathlib import Path

from fastapi import APIRouter, Request

from access_control import require_admin_access, require_inspection_access
from artifacts.registry import lookup_artifact_registry, rebuild_artifact_registry

router = APIRouter()


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


@router.get("/artifacts/registry")
def list_artifact_registry(
    run_id: str | None = None,
    artifact_type: str | None = None,
    workflow: str | None = None,
    date: str | None = None,
    dataset_id: str | None = None,
    include_invalid: bool = False,
    request: Request = None,
):
    require_inspection_access(request)
    result = lookup_artifact_registry(
        _base_dir(),
        run_id=run_id,
        artifact_type=artifact_type,
        workflow=workflow,
        date=date,
        dataset_id=dataset_id,
        include_invalid=include_invalid,
    )
    return result.model_dump(mode="json")


@router.post("/artifacts/registry/rebuild")
def rebuild_registry(request: Request = None):
    require_admin_access(request)
    snapshot = rebuild_artifact_registry(_base_dir())
    return snapshot.model_dump(mode="json")
