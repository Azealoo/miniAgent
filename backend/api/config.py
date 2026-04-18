"""Operator-facing config inspection endpoints.

GET /api/config/effective — return the active hardening posture, every
derived flag that the posture expands into, and per-layer provenance from
`runtime_config_types.LoadedRuntimeConfig`. Requires inspection access so
remote operators cannot probe bearer-token env-var names anonymously.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from access_control import require_inspection_access
from fastapi import APIRouter, Request

import config as cfg

router = APIRouter()


def _serialize_layer(layer: Any) -> dict[str, Any]:
    payload = asdict(layer)
    payload["keys"] = list(payload.get("keys", ()))
    return payload


@router.get("/config/effective")
def get_effective_config(request: Request = None):
    require_inspection_access(request)
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
    }
