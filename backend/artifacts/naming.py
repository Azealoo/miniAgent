"""Deterministic naming helpers for durable BioAPEX artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Mapping
from uuid import uuid4

ARTIFACTS_ROOT = PurePosixPath("artifacts")
RUN_RECORD_FILENAME = "run.json"
CONTENT_HASH_MANIFEST_FILENAME = "content_hashes.json"
USER_INPUTS_DIR = PurePosixPath("inputs/user")
GENERATED_OUTPUTS_DIR = PurePosixPath("outputs/generated")

STABLE_ARTIFACT_FILENAMES: dict[str, str] = {
    "workflow_run": RUN_RECORD_FILENAME,
    "run": RUN_RECORD_FILENAME,
    "dataset_manifest": "dataset_manifest.yaml",
    "workflow_plan": "workflow_plan.json",
    "compliance_report": "compliance_report.json",
    "evidence_card": "evidence_card.yaml",
    "entity_grounding": "entity_grounding.json",
    "fastqc_run": "fastqc_run.json",
    "fastqc_metrics": "fastqc_metrics.json",
    "multiqc_run": "multiqc_run.json",
    "multiqc_metrics": "multiqc_metrics.json",
    "count_matrix": "count_matrix.json",
    "normalized_count_matrix": "normalized_count_matrix.json",
    "differential_expression_results": "differential_expression_results.json",
    "differential_expression_run": "differential_expression_run.json",
    "protocol_run": "protocol_run.yaml",
    "qa_report": "qa_report.json",
    "provenance": "prov.json",
    "biocompute": "biocompute.json",
    "evidence_review": "evidence_review.json",
    "claim_graph": "claim_graph.json",
    "provenance_export": "prov.json",
    "prov": "prov.json",
    "ro_crate": "ro-crate",
    "ro-crate": "ro-crate",
}

_RUN_ID_RE = re.compile(r"^run-(?P<stamp>\d{8}T\d{6}Z)-(?P<suffix>[0-9a-f]{8})$")
_SLUG_PART_RE = re.compile(r"[^a-z0-9]+")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _normalize_timestamp(value: datetime | None = None) -> datetime:
    if value is None:
        value = datetime.now(timezone.utc)
    elif value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0)


def _isoformat_z(value: datetime | None = None) -> str:
    return _normalize_timestamp(value).isoformat().replace("+00:00", "Z")


def _slugify_path_component(value: str) -> str:
    candidate = value.strip().lower().replace("_", "-")
    candidate = _SLUG_PART_RE.sub("-", candidate).strip("-")
    if not candidate:
        raise ValueError("Path component must contain at least one letter or digit.")
    return candidate


def _sanitize_filename(name: str) -> str:
    raw_name = PurePosixPath(name.strip()).name
    if raw_name in {"", ".", ".."}:
        raise ValueError("Filename must not be empty.")

    sanitized = _SAFE_FILENAME_RE.sub("_", raw_name).strip("._-")
    if not sanitized:
        sanitized = "file"
    return sanitized.lower()


def _normalize_relative_path(path: str | PurePosixPath) -> PurePosixPath:
    value = str(path).strip()
    if not value:
        raise ValueError("Path must not be empty.")

    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        raise ValueError("Artifact paths must be relative, not absolute.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Artifact paths must not contain '..'.")
    if candidate.parts == (".",):
        raise ValueError("Artifact paths must not resolve to '.'.")
    return candidate


def _timestamp_from_run_id(run_id: str) -> datetime:
    match = _RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise ValueError(f"Invalid run_id format: {run_id!r}")
    return datetime.strptime(
        match.group("stamp"),
        "%Y%m%dT%H%M%SZ",
    ).replace(tzinfo=timezone.utc)


def validate_artifact_root(root: str | PurePosixPath = ARTIFACTS_ROOT) -> PurePosixPath:
    return _normalize_relative_path(root)


def is_valid_run_id(run_id: str) -> bool:
    return _RUN_ID_RE.fullmatch(run_id) is not None


def generate_run_id(
    *,
    now: datetime | None = None,
    unique_suffix: str | None = None,
) -> str:
    timestamp = _normalize_timestamp(now)
    suffix = (unique_suffix or uuid4().hex[:8]).lower()
    if not re.fullmatch(r"[0-9a-f]{8}", suffix):
        raise ValueError("Run ID suffix must be exactly 8 lowercase hex characters.")
    return f"run-{timestamp:%Y%m%dT%H%M%SZ}-{suffix}"


def stable_artifact_name(artifact_type: str) -> str:
    key = artifact_type.strip().lower()
    try:
        return STABLE_ARTIFACT_FILENAMES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown stable artifact type: {artifact_type!r}") from exc


def build_run_directory(
    workflow: str,
    *,
    created_at: datetime | None = None,
    run_id: str | None = None,
    artifact_root: str | PurePosixPath = ARTIFACTS_ROOT,
) -> PurePosixPath:
    root = validate_artifact_root(artifact_root)
    workflow_slug = _slugify_path_component(workflow)
    resolved_run_id = run_id or generate_run_id(now=created_at)
    if not is_valid_run_id(resolved_run_id):
        raise ValueError(f"Invalid run_id format: {resolved_run_id!r}")

    run_timestamp = (
        _normalize_timestamp(created_at) if created_at else _timestamp_from_run_id(resolved_run_id)
    )
    if created_at and run_timestamp != _timestamp_from_run_id(resolved_run_id):
        raise ValueError("created_at must match the timestamp encoded in run_id.")
    run_date = run_timestamp.strftime("%Y-%m-%d")
    return root / workflow_slug / run_date / resolved_run_id


def build_user_supplied_relpath(
    original_name: str,
    *,
    slot: str | None = None,
) -> PurePosixPath:
    filename = _sanitize_filename(original_name)
    if slot:
        label = f"{_slugify_path_component(slot)}__"
    else:
        label = "user__"
    return USER_INPUTS_DIR / f"{label}{filename}"


def build_generated_output_relpath(
    filename: str,
    *,
    step: str | None = None,
) -> PurePosixPath:
    sanitized_name = _sanitize_filename(filename)
    if step:
        return GENERATED_OUTPUTS_DIR / _slugify_path_component(step) / sanitized_name
    return GENERATED_OUTPUTS_DIR / sanitized_name


def resolve_artifact_path(
    base_dir: Path | str,
    relative_path: str | PurePosixPath,
    *,
    must_not_exist: bool = False,
) -> Path:
    base = Path(base_dir).resolve()
    relative = _normalize_relative_path(relative_path)
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("Resolved artifact path escapes the allowed base directory.") from exc

    if must_not_exist and target.exists():
        raise FileExistsError(f"Artifact path already exists: {relative}")
    return target


def build_artifact_header(
    *,
    schema_version: str,
    artifact_type: str,
    run_id: str,
    created_at: datetime | None = None,
    source_workflow: str | None = None,
    source_tool: str | None = None,
) -> dict[str, str]:
    if not is_valid_run_id(run_id):
        raise ValueError(f"Invalid run_id format: {run_id!r}")
    if not source_workflow and not source_tool:
        raise ValueError("Artifact headers require source_workflow or source_tool.")

    header = {
        "schema_version": schema_version,
        "artifact_type": artifact_type,
        "run_id": run_id,
        "created_at": _isoformat_z(created_at),
    }
    if source_workflow:
        header["source_workflow"] = source_workflow
    if source_tool:
        header["source_tool"] = source_tool
    return header


def compute_content_hash(content: bytes | str) -> str:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return sha256(payload).hexdigest()


def _dump_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _refresh_registry_for_path(base_dir: Path, target: Path) -> None:
    try:
        relative = target.resolve().relative_to(base_dir.resolve())
    except ValueError:
        return

    try:
        from .registry import refresh_artifact_registry_path

        relative_str = relative.as_posix()
        refresh_artifact_registry_path(base_dir, relative_str)

        # Keep the run-level ro-crate record fresh when individual entries change.
        if len(relative.parts) > 5 and relative.parts[4] == "ro-crate":
            refresh_artifact_registry_path(
                base_dir,
                PurePosixPath(*relative.parts[:5]),
            )
    except Exception:
        # Registry maintenance must not block artifact writes.
        return


class _TrackedArtifactPath(type(Path())):
    __slots__ = ("_registry_base_dir",)

    def __new__(
        cls,
        *args,
        registry_base_dir: Path | None = None,
    ):
        self = super().__new__(cls, *args)
        self._registry_base_dir = registry_base_dir
        return self

    def _registry_base_dir_or_none(self) -> Path | None:
        return getattr(self, "_registry_base_dir", None)

    def _tracked(self, target: Path) -> "_TrackedArtifactPath":
        return type(self)(target, registry_base_dir=self._registry_base_dir_or_none())

    def _refresh_registry(self) -> None:
        registry_base_dir = self._registry_base_dir_or_none()
        if registry_base_dir is None:
            return
        _refresh_registry_for_path(registry_base_dir, Path(self))

    def __truediv__(self, key):
        return self._tracked(super().__truediv__(key))

    def joinpath(self, *pathsegments):
        return self._tracked(super().joinpath(*pathsegments))

    def write_text(self, data: str, encoding=None, errors=None, newline=None):
        written = super().write_text(data, encoding=encoding, errors=errors, newline=newline)
        self._refresh_registry()
        return written

    def write_bytes(self, data: bytes):
        written = super().write_bytes(data)
        self._refresh_registry()
        return written

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        result = super().mkdir(mode=mode, parents=parents, exist_ok=exist_ok)
        self._refresh_registry()
        return result


def build_content_hash_manifest(
    *,
    run_id: str,
    schema_version: str,
    entries: Mapping[str | PurePosixPath, bytes | str],
    created_at: datetime | None = None,
    source_workflow: str | None = None,
    source_tool: str | None = None,
) -> dict[str, object]:
    normalized_entries: dict[str, dict[str, str]] = {}
    for relative_path, content in entries.items():
        relative = _normalize_relative_path(relative_path)
        normalized_entries[str(relative)] = {
            "algorithm": "sha256",
            "digest": compute_content_hash(content),
        }

    manifest: dict[str, object] = build_artifact_header(
        schema_version=schema_version,
        artifact_type="content_hash_manifest",
        run_id=run_id,
        created_at=created_at,
        source_workflow=source_workflow,
        source_tool=source_tool,
    )
    manifest["hashes"] = normalized_entries
    return manifest


@dataclass(frozen=True)
class RunLayout:
    base_dir: Path
    workflow: str
    workflow_slug: str
    run_id: str
    created_at: datetime
    artifact_root: PurePosixPath
    relative_run_dir: PurePosixPath
    run_dir: Path

    @property
    def run_record_relpath(self) -> PurePosixPath:
        return self.relative_run_dir / RUN_RECORD_FILENAME

    @property
    def run_record_path(self) -> Path:
        return self._track_path(self.run_dir / RUN_RECORD_FILENAME)

    @property
    def content_hash_manifest_relpath(self) -> PurePosixPath:
        return self.relative_run_dir / CONTENT_HASH_MANIFEST_FILENAME

    @property
    def content_hash_manifest_path(self) -> Path:
        return self._track_path(self.run_dir / CONTENT_HASH_MANIFEST_FILENAME)

    def stable_artifact_relpath(self, artifact_type: str) -> PurePosixPath:
        return self.relative_run_dir / stable_artifact_name(artifact_type)

    def _track_path(self, target: Path) -> Path:
        return _TrackedArtifactPath(target, registry_base_dir=self.base_dir)

    def _reserve_run_path(
        self,
        relative_path: PurePosixPath,
        *,
        create_parent: bool = False,
    ) -> Path:
        target = resolve_artifact_path(self.run_dir, relative_path, must_not_exist=True)
        if create_parent:
            target.parent.mkdir(parents=True, exist_ok=True)
        return self._track_path(target)

    def stable_artifact_path(self, artifact_type: str) -> Path:
        return self._reserve_run_path(PurePosixPath(stable_artifact_name(artifact_type)))

    def user_input_relpath(self, original_name: str, *, slot: str | None = None) -> PurePosixPath:
        return self.relative_run_dir / build_user_supplied_relpath(original_name, slot=slot)

    def user_input_path(self, original_name: str, *, slot: str | None = None) -> Path:
        return self._reserve_run_path(
            build_user_supplied_relpath(original_name, slot=slot),
            create_parent=True,
        )

    def generated_output_relpath(self, filename: str, *, step: str | None = None) -> PurePosixPath:
        return self.relative_run_dir / build_generated_output_relpath(filename, step=step)

    def generated_output_path(self, filename: str, *, step: str | None = None) -> Path:
        return self._reserve_run_path(
            build_generated_output_relpath(filename, step=step),
            create_parent=True,
        )

    def build_run_record(self, *, schema_version: str = "1.0.0") -> dict[str, object]:
        record: dict[str, object] = build_artifact_header(
            schema_version=schema_version,
            artifact_type="workflow_run",
            run_id=self.run_id,
            created_at=self.created_at,
            source_workflow=self.workflow,
        )
        record["workflow"] = {
            "name": self.workflow,
            "slug": self.workflow_slug,
        }
        record["paths"] = {
            "run_dir": str(self.relative_run_dir),
            "root_record": RUN_RECORD_FILENAME,
            "content_hash_manifest": CONTENT_HASH_MANIFEST_FILENAME,
            "user_inputs_dir": str(USER_INPUTS_DIR),
            "generated_outputs_dir": str(GENERATED_OUTPUTS_DIR),
        }
        record["stable_artifacts"] = {
            artifact_type: filename
            for artifact_type, filename in STABLE_ARTIFACT_FILENAMES.items()
            if artifact_type in {
                "workflow_run",
                "dataset_manifest",
                "workflow_plan",
                "compliance_report",
                "evidence_card",
                "evidence_review",
                "entity_grounding",
                "protocol_run",
                "qa_report",
                "provenance",
                "biocompute",
                "ro_crate",
                "claim_graph",
            }
        }
        return record


def prepare_run_directory(
    base_dir: Path | str,
    workflow: str,
    *,
    created_at: datetime | None = None,
    run_id: str | None = None,
    artifact_root: str | PurePosixPath = ARTIFACTS_ROOT,
) -> RunLayout:
    base = Path(base_dir).resolve()
    if not base.exists():
        raise FileNotFoundError(f"Artifact base directory does not exist: {base}")

    timestamp = _normalize_timestamp(created_at)
    resolved_run_id = run_id or generate_run_id(now=timestamp)
    relative_run_dir = build_run_directory(
        workflow,
        created_at=timestamp,
        run_id=resolved_run_id,
        artifact_root=artifact_root,
    )
    run_dir = resolve_artifact_path(base, relative_run_dir, must_not_exist=True)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / USER_INPUTS_DIR).mkdir(parents=True, exist_ok=False)
    (run_dir / GENERATED_OUTPUTS_DIR).mkdir(parents=True, exist_ok=False)
    layout = RunLayout(
        base_dir=base,
        workflow=workflow,
        workflow_slug=_slugify_path_component(workflow),
        run_id=resolved_run_id,
        created_at=timestamp,
        artifact_root=validate_artifact_root(artifact_root),
        relative_run_dir=relative_run_dir,
        run_dir=run_dir,
    )
    run_record = layout.build_run_record()
    run_record_text = _dump_json(run_record)
    layout.run_record_path.write_text(run_record_text, encoding="utf-8")

    content_hash_manifest = build_content_hash_manifest(
        run_id=layout.run_id,
        schema_version="1.0.0",
        created_at=layout.created_at,
        source_workflow=layout.workflow,
        entries={RUN_RECORD_FILENAME: run_record_text},
    )
    layout.content_hash_manifest_path.write_text(
        _dump_json(content_hash_manifest),
        encoding="utf-8",
    )
    return layout
