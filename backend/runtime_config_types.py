from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RuntimeConfigLayerName = Literal["defaults", "user", "project", "local"]


@dataclass(frozen=True)
class RuntimeConfigLayer:
    name: RuntimeConfigLayerName
    path: str | None
    exists: bool
    applied: bool
    keys: tuple[str, ...]


@dataclass(frozen=True)
class LoadedRuntimeConfig:
    data: dict[str, Any]
    layers: tuple[RuntimeConfigLayer, ...]
