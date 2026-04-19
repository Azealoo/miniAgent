from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from runtime_config_types import (
    LoadedRuntimeConfig,
    RuntimeConfigFieldProvenance,
    RuntimeConfigLayer,
    RuntimeConfigLayerName,
)

USER_CONFIG_ENV_VAR = "BIOAPEX_USER_CONFIG"
PROJECT_CONFIG_ENV_VAR = "BIOAPEX_PROJECT_CONFIG"
LOCAL_CONFIG_ENV_VAR = "BIOAPEX_LOCAL_CONFIG"
ENV_PROFILE_ENV_VAR = "BIOAPEX_ENV"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _iter_leaves(prefix: str, value: Any):
    """Yield (dotted_path, leaf_value) for every leaf reachable from value."""
    if isinstance(value, dict):
        for key, child in value.items():
            sub = f"{prefix}.{key}" if prefix else key
            yield from _iter_leaves(sub, child)
    else:
        yield prefix, value


def _apply_overlay_with_provenance(
    merged: dict[str, Any],
    overlay: dict[str, Any],
    provenance: dict[str, RuntimeConfigFieldProvenance],
    *,
    layer_name: RuntimeConfigLayerName,
    layer_path: str | None,
    prefix: str = "",
) -> None:
    """Merge ``overlay`` into ``merged`` while recording leaf-level provenance.

    A "leaf" is any non-dict value. When a later layer replaces a previous leaf
    or a whole subtree, its provenance entries supersede the earlier layer's.
    """

    for key, overlay_value in overlay.items():
        sub_prefix = f"{prefix}.{key}" if prefix else key
        current = merged.get(key)

        if isinstance(overlay_value, dict) and isinstance(current, dict):
            _apply_overlay_with_provenance(
                current,
                overlay_value,
                provenance,
                layer_name=layer_name,
                layer_path=layer_path,
                prefix=sub_prefix,
            )
            continue

        # The overlay replaces the current value wholesale. Drop any previous
        # provenance entries rooted at this path so stale child leaves do not
        # survive a type change (e.g. dict → scalar) or a scalar → dict swap.
        provenance.pop(sub_prefix, None)
        stale_children = [
            existing for existing in provenance if existing.startswith(sub_prefix + ".")
        ]
        for existing in stale_children:
            provenance.pop(existing, None)

        merged[key] = copy.deepcopy(overlay_value)

        for leaf_path, leaf_value in _iter_leaves(sub_prefix, overlay_value):
            provenance[leaf_path] = RuntimeConfigFieldProvenance(
                value=copy.deepcopy(leaf_value),
                source_layer=layer_name,
                path=layer_path,
            )


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


def resolve_runtime_config_paths(project_config_path: Path) -> dict[str, Path | None]:
    project_path = Path(
        os.getenv(PROJECT_CONFIG_ENV_VAR, str(project_config_path))
    ).expanduser()
    default_local_path = project_path.with_name("config.local.json")

    env_profile = os.getenv(ENV_PROFILE_ENV_VAR, "").strip()
    env_path: Path | None = (
        project_path.with_name(f"config.{env_profile}.json") if env_profile else None
    )

    return {
        "user": Path(
            os.getenv(
                USER_CONFIG_ENV_VAR,
                str(Path.home() / ".codex" / "bioapex" / "config.json"),
            )
        ).expanduser(),
        "project": project_path,
        "env": env_path,
        "local": Path(
            os.getenv(LOCAL_CONFIG_ENV_VAR, str(default_local_path))
        ).expanduser(),
    }


def load_runtime_config(
    *,
    default_config: dict[str, Any],
    project_config_path: Path,
) -> LoadedRuntimeConfig:
    merged: dict[str, Any] = {}
    provenance: dict[str, RuntimeConfigFieldProvenance] = {}

    _apply_overlay_with_provenance(
        merged,
        default_config,
        provenance,
        layer_name="defaults",
        layer_path=None,
    )

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

    for layer_name in ("user", "project", "env", "local"):
        path = paths[layer_name]
        if path is None:
            # The env layer is only active when BIOAPEX_ENV is set; otherwise
            # skip it entirely so it does not appear in provenance or layers.
            continue
        payload = _load_json_object(path)
        if payload:
            _apply_overlay_with_provenance(
                merged,
                payload,
                provenance,
                layer_name=layer_name,  # type: ignore[arg-type]
                layer_path=str(path),
            )
        layers.append(
            RuntimeConfigLayer(
                name=layer_name,  # type: ignore[arg-type]
                path=str(path),
                exists=path.exists(),
                applied=bool(payload),
                keys=tuple(sorted(payload.keys())),
            )
        )

    return LoadedRuntimeConfig(
        data=merged,
        layers=tuple(layers),
        field_provenance=provenance,
    )
