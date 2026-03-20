"""File-first artifact registry for canonical BioAPEX artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .naming import (
    CONTENT_HASH_MANIFEST_FILENAME,
    GENERATED_OUTPUTS_DIR,
    RUN_RECORD_FILENAME,
    USER_INPUTS_DIR,
    compute_content_hash,
    is_valid_run_id,
)
from .schemas import ArtifactDocument, WorkflowRun, load_artifact_document

ARTIFACT_REGISTRY_SCHEMA_VERSION = "1.0.0"
ARTIFACT_REGISTRY_DIR = PurePosixPath("storage/artifact_registry")
ARTIFACT_REGISTRY_FILENAME = "registry.json"
ARTIFACT_REGISTRY_PATH = ARTIFACT_REGISTRY_DIR / ARTIFACT_REGISTRY_FILENAME

_CANONICAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".tif", ".tiff"}
_REFERENCE_LIST_FIELDS = ("related_artifacts", "inputs", "outputs", "checklist_artifacts")

_SCHEMA_ARTIFACT_TYPES = {
    "dataset_manifest",
    "count_matrix",
    "normalized_count_matrix",
    "differential_expression_results",
    "differential_expression_run",
    "workflow_run",
    "provenance",
    "biocompute",
    "evidence_card",
    "evidence_review",
    "entity_grounding",
    "compliance_report",
    "protocol_run",
    "qa_report",
}
_STRUCTURED_ROOT_ARTIFACT_TYPES = {"content_hash_manifest", "workflow_plan", "provenance"}
_ROOT_STABLE_FILENAMES_TO_TYPES: dict[str, str] = {
    RUN_RECORD_FILENAME: "workflow_run",
    CONTENT_HASH_MANIFEST_FILENAME: "content_hash_manifest",
    "dataset_manifest.yaml": "dataset_manifest",
    "count_matrix.json": "count_matrix",
    "normalized_count_matrix.json": "normalized_count_matrix",
    "differential_expression_results.json": "differential_expression_results",
    "differential_expression_run.json": "differential_expression_run",
    "workflow_plan.json": "workflow_plan",
    "compliance_report.json": "compliance_report",
    "evidence_card.yaml": "evidence_card",
    "evidence_review.json": "evidence_review",
    "entity_grounding.json": "entity_grounding",
    "protocol_run.yaml": "protocol_run",
    "qa_report.json": "qa_report",
    "prov.json": "provenance",
    "biocompute.json": "biocompute",
    "ro-crate": "ro_crate",
}


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Timestamps must include timezone information.")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _normalize_relative_path(path: str | PurePosixPath) -> str:
    raw = str(path).strip()
    if not raw:
        raise ValueError("Path must not be empty.")
    if "\\" in raw:
        raise ValueError("Paths must use forward slashes.")

    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise ValueError("Paths must be relative, not absolute.")
    if candidate.parts == (".",):
        raise ValueError("Paths must not resolve to '.'.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Paths must not contain '..'.")
    return str(candidate)


def _parse_timestamp(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    candidate = raw_value.strip()
    if not candidate:
        return None
    try:
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return _normalize_timestamp(parsed)


def _timestamp_from_run_id(run_id: str | None) -> datetime | None:
    if not run_id or not is_valid_run_id(run_id):
        return None
    stamp = run_id[len("run-") : len("run-") + 16]
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _timestamp_from_stat(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0)


def _clean_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _artifacts_root(base_dir: Path) -> Path:
    return base_dir / "artifacts"


def _registry_file(base_dir: Path) -> Path:
    return base_dir / ARTIFACT_REGISTRY_PATH


def _infer_artifact_type(
    artifact_relative_path: PurePosixPath,
    *,
    is_dir: bool,
) -> str:
    if len(artifact_relative_path.parts) == 1:
        root_name = artifact_relative_path.name
        if root_name in _ROOT_STABLE_FILENAMES_TO_TYPES:
            return _ROOT_STABLE_FILENAMES_TO_TYPES[root_name]

    if artifact_relative_path.parts[:2] == USER_INPUTS_DIR.parts:
        return "user_input"

    if artifact_relative_path.parts[:2] == GENERATED_OUTPUTS_DIR.parts:
        if is_dir:
            return "generated_output_group"
        if artifact_relative_path.suffix.lower() in _IMAGE_EXTENSIONS:
            return "figure"
        return "generated_output"

    if artifact_relative_path.parts and artifact_relative_path.parts[0] == "ro-crate":
        if len(artifact_relative_path.parts) == 1:
            return "ro_crate"
        return "ro_crate_entry"

    return "artifact_directory" if is_dir else "artifact_file"


@dataclass(frozen=True)
class ArtifactPathContext:
    relative_path: str
    workflow: str | None
    run_date: str | None
    run_id: str | None
    filename: str
    artifact_relative_path: PurePosixPath | None
    inferred_artifact_type: str | None
    is_canonical: bool
    error: str | None

    @property
    def run_dir(self) -> PurePosixPath | None:
        if not self.is_canonical or self.workflow is None or self.run_date is None or self.run_id is None:
            return None
        return PurePosixPath("artifacts") / self.workflow / self.run_date / self.run_id


class ArtifactRegistryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    declared_id: str | None = None
    artifact_type: str
    path: str
    hash: str | None = None
    created_at: datetime | None = None
    run_id: str
    workflow: str
    date: str
    source_workflow: str | None = None
    source_tool: str | None = None
    dataset_id: str | None = None
    status: Literal["valid", "invalid"]
    error: str | None = None
    indexed_at: datetime = Field(default_factory=_now_utc)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _normalize_relative_path(value)

    @field_validator("created_at", "indexed_at")
    @classmethod
    def _validate_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _normalize_timestamp(value)


class ArtifactRegistrySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=ARTIFACT_REGISTRY_SCHEMA_VERSION)
    generated_at: datetime = Field(default_factory=_now_utc)
    artifact_root: str = "artifacts"
    registry_path: str = str(ARTIFACT_REGISTRY_PATH)
    record_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    records: list[ArtifactRegistryRecord] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value)


class ArtifactRegistryLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    artifact_root: str
    registry_path: str
    total_count: int
    matched_count: int
    valid_count: int
    invalid_count: int
    records: list[ArtifactRegistryRecord]

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value)


def _path_context(
    relative_path: str | PurePosixPath,
    *,
    is_dir: bool = False,
) -> ArtifactPathContext:
    normalized = _normalize_relative_path(relative_path)
    candidate = PurePosixPath(normalized)
    parts = candidate.parts
    filename = parts[-1] if parts else ""

    if len(parts) < 5 or parts[0] != "artifacts":
        return ArtifactPathContext(
            relative_path=normalized,
            workflow=None,
            run_date=None,
            run_id=None,
            filename=filename,
            artifact_relative_path=None,
            inferred_artifact_type=None,
            is_canonical=False,
            error="Artifact path must live under artifacts/<workflow>/<YYYY-MM-DD>/<run_id>/...",
        )

    workflow, run_date, run_id = parts[1], parts[2], parts[3]
    artifact_relative_path = PurePosixPath(*parts[4:])
    inferred_artifact_type = _infer_artifact_type(artifact_relative_path, is_dir=is_dir)

    if _CANONICAL_DATE_RE.fullmatch(run_date) is None:
        return ArtifactPathContext(
            relative_path=normalized,
            workflow=workflow,
            run_date=run_date,
            run_id=run_id,
            filename=filename,
            artifact_relative_path=artifact_relative_path,
            inferred_artifact_type=inferred_artifact_type,
            is_canonical=False,
            error=f"Invalid run date segment: {run_date!r}.",
        )

    if not is_valid_run_id(run_id):
        return ArtifactPathContext(
            relative_path=normalized,
            workflow=workflow,
            run_date=run_date,
            run_id=run_id,
            filename=filename,
            artifact_relative_path=artifact_relative_path,
            inferred_artifact_type=inferred_artifact_type,
            is_canonical=False,
            error=f"Invalid run_id path segment: {run_id!r}.",
        )

    return ArtifactPathContext(
        relative_path=normalized,
        workflow=workflow,
        run_date=run_date,
        run_id=run_id,
        filename=filename,
        artifact_relative_path=artifact_relative_path,
        inferred_artifact_type=inferred_artifact_type,
        is_canonical=True,
        error=None,
    )


def _build_fallback_artifact_id(context: ArtifactPathContext) -> str:
    if context.inferred_artifact_type and context.run_id:
        if (
            context.artifact_relative_path is not None
            and (
                len(context.artifact_relative_path.parts) > 1
                or context.artifact_relative_path.name not in _ROOT_STABLE_FILENAMES_TO_TYPES
            )
        ):
            suffix = str(context.artifact_relative_path).replace("/", ":")
            return f"{context.inferred_artifact_type}:{context.run_id}:{suffix}"
        return f"{context.inferred_artifact_type}:{context.run_id}"
    return context.relative_path.replace("/", ":")


def _load_raw_artifact_payload(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        return None, str(exc)
    except OSError as exc:
        return None, str(exc)

    try:
        if path.suffix == ".json":
            payload = json.loads(raw_text)
        elif path.suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(raw_text)
        else:
            return None, f"Unsupported artifact file extension: {path.suffix!r}."
    except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
        return None, str(exc)

    if not isinstance(payload, dict):
        return None, "Artifact documents must deserialize to a mapping."
    return payload, None


def _compute_directory_hash(directory: Path) -> str:
    entries: list[dict[str, str]] = []
    for child in sorted(p for p in directory.rglob("*") if p.is_file()):
        entries.append(
            {
                "path": child.relative_to(directory).as_posix(),
                "hash": compute_content_hash(child.read_bytes()),
            }
        )
    payload = json.dumps(entries, sort_keys=True)
    return compute_content_hash(payload)


def _extract_declared_dataset_id(payload: dict[str, Any], artifact_type: str) -> str | None:
    if artifact_type == "dataset_manifest":
        return _clean_optional_string(payload.get("id"))

    for field_name in _REFERENCE_LIST_FIELDS:
        values = payload.get(field_name)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            if _clean_optional_string(item.get("artifact_type")) != "dataset_manifest":
                continue
            dataset_id = _clean_optional_string(item.get("id"))
            if dataset_id:
                return dataset_id
    return None


def _read_sibling_dataset_manifest_id(
    base_dir: Path,
    context: ArtifactPathContext,
    cache: dict[str, str | None],
) -> str | None:
    if context.run_dir is None:
        return None
    sibling_relative = str(context.run_dir / "dataset_manifest.yaml")
    if sibling_relative == context.relative_path:
        return None
    if sibling_relative in cache:
        return cache[sibling_relative]

    sibling_path = base_dir / sibling_relative
    if not sibling_path.is_file():
        cache[sibling_relative] = None
        return None

    payload, error = _load_raw_artifact_payload(sibling_path)
    if error or payload is None:
        cache[sibling_relative] = None
        return None

    dataset_id = _clean_optional_string(payload.get("id"))
    cache[sibling_relative] = dataset_id
    return dataset_id


def _is_registry_compatible_workflow_run(
    payload: dict[str, Any],
    context: ArtifactPathContext,
) -> bool:
    if _clean_optional_string(payload.get("artifact_type")) != "workflow_run":
        return False
    raw_run_id = _clean_optional_string(payload.get("run_id"))
    if raw_run_id is None or raw_run_id != context.run_id or not is_valid_run_id(raw_run_id):
        return False
    if _parse_timestamp(payload.get("created_at")) is None:
        return False
    if not (_clean_optional_string(payload.get("source_workflow")) or _clean_optional_string(payload.get("source_tool"))):
        return False
    workflow_data = payload.get("workflow")
    if not isinstance(workflow_data, dict):
        return False
    workflow_slug = _clean_optional_string(workflow_data.get("slug"))
    return workflow_slug == context.workflow


def _payload_mismatches(payload: dict[str, Any], context: ArtifactPathContext) -> list[str]:
    declared_type = _clean_optional_string(payload.get("artifact_type"))
    raw_run_id = _clean_optional_string(payload.get("run_id"))
    raw_created_at = _parse_timestamp(payload.get("created_at"))
    mismatches: list[str] = []

    if declared_type and context.inferred_artifact_type and declared_type != context.inferred_artifact_type:
        mismatches.append(
            f"Artifact payload type {declared_type!r} does not match path type {context.inferred_artifact_type!r}."
        )
    if raw_run_id and raw_run_id != context.run_id:
        mismatches.append(
            f"Artifact payload run_id {raw_run_id!r} does not match path run_id {context.run_id!r}."
        )
    if raw_run_id and not is_valid_run_id(raw_run_id):
        mismatches.append(f"Artifact payload run_id is not canonical: {raw_run_id!r}.")
    if raw_created_at is None and payload.get("created_at") is not None:
        mismatches.append("Artifact created_at must be an ISO-8601 timestamp with timezone.")
    return mismatches


def _record_from_valid_document(
    document: ArtifactDocument,
    context: ArtifactPathContext,
    content_hash: str,
    *,
    dataset_id: str | None,
) -> ArtifactRegistryRecord:
    return ArtifactRegistryRecord(
        artifact_id=document.id,
        declared_id=document.id,
        artifact_type=document.artifact_type,
        path=context.relative_path,
        hash=content_hash,
        created_at=document.created_at,
        run_id=document.run_id,
        workflow=context.workflow or "",
        date=context.run_date or "",
        source_workflow=document.source_workflow,
        source_tool=document.source_tool,
        dataset_id=dataset_id,
        status="valid",
    )


def _record_from_payload(
    payload: dict[str, Any],
    context: ArtifactPathContext,
    content_hash: str,
    *,
    dataset_id: str | None,
    default_created_at: datetime | None = None,
    default_source_workflow: str | None = None,
    default_source_tool: str | None = None,
    default_artifact_type: str | None = None,
    error: str | None = None,
) -> ArtifactRegistryRecord:
    declared_id = _clean_optional_string(payload.get("id"))
    run_id = _clean_optional_string(payload.get("run_id")) or context.run_id or ""
    artifact_type = (
        _clean_optional_string(payload.get("artifact_type"))
        or default_artifact_type
        or context.inferred_artifact_type
        or "unknown"
    )
    created_at = (
        _parse_timestamp(payload.get("created_at"))
        or default_created_at
        or _timestamp_from_run_id(run_id)
    )
    source_workflow = _clean_optional_string(payload.get("source_workflow")) or default_source_workflow
    source_tool = _clean_optional_string(payload.get("source_tool")) or default_source_tool
    artifact_id = declared_id or _build_fallback_artifact_id(context)
    status: Literal["valid", "invalid"] = "invalid" if error else "valid"

    return ArtifactRegistryRecord(
        artifact_id=artifact_id,
        declared_id=declared_id,
        artifact_type=artifact_type,
        path=context.relative_path,
        hash=content_hash,
        created_at=created_at,
        run_id=run_id,
        workflow=context.workflow or "",
        date=context.run_date or "",
        source_workflow=source_workflow,
        source_tool=source_tool,
        dataset_id=dataset_id,
        status=status,
        error=error,
    )


def _generic_record(
    context: ArtifactPathContext,
    *,
    content_hash: str,
    created_at: datetime,
    source_workflow: str | None,
    source_tool: str | None,
    dataset_id: str | None,
    declared_id: str | None = None,
    artifact_type: str | None = None,
    error: str | None = None,
) -> ArtifactRegistryRecord:
    return ArtifactRegistryRecord(
        artifact_id=declared_id or _build_fallback_artifact_id(context),
        declared_id=declared_id,
        artifact_type=artifact_type or context.inferred_artifact_type or "artifact_file",
        path=context.relative_path,
        hash=content_hash,
        created_at=created_at,
        run_id=context.run_id or "",
        workflow=context.workflow or "",
        date=context.run_date or "",
        source_workflow=source_workflow,
        source_tool=source_tool,
        dataset_id=dataset_id,
        status="invalid" if error else "valid",
        error=error,
    )


def _invalid_record(
    context: ArtifactPathContext,
    *,
    content_hash: str | None = None,
    declared_id: str | None = None,
    error: str,
    created_at: datetime | None = None,
    source_workflow: str | None = None,
    source_tool: str | None = None,
    dataset_id: str | None = None,
    artifact_type: str | None = None,
    run_id: str | None = None,
) -> ArtifactRegistryRecord:
    resolved_run_id = run_id or context.run_id or ""
    resolved_artifact_type = artifact_type or context.inferred_artifact_type or "unknown"
    return ArtifactRegistryRecord(
        artifact_id=declared_id or _build_fallback_artifact_id(context),
        declared_id=declared_id,
        artifact_type=resolved_artifact_type,
        path=context.relative_path,
        hash=content_hash,
        created_at=created_at,
        run_id=resolved_run_id,
        workflow=context.workflow or "",
        date=context.run_date or "",
        source_workflow=source_workflow,
        source_tool=source_tool,
        dataset_id=dataset_id,
        status="invalid",
        error=error,
    )


def _sort_records(records: list[ArtifactRegistryRecord]) -> list[ArtifactRegistryRecord]:
    return sorted(
        records,
        key=lambda record: (
            record.workflow,
            record.date,
            record.run_id,
            record.path,
        ),
    )


def _build_snapshot(records: list[ArtifactRegistryRecord]) -> ArtifactRegistrySnapshot:
    sorted_records = _sort_records(records)
    valid_count = sum(record.status == "valid" for record in sorted_records)
    invalid_count = len(sorted_records) - valid_count
    return ArtifactRegistrySnapshot(
        generated_at=_now_utc(),
        record_count=len(sorted_records),
        valid_count=valid_count,
        invalid_count=invalid_count,
        records=sorted_records,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class ArtifactRegistry:
    """Manage an on-disk metadata registry for canonical artifact files."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir).resolve()
        self._dataset_id_cache: dict[str, str | None] = {}
        self._run_origin_cache: dict[str, tuple[str | None, str | None]] = {}

    def _scan_candidate_paths(self) -> list[str]:
        artifacts_root = _artifacts_root(self.base_dir)
        if not artifacts_root.exists():
            return []

        candidates: list[str] = []
        for path in artifacts_root.rglob("*"):
            if path.is_dir() and path.name != "ro-crate":
                continue
            relative = path.relative_to(self.base_dir).as_posix()
            context = _path_context(relative, is_dir=path.is_dir())
            if context.is_canonical:
                candidates.append(relative)
        return sorted(set(candidates))

    def _load_snapshot(self) -> ArtifactRegistrySnapshot | None:
        registry_path = _registry_file(self.base_dir)
        if not registry_path.exists():
            return None
        try:
            return ArtifactRegistrySnapshot.model_validate_json(registry_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_snapshot(self, snapshot: ArtifactRegistrySnapshot) -> None:
        _atomic_write_json(_registry_file(self.base_dir), snapshot.model_dump(mode="json"))

    def _read_run_origin(self, context: ArtifactPathContext) -> tuple[str | None, str | None]:
        if context.run_dir is None:
            return None, None
        run_record_relative = str(context.run_dir / RUN_RECORD_FILENAME)
        if run_record_relative == context.relative_path:
            return None, None
        if run_record_relative in self._run_origin_cache:
            return self._run_origin_cache[run_record_relative]

        run_record_path = self.base_dir / run_record_relative
        if not run_record_path.is_file():
            self._run_origin_cache[run_record_relative] = (None, None)
            return None, None

        payload, error = _load_raw_artifact_payload(run_record_path)
        if error or payload is None:
            self._run_origin_cache[run_record_relative] = (None, None)
            return None, None

        origin = (
            _clean_optional_string(payload.get("source_workflow")),
            _clean_optional_string(payload.get("source_tool")),
        )
        self._run_origin_cache[run_record_relative] = origin
        return origin

    def _extract_dataset_id(
        self,
        *,
        context: ArtifactPathContext,
        payload: dict[str, Any] | None,
        document: ArtifactDocument | None,
    ) -> str | None:
        if document is not None:
            if document.artifact_type == "dataset_manifest":
                return document.id
            if isinstance(document, WorkflowRun):
                for reference in [*document.related_artifacts, *document.inputs, *document.outputs]:
                    if reference.artifact_type == "dataset_manifest" and reference.id:
                        return reference.id
            for reference in document.related_artifacts:
                if reference.artifact_type == "dataset_manifest" and reference.id:
                    return reference.id

        if payload is not None:
            declared_dataset_id = _extract_declared_dataset_id(
                payload,
                artifact_type=context.inferred_artifact_type or "unknown",
            )
            if declared_dataset_id:
                return declared_dataset_id

        return _read_sibling_dataset_manifest_id(self.base_dir, context, self._dataset_id_cache)

    def build_record(self, relative_path: str | PurePosixPath) -> ArtifactRegistryRecord | None:
        normalized = _normalize_relative_path(relative_path)
        target = self.base_dir / normalized
        context = _path_context(normalized, is_dir=target.is_dir())
        if context.inferred_artifact_type is None:
            return None

        if not context.is_canonical:
            return _invalid_record(context, error=context.error or "Artifact path is not canonical.")

        if not target.exists():
            return _invalid_record(context, error=f"Artifact file not found: {context.relative_path}")

        if target.is_dir():
            content_hash = _compute_directory_hash(target)
            dataset_id = self._extract_dataset_id(context=context, payload=None, document=None)
            run_source_workflow, run_source_tool = self._read_run_origin(context)
            return _generic_record(
                context,
                content_hash=content_hash,
                created_at=_timestamp_from_stat(target),
                source_workflow=run_source_workflow or context.workflow,
                source_tool=run_source_tool,
                dataset_id=dataset_id,
            )

        try:
            content_hash = compute_content_hash(target.read_bytes())
        except OSError as exc:
            return _invalid_record(context, error=str(exc))

        raw_payload, payload_error = (None, None)
        if target.suffix in {".json", ".yaml", ".yml"}:
            raw_payload, payload_error = _load_raw_artifact_payload(target)

        if context.inferred_artifact_type in _SCHEMA_ARTIFACT_TYPES:
            if payload_error or raw_payload is None:
                return _invalid_record(
                    context,
                    content_hash=content_hash,
                    error=payload_error or "Unable to parse artifact.",
                )

            declared_id = _clean_optional_string(raw_payload.get("id"))
            raw_run_id = _clean_optional_string(raw_payload.get("run_id"))
            raw_created_at = _parse_timestamp(raw_payload.get("created_at"))
            source_workflow = _clean_optional_string(raw_payload.get("source_workflow"))
            source_tool = _clean_optional_string(raw_payload.get("source_tool"))
            mismatches = _payload_mismatches(raw_payload, context)

            try:
                document = load_artifact_document(target)
            except Exception as exc:
                document = None
                validation_error = str(exc)
            else:
                validation_error = None

            dataset_id = self._extract_dataset_id(context=context, payload=raw_payload, document=document)

            if document is not None:
                if context.run_id and document.run_id != context.run_id:
                    mismatches.append(
                        f"Artifact document run_id {document.run_id!r} does not match path run_id {context.run_id!r}."
                    )
                if isinstance(document, WorkflowRun) and context.workflow and document.workflow.slug != context.workflow:
                    mismatches.append(
                        f"Workflow run slug {document.workflow.slug!r} does not match path workflow {context.workflow!r}."
                    )
                if mismatches:
                    return _invalid_record(
                        context,
                        content_hash=content_hash,
                        declared_id=document.id,
                        created_at=document.created_at,
                        source_workflow=document.source_workflow,
                        source_tool=document.source_tool,
                        dataset_id=dataset_id,
                        artifact_type=document.artifact_type,
                        run_id=document.run_id,
                        error=" ".join(mismatches),
                    )
                return _record_from_valid_document(document, context, content_hash, dataset_id=dataset_id)

            if context.inferred_artifact_type == "workflow_run" and _is_registry_compatible_workflow_run(raw_payload, context):
                if mismatches:
                    return _invalid_record(
                        context,
                        content_hash=content_hash,
                        declared_id=declared_id,
                        created_at=raw_created_at or _timestamp_from_run_id(raw_run_id or context.run_id),
                        source_workflow=source_workflow,
                        source_tool=source_tool,
                        dataset_id=dataset_id,
                        error=" ".join(mismatches),
                    )
                return _record_from_payload(
                    raw_payload,
                    context,
                    content_hash,
                    dataset_id=dataset_id,
                )

            error_parts = mismatches[:]
            if validation_error:
                error_parts.append(validation_error)
            return _invalid_record(
                context,
                content_hash=content_hash,
                declared_id=declared_id,
                created_at=raw_created_at or _timestamp_from_run_id(raw_run_id or context.run_id),
                source_workflow=source_workflow,
                source_tool=source_tool,
                dataset_id=dataset_id,
                artifact_type=_clean_optional_string(raw_payload.get("artifact_type")) or context.inferred_artifact_type,
                run_id=raw_run_id or context.run_id,
                error=" ".join(error_parts) if error_parts else "Artifact validation failed.",
            )

        run_source_workflow, run_source_tool = self._read_run_origin(context)
        dataset_id = self._extract_dataset_id(context=context, payload=raw_payload, document=None)
        default_created_at = _timestamp_from_stat(target)

        if context.inferred_artifact_type in _STRUCTURED_ROOT_ARTIFACT_TYPES:
            if payload_error or raw_payload is None:
                return _invalid_record(
                    context,
                    content_hash=content_hash,
                    created_at=default_created_at,
                    source_workflow=run_source_workflow or context.workflow,
                    source_tool=run_source_tool,
                    dataset_id=dataset_id,
                    error=payload_error or "Unable to parse structured artifact.",
                )

            mismatches = _payload_mismatches(raw_payload, context)
            if mismatches:
                return _invalid_record(
                    context,
                    content_hash=content_hash,
                    declared_id=_clean_optional_string(raw_payload.get("id")),
                    created_at=_parse_timestamp(raw_payload.get("created_at")) or default_created_at,
                    source_workflow=_clean_optional_string(raw_payload.get("source_workflow")) or run_source_workflow or context.workflow,
                    source_tool=_clean_optional_string(raw_payload.get("source_tool")) or run_source_tool,
                    dataset_id=dataset_id,
                    artifact_type=_clean_optional_string(raw_payload.get("artifact_type")) or context.inferred_artifact_type,
                    run_id=_clean_optional_string(raw_payload.get("run_id")) or context.run_id,
                    error=" ".join(mismatches),
                )
            return _record_from_payload(
                raw_payload,
                context,
                content_hash,
                dataset_id=dataset_id,
                default_created_at=default_created_at,
                default_source_workflow=run_source_workflow or context.workflow,
                default_source_tool=run_source_tool,
                default_artifact_type=context.inferred_artifact_type,
            )

        return _generic_record(
            context,
            content_hash=content_hash,
            created_at=_parse_timestamp((raw_payload or {}).get("created_at")) or default_created_at,
            source_workflow=_clean_optional_string((raw_payload or {}).get("source_workflow")) or run_source_workflow or context.workflow,
            source_tool=_clean_optional_string((raw_payload or {}).get("source_tool")) or run_source_tool,
            dataset_id=dataset_id,
            declared_id=_clean_optional_string((raw_payload or {}).get("id")),
            artifact_type=context.inferred_artifact_type,
            error=" ".join(_payload_mismatches(raw_payload, context)) if raw_payload is not None and _payload_mismatches(raw_payload, context) else None,
        )

    def rebuild(self) -> ArtifactRegistrySnapshot:
        self._dataset_id_cache = {}
        self._run_origin_cache = {}
        records = [
            record
            for record in (self.build_record(relative_path) for relative_path in self._scan_candidate_paths())
            if record is not None
        ]
        snapshot = _build_snapshot(records)
        self._save_snapshot(snapshot)
        return snapshot

    def ensure_snapshot(self) -> ArtifactRegistrySnapshot:
        snapshot = self._load_snapshot()
        if snapshot is None:
            return self.rebuild()
        return snapshot

    def refresh_path(self, relative_path: str | PurePosixPath) -> ArtifactRegistryRecord | None:
        snapshot = self._load_snapshot()
        if snapshot is None:
            snapshot = self.rebuild()

        normalized = _normalize_relative_path(relative_path)
        records_by_path = {record.path: record for record in snapshot.records}
        record = self.build_record(normalized)
        if record is None:
            records_by_path.pop(normalized, None)
        else:
            records_by_path[normalized] = record

        refreshed = _build_snapshot(list(records_by_path.values()))
        self._save_snapshot(refreshed)
        return record

    def lookup(
        self,
        *,
        run_id: str | None = None,
        artifact_type: str | None = None,
        workflow: str | None = None,
        date: str | None = None,
        dataset_id: str | None = None,
        include_invalid: bool = False,
    ) -> ArtifactRegistryLookupResult:
        snapshot = self.ensure_snapshot()
        records = snapshot.records
        if not include_invalid:
            records = [record for record in records if record.status == "valid"]

        filters = {
            "run_id": _clean_optional_string(run_id),
            "artifact_type": _clean_optional_string(artifact_type),
            "workflow": _clean_optional_string(workflow),
            "date": _clean_optional_string(date),
            "dataset_id": _clean_optional_string(dataset_id),
        }

        if filters["run_id"]:
            records = [record for record in records if record.run_id == filters["run_id"]]
        if filters["artifact_type"]:
            records = [record for record in records if record.artifact_type == filters["artifact_type"]]
        if filters["workflow"]:
            records = [record for record in records if record.workflow == filters["workflow"]]
        if filters["date"]:
            records = [record for record in records if record.date == filters["date"]]
        if filters["dataset_id"]:
            records = [record for record in records if record.dataset_id == filters["dataset_id"]]

        sorted_records = _sort_records(records)
        return ArtifactRegistryLookupResult(
            generated_at=snapshot.generated_at,
            artifact_root=snapshot.artifact_root,
            registry_path=snapshot.registry_path,
            total_count=snapshot.record_count,
            matched_count=len(sorted_records),
            valid_count=sum(record.status == "valid" for record in sorted_records),
            invalid_count=sum(record.status == "invalid" for record in sorted_records),
            records=sorted_records,
        )


def rebuild_artifact_registry(base_dir: str | Path) -> ArtifactRegistrySnapshot:
    return ArtifactRegistry(base_dir).rebuild()


def refresh_artifact_registry_path(
    base_dir: str | Path,
    relative_path: str | PurePosixPath,
) -> ArtifactRegistryRecord | None:
    return ArtifactRegistry(base_dir).refresh_path(relative_path)


def lookup_artifact_registry(
    base_dir: str | Path,
    *,
    run_id: str | None = None,
    artifact_type: str | None = None,
    workflow: str | None = None,
    date: str | None = None,
    dataset_id: str | None = None,
    include_invalid: bool = False,
) -> ArtifactRegistryLookupResult:
    return ArtifactRegistry(base_dir).lookup(
        run_id=run_id,
        artifact_type=artifact_type,
        workflow=workflow,
        date=date,
        dataset_id=dataset_id,
        include_invalid=include_invalid,
    )
