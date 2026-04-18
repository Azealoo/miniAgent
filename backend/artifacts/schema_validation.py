"""Reference-schema validation helpers for BioCompute artifacts."""

from __future__ import annotations

import inspect
import json
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from jsonschema import Draft7Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

IEEE_2791_REFERENCE_SCHEMA_DIR = Path(__file__).resolve().parent / "reference_schemas" / "ieee_2791"
_IEEE_2791_ROOT_SCHEMA_PATH = IEEE_2791_REFERENCE_SCHEMA_DIR / "2791object.json"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_JSONSCHEMA_SUPPORTS_REGISTRY_API = "registry" in inspect.signature(Draft7Validator).parameters


def ieee_2791_bco_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in (
        "object_id",
        "spec_version",
        "etag",
        "provenance_domain",
        "usability_domain",
        "extension_domain",
        "description_domain",
        "execution_domain",
        "parametric_domain",
        "io_domain",
        "error_domain",
    ):
        value = payload.get(key)
        if value is not None:
            projected[key] = value
    return projected


def validate_biocompute_payload_against_reference_schemas(payload: Mapping[str, Any]) -> None:
    if not _JSONSCHEMA_SUPPORTS_REGISTRY_API:
        raise RuntimeError("BioCompute reference-schema validation requires jsonschema>=4.18.0.")

    projected = _prune_none(ieee_2791_bco_projection(payload))
    root_schema = _load_json_schema(_IEEE_2791_ROOT_SCHEMA_PATH)
    Draft7Validator(
        root_schema,
        registry=_ieee_2791_schema_registry(),
        format_checker=FormatChecker(),
    ).validate(projected)

    for index, entry in enumerate(projected.get("extension_domain", [])):
        if not isinstance(entry, Mapping):
            raise ValidationError(f"extension_domain[{index}] must be an object.")
        _validate_extension_entry(entry)


@lru_cache(maxsize=1)
def _ieee_2791_schema_registry() -> Registry:
    registry = Registry()
    for schema_path in sorted(IEEE_2791_REFERENCE_SCHEMA_DIR.glob("*.json")):
        schema = _load_json_schema(schema_path)
        registry = registry.with_resource(schema_path.name, Resource.from_contents(schema))
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    return registry


@lru_cache(maxsize=None)
def _load_json_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_extension_entry(entry: Mapping[str, Any]) -> None:
    extension_schema_url = entry.get("extension_schema")
    if not isinstance(extension_schema_url, str) or not extension_schema_url.strip():
        raise ValidationError("extension_domain entries must include non-empty extension_schema URLs.")

    payload_keys = [key for key in entry.keys() if key != "extension_schema"]
    if len(payload_keys) != 1:
        raise ValidationError(
            "Each extension_domain entry must contain exactly one extension payload alongside extension_schema."
        )

    schema_path = _resolve_local_schema_path_from_public_raw_url(extension_schema_url)
    schema = _load_json_schema(schema_path)
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator_cls(schema, format_checker=FormatChecker()).validate(_prune_none(entry[payload_keys[0]]))


def _resolve_local_schema_path_from_public_raw_url(schema_url: str) -> Path:
    parsed = urlparse(schema_url)
    relative_candidates = parse_qs(parsed.query).get("path", [])
    if not relative_candidates:
        raise ValidationError("extension_schema URLs must include a ?path=... query parameter.")

    relative_path = PurePosixPath(relative_candidates[0])
    if relative_path.is_absolute() or any(part == ".." for part in relative_path.parts):
        raise ValidationError("extension_schema path queries must stay within the backend root.")

    resolved = (_BACKEND_ROOT / relative_path).resolve()
    try:
        resolved.relative_to(_BACKEND_ROOT.resolve())
    except ValueError as exc:
        raise ValidationError("extension_schema path queries must stay within the backend root.") from exc
    if not resolved.exists():
        raise ValidationError(f"extension_schema target does not exist: {relative_path}")
    return resolved


def _prune_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _prune_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_prune_none(item) for item in value]
    return value
