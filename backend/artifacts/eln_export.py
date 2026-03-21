"""Portable ELN export helpers derived from canonical workflow artifacts."""

from __future__ import annotations

import gzip
import io
import json
import os
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from uuid import uuid4

from audit.store import append_export_generated_event

from .naming import RunLayout, compute_content_hash, resolve_artifact_path
from .schemas import (
    ArtifactReference,
    ELNExportArtifact,
    EvidenceReviewArtifact,
    WorkflowRun,
    load_artifact_document,
    normalize_identifier,
)

_ELN_EXPORT_STEP = "eln-export"
_ELN_EXPORT_MANIFEST_FILENAME = "eln_export.json"
_ELN_EXPORT_ARCHIVE_FILENAME = "eln_export_bundle.tar.gz"
_ELN_EXPORT_ARCHIVE_INTERNAL_MANIFEST = "manifest.json"
_ELN_EXPORT_BUNDLE_VERSION = "1.0.0"
_ELN_EXPORT_PACKAGE_ROOT = "bioapex-eln-export"
_REPORT_BUNDLE_MANIFEST_RELATIVE_PATH = PurePosixPath(
    "outputs/generated/report-bundle/report_bundle_manifest.json"
)
_ELN_VENDOR_UNSUPPORTED_FIELDS = [
    {
        "field_name": "vendor_specific_eln_metadata",
        "reason": (
            "ELN Export V1 materializes a portable artifact bundle and does not emit "
            "vendor-specific notebook record fields."
        ),
    }
]


def expected_eln_export_paths(layout: RunLayout) -> list[str]:
    return [
        layout.generated_output_relpath(
            _ELN_EXPORT_MANIFEST_FILENAME,
            step=_ELN_EXPORT_STEP,
        ).as_posix(),
        layout.generated_output_relpath(
            _ELN_EXPORT_ARCHIVE_FILENAME,
            step=_ELN_EXPORT_STEP,
        ).as_posix(),
    ]


