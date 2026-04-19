from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RuntimeConfigLayerName = Literal["defaults", "user", "project", "env", "local"]


@dataclass(frozen=True)
class RuntimeConfigLayer:
    name: RuntimeConfigLayerName
    path: str | None
    exists: bool
    applied: bool
    keys: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfigFieldProvenance:
    """Provenance for one effective leaf field in the merged runtime config."""

    value: Any
    source_layer: RuntimeConfigLayerName
    path: str | None


@dataclass(frozen=True)
class LoadedRuntimeConfig:
    data: dict[str, Any]
    layers: tuple[RuntimeConfigLayer, ...]
    field_provenance: dict[str, RuntimeConfigFieldProvenance]
