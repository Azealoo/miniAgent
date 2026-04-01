"""Derived study summary endpoints."""

from pathlib import Path

from fastapi import APIRouter, Request

from access_control import require_inspection_access
from graph.studies_workspace import list_studies_workspace

router = APIRouter()


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


@router.get("/studies")
def list_studies(request: Request = None):
    require_inspection_access(request)
    return list_studies_workspace(_base_dir())