def materialize_eln_export_bundle(
    *,
    base_dir: Path,
    layout: RunLayout,
    run_document: WorkflowRun,
    workflow_version: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    manifest_path, archive_path = expected_eln_export_paths(layout)
    exported_at = _workflow_end_time(run_document)
    run_ref = ArtifactReference(
        artifact_type="workflow_run",
        path=layout.run_record_relpath.as_posix(),
        id=run_document.id,
        run_id=run_document.run_id,
    )
    content_hash_ref = ArtifactReference(
        artifact_type="content_hash_manifest",
        path=layout.content_hash_manifest_relpath.as_posix(),
        id=normalize_identifier(f"content-hashes-{layout.workflow}-{layout.run_id.lower()}"),
        run_id=layout.run_id,
    )

    dataset_manifest_ref = _first_ref(
        [*run_document.inputs, *run_document.related_artifacts],
        artifact_type="dataset_manifest",
    )
    protocol_run_ref = _load_optional_artifact_ref(base_dir, layout.stable_artifact_relpath("protocol_run"))

    report_bundle_manifest_ref, report_bundle_manifest_payload = _load_report_bundle_manifest(base_dir, layout)
    report_bundle_ref = _report_bundle_ref_from_manifest(report_bundle_manifest_payload, run_id=layout.run_id)
    report_bundle_expected_refs = _report_bundle_expected_refs(report_bundle_manifest_payload)
    report_bundle_missing = _report_bundle_missing_artifacts(report_bundle_manifest_payload)

    provenance_refs = _export_refs_from_paths(
        run_document.provenance_exports,
        default_run_id=layout.run_id,
        preferred_type="provenance",
    )
    if not provenance_refs:
        provenance_refs = _export_refs_from_paths(
            [
                (layout.relative_run_dir / "prov.json").as_posix(),
                (layout.relative_run_dir / "ro-crate" / "ro-crate-metadata.json").as_posix(),
            ],
            default_run_id=layout.run_id,
            preferred_type="provenance",
        )

    biocompute_refs = _export_refs_from_paths(
        run_document.biocompute_exports,
        default_run_id=layout.run_id,
        preferred_type="biocompute",
    )

    evidence_review_refs = _dedupe_refs(
        [
            ref
            for ref in [
                *run_document.related_artifacts,
                *run_document.outputs,
                *(output for record in run_document.steps for output in record.outputs_produced),
                *report_bundle_expected_refs,
            ]
            if ref.artifact_type == "evidence_review"
        ]
    )
    evidence_card_refs = _linked_evidence_card_refs(base_dir, evidence_review_refs)

    linked_refs = _dedupe_refs(
        [
            run_ref,
            content_hash_ref,
            *run_document.inputs,
            *run_document.outputs,
            *run_document.related_artifacts,
            *provenance_refs,
            *biocompute_refs,
            *report_bundle_expected_refs,
            *( [report_bundle_manifest_ref] if report_bundle_manifest_ref is not None else [] ),
            *( [report_bundle_ref] if report_bundle_ref is not None else [] ),
            *( [protocol_run_ref] if protocol_run_ref is not None else [] ),
            *evidence_card_refs,
        ]
    )

    included_entries: list[dict[str, Any]] = []
    included_refs: list[ArtifactReference] = []
    missing_entries: list[dict[str, Any]] = []

    expected_required_refs: list[ArtifactReference] = [run_ref, content_hash_ref]
    if dataset_manifest_ref is not None:
        expected_required_refs.append(dataset_manifest_ref)
    else:
        missing_entries.append(
            {
                "artifact_type": "dataset_manifest",
                "expected_source_path": (layout.relative_run_dir / "dataset_manifest.yaml").as_posix(),
                "expected_package_path": (layout.relative_run_dir / "dataset_manifest.yaml").as_posix(),
                "reason": (
                    "The workflow run did not retain a canonical dataset_manifest reference, so the dataset link "
                    "cannot be populated in the ELN export bundle."
                ),
            }
        )

    if report_bundle_manifest_ref is not None:
        expected_required_refs.append(report_bundle_manifest_ref)
    else:
        missing_entries.append(
            {
                "artifact_type": "report_bundle_manifest",
                "expected_source_path": (layout.relative_run_dir / _REPORT_BUNDLE_MANIFEST_RELATIVE_PATH).as_posix(),
                "expected_package_path": (layout.relative_run_dir / _REPORT_BUNDLE_MANIFEST_RELATIVE_PATH).as_posix(),
                "reason": (
                    "No terminal report_bundle_manifest was materialized for this workflow run, so the export "
                    "bundle cannot link a machine-readable handoff summary."
                ),
            }
        )

    if report_bundle_ref is not None:
        expected_required_refs.append(report_bundle_ref)
    else:
        missing_entries.append(
            {
                "artifact_type": "report_bundle",
                "expected_source_path": None,
                "expected_package_path": "artifacts/report-bundle/unavailable",
                "reason": (
                    "No report_bundle artifact could be resolved from the report_bundle_manifest, so the "
                    "human-readable handoff artifact is missing from the ELN export bundle."
                ),
            }
        )

    for ref in _dedupe_refs([*expected_required_refs, *linked_refs]):
        target = _resolve_existing_path(base_dir, ref.path)
        if target is None:
            missing_entries.append(
                {
                    "artifact_type": ref.artifact_type,
                    "expected_source_path": ref.path,
                    "expected_package_path": ref.path,
                    "reason": (
                        "The artifact was linked from the workflow record or report bundle but was not present on disk "
                        "when the ELN export bundle was generated."
                    ),
                }
            )
            continue

        included_refs.append(ref)
        included_entries.append(
            {
                "role": _export_role(ref),
                "artifact_type": ref.artifact_type,
                "source_path": ref.path,
                "package_path": ref.path,
                "id": ref.id,
                "run_id": ref.run_id,
                "sha256": _content_digest(target),
                "note": "Packaged recursively because the source path is a directory."
                if target.is_dir()
                else None,
            }
        )

    missing_entries.extend(report_bundle_missing)
    missing_entries = _sorted_missing_entries(_dedupe_missing_entries(missing_entries))
    included_entries = sorted(
        included_entries,
        key=lambda item: (str(item["package_path"]), str(item["artifact_type"])),
    )
    included_refs = _dedupe_refs(sorted(included_refs, key=lambda ref: (ref.path, ref.artifact_type)))

    manifest_payload = {
        "schema_version": run_document.schema_version,
        "artifact_type": "eln_export",
        "id": normalize_identifier(f"eln-export-{layout.workflow}-{layout.run_id.lower()}"),
        "run_id": run_document.run_id,
        "created_at": exported_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_workflow": run_document.source_workflow or layout.workflow,
        "related_artifacts": [ref.model_dump(mode="json") for ref in included_refs],
        "bundle_version": _ELN_EXPORT_BUNDLE_VERSION,
        "scope": "workflow_run_bundle",
        "package_root": _ELN_EXPORT_PACKAGE_ROOT,
        "workflow_version": workflow_version,
        "lifecycle_status": run_document.lifecycle_status,
        "qc_status": run_document.qc_status,
        "workflow_run": run_ref.model_dump(mode="json"),
        "dataset_manifest": dataset_manifest_ref.model_dump(mode="json") if dataset_manifest_ref is not None else None,
        "report_bundle_manifest": (
            report_bundle_manifest_ref.model_dump(mode="json") if report_bundle_manifest_ref is not None else None
        ),
        "report_bundle": report_bundle_ref.model_dump(mode="json") if report_bundle_ref is not None else None,
        "protocol_run": protocol_run_ref.model_dump(mode="json") if protocol_run_ref is not None else None,
        "provenance_exports": [ref.model_dump(mode="json") for ref in provenance_refs],
        "biocompute_exports": [ref.model_dump(mode="json") for ref in biocompute_refs],
        "evidence_review_artifacts": [ref.model_dump(mode="json") for ref in evidence_review_refs],
        "included_artifacts": included_entries,
        "missing_artifacts": missing_entries,
        "unsupported_fields": list(_ELN_VENDOR_UNSUPPORTED_FIELDS),
        "notes": [
            "The archive preserves canonical artifacts under their original artifacts/... relative paths so linked manifests remain portable without path rewriting.",
            "ELN Export V1 packages only persisted on-disk artifacts and never reconstructs missing state from chat history or transient workflow memory.",
            "content_hashes.json intentionally excludes ELN export packaging outputs to avoid self-referential archive hashing while keeping canonical run artifacts reproducible.",
            "Vendor-specific ELN fields remain explicitly unsupported in V1; the portable bundle is the primary interchange format.",
        ],
    }

    export_document = ELNExportArtifact.model_validate(manifest_payload)
    export_payload = export_document.model_dump(mode="json", exclude_none=True)
    manifest_text = json.dumps(export_payload, ensure_ascii=False, indent=2) + "\n"

    manifest_target = layout._track_path(resolve_artifact_path(base_dir, PurePosixPath(manifest_path)))
    manifest_target.parent.mkdir(parents=True, exist_ok=True)

    archive_target = layout._track_path(resolve_artifact_path(base_dir, PurePosixPath(archive_path)))
    archive_target.parent.mkdir(parents=True, exist_ok=True)
    _publish_export_outputs(
        manifest_target=manifest_target,
        manifest_text=manifest_text,
        archive_target=archive_target,
        included_paths=[
            (resolve_artifact_path(base_dir, item["source_path"]), str(item["package_path"]))
            for item in included_entries
        ],
    )
    _refresh_registry_entry(base_dir, manifest_path)
    _refresh_registry_entry(base_dir, archive_path)

    append_export_generated_event(
        base_dir,
        export_type="eln_bundle",
        session_id=session_id,
        run_id=run_document.run_id,
        workflow_id=run_document.source_workflow or layout.workflow,
        artifact_paths=[manifest_path, archive_path],
        lifecycle_status=run_document.lifecycle_status,
    )
    return [manifest_path, archive_path]


def _workflow_end_time(run_document: WorkflowRun) -> datetime:
    step_end_times = [record.end_time for record in run_document.steps if record.end_time is not None]
    return max(step_end_times, default=run_document.created_at)


def _resolve_existing_path(base_dir: Path, relative_path: str) -> Path | None:
    candidate = resolve_artifact_path(base_dir, relative_path)
    return candidate if candidate.exists() else None


def _content_digest(path: Path) -> str:
    if path.is_dir():
        entries: list[dict[str, str]] = []
        for child in sorted(node for node in path.rglob("*") if node.is_file()):
            entries.append(
                {
                    "path": child.relative_to(path).as_posix(),
                    "sha256": compute_content_hash(child.read_bytes()),
                }
            )
        return compute_content_hash(json.dumps(entries, sort_keys=True))
    return compute_content_hash(path.read_bytes())


def _export_refs_from_paths(
    paths: Iterable[str],
    *,
    default_run_id: str,
    preferred_type: str,
) -> list[ArtifactReference]:
    refs: list[ArtifactReference] = []
    for path in paths:
        normalized = str(path).strip()
        if not normalized:
            continue
        artifact_type = preferred_type
        if normalized.endswith("/ro-crate/ro-crate-metadata.json") or normalized.endswith("ro-crate-metadata.json"):
            artifact_type = "ro_crate_metadata"
        refs.append(
            ArtifactReference(
                artifact_type=artifact_type,
                path=normalized,
                run_id=default_run_id,
            )
        )
    return refs


def _load_optional_artifact_ref(base_dir: Path, relative_path: PurePosixPath) -> ArtifactReference | None:
    path = resolve_artifact_path(base_dir, relative_path)
    if not path.exists():
        return None
    try:
        document = load_artifact_document(path)
    except Exception:
        return ArtifactReference(
            artifact_type=relative_path.stem if relative_path.suffix else relative_path.name.replace("-", "_"),
            path=str(relative_path),
        )
    return ArtifactReference(
        artifact_type=document.artifact_type,
        path=str(relative_path),
        id=document.id,
        run_id=document.run_id,
    )


def _load_report_bundle_manifest(
    base_dir: Path,
    layout: RunLayout,
) -> tuple[ArtifactReference | None, dict[str, Any] | None]:
    relative_path = layout.relative_run_dir / _REPORT_BUNDLE_MANIFEST_RELATIVE_PATH
    target = resolve_artifact_path(base_dir, relative_path)
    if not target.exists() or not target.is_file():
        return None, None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (
            ArtifactReference(
                artifact_type="report_bundle_manifest",
                path=relative_path.as_posix(),
                run_id=layout.run_id,
            ),
            None,
        )

    manifest_value = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(manifest_value, dict):
        manifest_value = payload if isinstance(payload, dict) else None
    return (
        ArtifactReference(
            artifact_type="report_bundle_manifest",
            path=relative_path.as_posix(),
            run_id=layout.run_id,
        ),
        manifest_value,
    )


def _report_bundle_ref_from_manifest(
    manifest_payload: Mapping[str, Any] | None,
    *,
    run_id: str,
) -> ArtifactReference | None:
    if not isinstance(manifest_payload, Mapping):
        return None
    report_markdown_path = manifest_payload.get("report_markdown_path")
    if not isinstance(report_markdown_path, str) or not report_markdown_path.strip():
        return None
    return ArtifactReference(
        artifact_type="report_bundle",
        path=report_markdown_path,
        run_id=run_id,
    )


def _report_bundle_expected_refs(manifest_payload: Mapping[str, Any] | None) -> list[ArtifactReference]:
    if not isinstance(manifest_payload, Mapping):
        return []
    raw_items = manifest_payload.get("expected_artifacts")
    if not isinstance(raw_items, list):
        return []
    refs: list[ArtifactReference] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        artifact_type = item.get("artifact_type")
        path = item.get("path")
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            continue
        if not isinstance(path, str) or not path.strip():
            continue
        kwargs: dict[str, Any] = {"artifact_type": artifact_type, "path": path}
        if isinstance(item.get("id"), str) and item["id"].strip():
            kwargs["id"] = item["id"]
        if isinstance(item.get("run_id"), str) and item["run_id"].strip():
            kwargs["run_id"] = item["run_id"]
        refs.append(ArtifactReference(**kwargs))
    return refs


def _report_bundle_missing_artifacts(manifest_payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(manifest_payload, Mapping):
        return []
    raw_items = manifest_payload.get("missing_artifacts")
    if not isinstance(raw_items, list):
        return []
    missing: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        artifact_type = item.get("artifact_type")
        if not isinstance(artifact_type, str) or not artifact_type.strip():
            continue
        expected_path = item.get("expected_path")
        if expected_path is not None and (not isinstance(expected_path, str) or not expected_path.strip()):
            expected_path = None
        rationale = item.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            rationale = "The report bundle recorded this artifact as missing at export time."
        missing.append(
            {
                "artifact_type": artifact_type,
                "expected_source_path": expected_path,
                "expected_package_path": expected_path or f"artifacts/missing/{artifact_type}",
                "reason": rationale,
            }
        )
    return missing


def _linked_evidence_card_refs(
    base_dir: Path,
    evidence_review_refs: Iterable[ArtifactReference],
) -> list[ArtifactReference]:
    refs: list[ArtifactReference] = []
    for ref in evidence_review_refs:
        path = _resolve_existing_path(base_dir, ref.path)
        if path is None:
            continue
        try:
            document = load_artifact_document(path)
        except Exception:
            continue
        if not isinstance(document, EvidenceReviewArtifact):
            continue
        refs.extend(
            related
            for related in document.related_artifacts
            if related.artifact_type == "evidence_card"
        )
    return _dedupe_refs(refs)


def _first_ref(refs: Iterable[ArtifactReference], *, artifact_type: str) -> ArtifactReference | None:
    for ref in refs:
        if ref.artifact_type == artifact_type:
            return ref
    return None


def _export_role(ref: ArtifactReference) -> str:
    if ref.artifact_type == "workflow_run":
        return "workflow_run"
    if ref.artifact_type == "content_hash_manifest":
        return "content_hash_manifest"
    if ref.artifact_type == "dataset_manifest":
        return "dataset_manifest"
    if ref.artifact_type == "report_bundle_manifest":
        return "report_bundle_manifest"
    if ref.artifact_type == "report_bundle":
        return "report_bundle"
    if ref.artifact_type in {"provenance", "ro_crate_metadata"}:
        return "provenance_export"
    if ref.artifact_type == "protocol_run":
        return "protocol_run"
    if ref.artifact_type == "evidence_review":
        return "evidence_review"
    if ref.artifact_type == "evidence_card":
        return "evidence_card"
    if ref.artifact_type == "biocompute":
        return "biocompute_export"
    if ref.artifact_type == "compliance_report":
        return "compliance_report"
    return "linked_artifact"


def _dedupe_refs(refs: Iterable[ArtifactReference]) -> list[ArtifactReference]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for ref in refs:
        key = (ref.artifact_type, ref.path, ref.id, ref.run_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _dedupe_missing_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str, str]] = set()
    for entry in entries:
        artifact_type = str(entry.get("artifact_type", "")).strip()
        expected_source_path = entry.get("expected_source_path")
        if expected_source_path is not None:
            expected_source_path = str(expected_source_path)
        expected_package_path = str(entry.get("expected_package_path", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        key = (artifact_type, expected_source_path, expected_package_path, reason)
        if not artifact_type or not expected_package_path or not reason or key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "artifact_type": artifact_type,
                "expected_source_path": expected_source_path,
                "expected_package_path": expected_package_path,
                "reason": reason,
            }
        )
    return deduped


def _sorted_missing_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda item: (
            str(item.get("expected_package_path") or ""),
            str(item.get("artifact_type") or ""),
        ),
    )


