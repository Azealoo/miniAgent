from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from runtime_config_types import LoadedRuntimeConfig, RuntimeConfigLayer

USER_CONFIG_ENV_VAR = "BIOAPEX_USER_CONFIG"
PROJECT_CONFIG_ENV_VAR = "BIOAPEX_PROJECT_CONFIG"
LOCAL_CONFIG_ENV_VAR = "BIOAPEX_LOCAL_CONFIG"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}
    return payload


def resolve_runtime_config_paths(project_config_path: Path) -> dict[str, Path]:
    project_path = Path(
        os.getenv(PROJECT_CONFIG_ENV_VAR, str(project_config_path))
    ).expanduser()
    default_local_path = project_path.with_name("config.local.json")
    return {
        "user": Path(
            os.getenv(
                USER_CONFIG_ENV_VAR,
                str(Path.home() / ".codex" / "bioapex" / "config.json"),
            )
        ).expanduser(),
        "project": project_path,
        "local": Path(
            os.getenv(LOCAL_CONFIG_ENV_VAR, str(default_local_path))
        ).expanduser(),
    }


def load_runtime_config(
    *,
    default_config: dict[str, Any],
    project_config_path: Path,
) -> LoadedRuntimeConfig:
    merged = copy.deepcopy(default_config)
    paths = resolve_runtime_config_paths(project_config_path)
    layers: list[RuntimeConfigLayer] = [
        RuntimeConfigLayer(
            name="defaults",
            path=None,
            exists=True,
            applied=True,
            keys=tuple(sorted(default_config.keys())),
        )
    ]

    for layer_name in ("user", "project", "local"):
        path = paths[layer_name]
        payload = _load_json_object(path)
        if payload:
            merged = _deep_merge(merged, payload)
        layers.append(
            RuntimeConfigLayer(
                name=layer_name,  # type: ignore[arg-type]
                path=str(path),
                exists=path.exists(),
                applied=bool(payload),
                keys=tuple(sorted(payload.keys())),
            )
        )

    return LoadedRuntimeConfig(data=merged, layers=tuple(layers))
