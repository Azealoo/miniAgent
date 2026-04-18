"""Operator-facing config inspection endpoints.

GET /api/config/effective — return the active hardening posture, every
derived flag that the posture expands into, per-layer provenance from
`runtime_config_types.LoadedRuntimeConfig`, per-field provenance
(``{field_path: {value, source_layer, path}}``) derived from the same
merge, and the resolved role→model mapping (executor/planner/verifier/title)
with api_key redacted. Requires admin access so remote operators cannot
probe bearer-token env-var names or other sensitive settings anonymously.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, get_args

from access_control import require_admin_access
from fastapi import APIRouter, Request

import config as cfg
from runtime.model_factory import ModelRole, get_role_model_config

router = APIRouter()

_ROLE_ORDER: tuple[ModelRole, ...] = get_args(ModelRole)


def _serialize_layer(layer: Any) -> dict[str, Any]:
    payload = asdict(layer)
    payload["keys"] = list(payload.get("keys", ()))
    return payload


def _serialize_field_provenance(
    provenance: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        field_path: {
            "value": entry.value,
            "source_layer": entry.source_layer,
            "path": entry.path,
        }
        for field_path, entry in sorted(provenance.items())
    }


def _serialize_resolved_role_models() -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for role in _ROLE_ORDER:
        settings = get_role_model_config(role)
        resolved[role] = {
            "provider": settings.provider,
            "model": settings.model,
            "base_url": settings.base_url,
            "temperature": settings.temperature,
            "streaming": settings.streaming,
            "seed": settings.seed,
        }
    return resolved


@router.get("/config/effective")
def get_effective_config(request: Request = None):
    require_admin_access(request)
    loaded = cfg.get_loaded_runtime_config()
    policy = cfg.get_production_hardening_policy()
    return {
        "production_hardening": {
            "posture": policy.posture,
            "host_binding": policy.host_binding,
            "approval_threshold": policy.approval_threshold,
            "file_write_whitelist": list(policy.file_write_whitelist),
            "tools": policy.tools.model_dump(),
            "api": policy.api.model_dump(),
        },
        "config_layers": [_serialize_layer(layer) for layer in loaded.layers],
        "field_provenance": _serialize_field_provenance(loaded.field_provenance),
        "resolved_role_models": _serialize_resolved_role_models(),
    }