def _publish_export_outputs(
    *,
    manifest_target: Path,
    manifest_text: str,
    archive_target: Path,
    included_paths: Iterable[tuple[Path, str]],
) -> None:
    manifest_tmp = _stage_bytes(manifest_target.parent, manifest_text.encode("utf-8"))
    archive_tmp: Path | None = None
    try:
        archive_tmp = _stage_export_archive(
            archive_target.parent,
            manifest_text=manifest_text,
            included_paths=included_paths,
        )
        _install_staged_outputs(
            [
                (manifest_target, manifest_tmp),
                (archive_target, archive_tmp),
            ]
        )
    finally:
        _remove_if_exists(manifest_tmp)
        if archive_tmp is not None:
            _remove_if_exists(archive_tmp)


def _stage_bytes(parent_dir: Path, content: bytes) -> Path:
    target = _temporary_output_path(parent_dir)
    try:
        target.write_bytes(content)
    except Exception:
        _remove_if_exists(target)
        raise
    return target


def _stage_export_archive(
    parent_dir: Path,
    *,
    manifest_text: str,
    included_paths: Iterable[tuple[Path, str]],
) -> Path:
    target = _temporary_output_path(parent_dir)
    normalized_paths = list(included_paths)
    try:
        _write_deterministic_export_archive(
            target,
            manifest_text=manifest_text,
            included_paths=normalized_paths,
        )
    except Exception:
        _remove_if_exists(target)
        raise
    return target


