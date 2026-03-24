"""Shared route-access helpers for production hardening."""

from __future__ import annotations

import os
import secrets
from typing import Literal

from fastapi import HTTPException, Request

import config as cfg

_LOCALHOST_CLIENTS = {"127.0.0.1", "::1", "localhost"}
AccessScope = Literal["inspection", "execution", "admin"]
AccessGrantMode = Literal["loopback", "bearer"]


def is_loopback_client(request: Request | None) -> bool:
    client = request.client if request is not None else None
    host = client.host if client is not None else None
    return host in _LOCALHOST_CLIENTS


def _configured_token(scope: AccessScope) -> tuple[str | None, str | None]:
    policy = cfg.get_production_hardening_policy()
    env_var = policy.api.execution_bearer_token_env_var
    if scope == "inspection":
        env_var = policy.api.inspection_bearer_token_env_var
    elif scope == "admin":
        env_var = policy.api.admin_bearer_token_env_var
    if env_var is None:
        return None, None
    return env_var, os.getenv(env_var, "").strip() or None


def _authorization_bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    cleaned = token.strip()
    return cleaned or None


def determine_route_access_mode(
    request: Request | None,
    *,
    scope: AccessScope,
) -> AccessGrantMode | None:
    # Route unit tests call handlers directly without an ASGI Request; only enforce
    # the network-layer access policy when an actual HTTP request is present.
    if request is None:
        return None

    policy = cfg.get_production_hardening_policy()
    if policy.api.allow_loopback_without_auth and is_loopback_client(request):
        return "loopback"

    env_var, expected_token = _configured_token(scope)
    if env_var is None:
        raise HTTPException(403, "This route requires local access or a configured bearer token.")
    if expected_token is None:
        raise HTTPException(503, f"Configured bearer token environment variable {env_var} is empty.")

    presented_token = _authorization_bearer_token(request)
    if presented_token is None or not secrets.compare_digest(presented_token, expected_token):
        raise HTTPException(401, "Bearer token required.")
    return "bearer"


def require_route_access(
    request: Request | None,
    *,
    scope: AccessScope,
) -> None:
    determine_route_access_mode(request, scope=scope)


def require_execution_access(request: Request | None) -> None:
    require_route_access(request, scope="execution")


def require_inspection_access(request: Request | None) -> None:
    require_route_access(request, scope="inspection")


def require_admin_access(request: Request | None) -> None:
    require_route_access(request, scope="admin")


__all__ = [
    "AccessGrantMode",
    "AccessScope",
    "determine_route_access_mode",
    "is_loopback_client",
    "require_admin_access",
    "require_execution_access",
    "require_inspection_access",
    "require_route_access",
]
