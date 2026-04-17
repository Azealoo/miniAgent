"""
Typed memory document schema.

Every markdown file under backend/memory/{project,user,agent}/ may carry a YAML
frontmatter block. When present, the block must satisfy this schema:

    ---
    type: <one of TYPED_MEMORY_TYPE_VALUES>     # required
    name: <human-readable short title>           # required, non-empty
    description: <one-line summary>              # required, non-empty
    kind: project | user | agent                 # optional; inferred from path
    scope: session | project | user | global     # optional; defaults by kind
    tags: [tag-a, tag-b]                         # optional flat list of strings
    pinned: true | false                         # optional; default false
    updated_at: 2026-04-17T00:00:00Z             # optional ISO-8601
    ---

Semantics:

    * `type`  — fine-grained taxonomy used by retrieval labelling and
      distillation routing. One of TYPED_MEMORY_TYPE_VALUES.
    * `kind`  — coarse axis aligned with the on-disk layout. When omitted,
      it is inferred from the directory: memory/project/... -> 'project',
      memory/user/... -> 'user', memory/agent/... -> 'agent'.
    * `scope` — applicability. Defaults track `kind` (project->project,
      user->user, agent->global). `session` denotes a scratch-pad tied to
      the originating session.
    * `tags`  — freeform, flat, lowercase tokens. No controlled vocabulary.
    * `pinned` / `updated_at` — already consumed by the scoped-memory listing
      in prompt_builder.py; now also carried on parsed metadata for symmetry
      and so that `validate_memory_write` / retrieval filters can reason
      about them.

Files without frontmatter remain valid (legacy notes); they are just excluded
from typed filtering. Malformed frontmatter is rejected by
`validate_memory_write` on every write, and logged (not fatal) by the
MemoryIndexer at startup rebuild so the backend still boots.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TYPED_MEMORY_TYPE_VALUES = (
    "user_preference",
    "project_fact",
    "workflow_heuristic",
    "scientific_reference",
    "session_distillation",
)

TYPED_MEMORY_KIND_VALUES = ("project", "user", "agent")
TYPED_MEMORY_SCOPE_VALUES = ("session", "project", "user", "global")

_MARKDOWN_MEMORY_SUFFIXES = {".md", ".markdown"}
_TYPED_MEMORY_REQUIRED_FIELDS = ("type", "name", "description")

# kind -> default scope when scope is omitted
_DEFAULT_SCOPE_FOR_KIND = {
    "project": "project",
    "user": "user",
    "agent": "global",
}


@dataclass(frozen=True)
class TypedMemoryMetadata:
    memory_type: str
    name: str
    description: str
    kind: str | None = None
    scope: str | None = None
    tags: tuple[str, ...] = ()
    pinned: bool = False
    updated_at: str | None = None


@dataclass(frozen=True)
class ParsedMemoryDocument:
    source: str
    body: str
    metadata: TypedMemoryMetadata | None = None
    frontmatter_present: bool = False
    errors: tuple[str, ...] = ()

    @property
    def is_typed(self) -> bool:
        return self.metadata is not None and not self.errors


def display_memory_type(memory_type: str) -> str:
    return memory_type.replace("_", " ")


def normalize_memory_type(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    normalized = " ".join(str(raw_value).strip().lower().replace("-", " ").split())
    return normalized.replace(" ", "_")


def _normalize_enum_value(raw_value: Any) -> str:
    if raw_value is None:
        return ""
    return str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")


def infer_kind_from_source(source: str) -> str | None:
    """Infer `kind` from a memory file's relative path, e.g. memory/project/... -> 'project'."""
    parts = Path(source).parts
    if len(parts) < 2 or parts[0] != "memory":
        return None
    candidate = parts[1]
    return candidate if candidate in TYPED_MEMORY_KIND_VALUES else None


def _coerce_tags(raw_value: Any) -> tuple[tuple[str, ...], str | None]:
    """Return (normalized_tags, error). Missing value -> ((), None)."""
    if raw_value is None:
        return (), None
    if isinstance(raw_value, str):
        return (), "Typed memory frontmatter `tags` must be a list of strings, not a string."
    if not isinstance(raw_value, list):
        return (), "Typed memory frontmatter `tags` must be a list of strings."
    cleaned: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            return (), "Typed memory frontmatter `tags` must be a list of strings."
        token = item.strip().lower()
        if token and token not in cleaned:
            cleaned.append(token)
    return tuple(cleaned), None


def _coerce_pinned(raw_value: Any) -> tuple[bool, str | None]:
    if raw_value is None:
        return False, None
    if isinstance(raw_value, bool):
        return raw_value, None
    return False, "Typed memory frontmatter `pinned` must be a boolean."