def _install_staged_outputs(staged_outputs: list[tuple[Path, Path]]) -> None:
    backups: list[tuple[Path, Path]] = []
    installed_targets: list[Path] = []
    try:
        for target, _staged_path in staged_outputs:
            if not target.exists():
                continue
            backup_path = _temporary_output_path(target.parent)
            os.replace(target, backup_path)
            backups.append((target, backup_path))

        for target, staged_path in staged_outputs:
            os.replace(staged_path, target)
            installed_targets.append(target)
    except Exception:
        for target in reversed(installed_targets):
            _remove_if_exists(target)
        for target, backup_path in reversed(backups):
            if backup_path.exists():
                os.replace(backup_path, target)
        raise
    else:
        for _target, backup_path in backups:
            _remove_if_exists(backup_path)


def _temporary_output_path(parent_dir: Path) -> Path:
    for _ in range(32):
        candidate = parent_dir / f".bioapex-export-tmp-{uuid4().hex}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate a temporary export path under {parent_dir}.")


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _refresh_registry_entry(base_dir: Path, relative_path: str) -> None:
    try:
        from .registry import refresh_artifact_registry_path

        refresh_artifact_registry_path(base_dir, relative_path)
    except Exception:
        return


def _write_deterministic_export_archive(
    target: Path,
    *,
    manifest_text: str,
    included_paths: Iterable[tuple[Path, str]],
) -> None:
    with target.open("wb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", filename="", mtime=0) as gzip_handle:
            with tarfile.open(fileobj=gzip_handle, mode="w") as archive:
                written_dirs: set[str] = set()
                _add_directory_entry(
                    archive,
                    written_dirs,
                    PurePosixPath(_ELN_EXPORT_PACKAGE_ROOT),
                )
                _add_file_entry(
                    archive,
                    PurePosixPath(_ELN_EXPORT_PACKAGE_ROOT) / _ELN_EXPORT_ARCHIVE_INTERNAL_MANIFEST,
                    manifest_text.encode("utf-8"),
                )
                for source_path, package_path in sorted(included_paths, key=lambda item: item[1]):
                    _add_source_path(
                        archive,
                        written_dirs,
                        source_path=source_path,
                        archive_path=PurePosixPath(_ELN_EXPORT_PACKAGE_ROOT) / PurePosixPath(package_path),
                    )


