"""Access inspection endpoints for frontend auth and capability bootstrapping."""

from __future__ import annotations

from typing import Literal

from access_control import determine_route_access_mode
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/access/probe")
def probe_route_access(
    scope: Literal["inspection", "execution", "admin"],
    request: Request,
):
    authorization_mode = determine_route_access_mode(request, scope=scope)
    return {
        "scope": scope,
        "authorization_mode": authorization_mode,
    }