def _coerce_updated_at(raw_value: Any) -> tuple[str | None, str | None]:
    from datetime import date, datetime

    if raw_value is None:
        return None, None
    # PyYAML decodes bare ISO timestamps to datetime/date; accept and stringify.
    if isinstance(raw_value, datetime):
        return raw_value.isoformat(), None
    if isinstance(raw_value, date):
        return raw_value.isoformat(), None
    if not isinstance(raw_value, str):
        return None, "Typed memory frontmatter `updated_at` must be an ISO-8601 string."
    value = raw_value.strip()
    if not value:
        return None, None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return None, "Typed memory frontmatter `updated_at` must be an ISO-8601 string."
    return value, None


def _split_markdown_frontmatter(
    content: str,
) -> tuple[dict[str, Any] | None, str, bool, str | None]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, content, False, None

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue

        frontmatter_text = "\n".join(lines[1:index])
        body = "\n".join(lines[index + 1 :]).strip()
        try:
            payload = yaml.safe_load(frontmatter_text) or {}
        except Exception as exc:
            return None, body, True, f"Typed memory frontmatter is not valid YAML: {exc}"

        if not isinstance(payload, dict):
            return None, body, True, "Typed memory frontmatter must be a YAML mapping."

        return payload, body, True, None

    return (
        None,
        content,
        True,
        "Typed memory frontmatter is missing a closing --- delimiter.",
    )


def parse_memory_document(source: str, content: str) -> ParsedMemoryDocument:
    suffix = Path(source).suffix.lower()
    frontmatter_present = False
    frontmatter: dict[str, Any] | None = None
    body = content.strip()
    errors: list[str] = []

    if suffix in _MARKDOWN_MEMORY_SUFFIXES:
        frontmatter, body, frontmatter_present, parse_error = _split_markdown_frontmatter(
            content
        )
        body = body.strip()
        if parse_error:
            errors.append(parse_error)

    metadata: TypedMemoryMetadata | None = None
    if frontmatter_present and not errors:
        missing_fields = [
            field_name
            for field_name in _TYPED_MEMORY_REQUIRED_FIELDS
            if frontmatter.get(field_name) is None
            or not str(frontmatter.get(field_name, "")).strip()
        ]
        if missing_fields:
            errors.append(
                "Typed memory frontmatter requires non-empty fields: "
                + ", ".join(missing_fields)
                + "."
            )
        else:
            memory_type = normalize_memory_type(frontmatter.get("type"))
            if memory_type not in TYPED_MEMORY_TYPE_VALUES:
                errors.append(
                    "Typed memory frontmatter type must be one of: "
                    + ", ".join(TYPED_MEMORY_TYPE_VALUES)
                    + "."
                )
            else:
                kind_raw = frontmatter.get("kind")
                kind: str | None
                if kind_raw is None:
                    kind = infer_kind_from_source(source)
                else:
                    kind = _normalize_enum_value(kind_raw)
                    if kind not in TYPED_MEMORY_KIND_VALUES:
                        errors.append(
                            "Typed memory frontmatter `kind` must be one of: "
                            + ", ".join(TYPED_MEMORY_KIND_VALUES)
                            + "."
                        )
                        kind = None

                scope_raw = frontmatter.get("scope")
                scope: str | None
                if scope_raw is None:
                    scope = _DEFAULT_SCOPE_FOR_KIND.get(kind) if kind else None
                else:
                    scope = _normalize_enum_value(scope_raw)
                    if scope not in TYPED_MEMORY_SCOPE_VALUES:
                        errors.append(
                            "Typed memory frontmatter `scope` must be one of: "
                            + ", ".join(TYPED_MEMORY_SCOPE_VALUES)
                            + "."
                        )
                        scope = None

                tags, tags_error = _coerce_tags(frontmatter.get("tags"))
                if tags_error:
                    errors.append(tags_error)

                pinned, pinned_error = _coerce_pinned(frontmatter.get("pinned"))
                if pinned_error:
                    errors.append(pinned_error)

                updated_at, updated_at_error = _coerce_updated_at(
                    frontmatter.get("updated_at")
                )
                if updated_at_error:
                    errors.append(updated_at_error)

                if not errors:
                    metadata = TypedMemoryMetadata(
                        memory_type=memory_type,
                        name=str(frontmatter["name"]).strip(),
                        description=str(frontmatter["description"]).strip(),
                        kind=kind,
                        scope=scope,
                        tags=tags,
                        pinned=pinned,
                        updated_at=updated_at,
                    )

    return ParsedMemoryDocument(
        source=source,
        body=body,
        metadata=metadata,
        frontmatter_present=frontmatter_present,
        errors=tuple(errors),
    )


def validate_memory_write(path: str, content: str) -> tuple[str, ...]:
    clean_path = path.strip().lstrip("/").removeprefix("./")
    if not clean_path.startswith("memory/") or clean_path == "memory/MEMORY.md":
        return ()

    if Path(clean_path).suffix.lower() not in _MARKDOWN_MEMORY_SUFFIXES:
        return ()

    parsed = parse_memory_document(clean_path, content)
    if not parsed.frontmatter_present:
        return ()
    return parsed.errors
