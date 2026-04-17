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
_MARKDOWN_MEMORY_SUFFIXES = {".md", ".markdown"}
_TYPED_MEMORY_REQUIRED_FIELDS = ("type", "name", "description")


@dataclass(frozen=True)
class TypedMemoryMetadata:
    memory_type: str
    name: str
    description: str


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
            field
            for field in _TYPED_MEMORY_REQUIRED_FIELDS
            if frontmatter.get(field) is None or not str(frontmatter.get(field, "")).strip()
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
                metadata = TypedMemoryMetadata(
                    memory_type=memory_type,
                    name=str(frontmatter["name"]).strip(),
                    description=str(frontmatter["description"]).strip(),
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