def _add_source_path(
    archive: tarfile.TarFile,
    written_dirs: set[str],
    *,
    source_path: Path,
    archive_path: PurePosixPath,
) -> None:
    if source_path.is_dir():
        _add_directory_entry(archive, written_dirs, archive_path)
        for child in sorted(source_path.iterdir(), key=lambda item: item.name):
            _add_source_path(
                archive,
                written_dirs,
                source_path=child,
                archive_path=archive_path / child.name,
            )
        return

    _ensure_parent_directories(archive, written_dirs, archive_path)
    _add_file_entry(archive, archive_path, source_path.read_bytes())


def _ensure_parent_directories(
    archive: tarfile.TarFile,
    written_dirs: set[str],
    archive_path: PurePosixPath,
) -> None:
    parents = list(archive_path.parents)
    for parent in reversed(parents[:-1]):
        _add_directory_entry(archive, written_dirs, parent)


def _add_directory_entry(
    archive: tarfile.TarFile,
    written_dirs: set[str],
    archive_path: PurePosixPath,
) -> None:
    archive_name = archive_path.as_posix().rstrip("/")
    if not archive_name or archive_name in written_dirs:
        return
    info = tarfile.TarInfo(f"{archive_name}/")
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info)
    written_dirs.add(archive_name)


def _add_file_entry(
    archive: tarfile.TarFile,
    archive_path: PurePosixPath,
    content: bytes,
) -> None:
    info = tarfile.TarInfo(archive_path.as_posix())
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info, io.BytesIO(content))
