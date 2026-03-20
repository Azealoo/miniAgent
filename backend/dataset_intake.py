"""Deterministic dataset intake validation helpers."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from artifacts import DatasetManifest

DatasetIntakeIssueCode = Literal[
    "invalid_document",
    "missing_field",
    "invalid_value",
    "missing_file",
]


class DatasetIntakeIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: DatasetIntakeIssueCode
    field_path: str
    message: str
    path: str | None = None


class DatasetIntakeValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_path: str
    checked_paths: list[str] = Field(default_factory=list)
    issues: list[DatasetIntakeIssue] = Field(default_factory=list)
    manifest: DatasetManifest | None = None

    @property
    def ok(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if not self.issues:
            return "Dataset intake validation passed."
        details = "; ".join(_format_issue(issue) for issue in self.issues)
        return f"Dataset intake validation failed: {details}"


class DatasetIntakeValidationError(ValueError):
    """Raised when dataset intake validation blocks execution."""

    def __init__(self, result: DatasetIntakeValidationResult):
        self.result = result
        super().__init__(result.summary())


def validate_dataset_intake_manifest(
    base_dir: Path | str,
    manifest_path: str | Path,
    *,
    expected_reference_build: str | None = None,
) -> DatasetIntakeValidationResult:
    base_path = Path(base_dir).resolve()
    raw_manifest_path = str(manifest_path)

    try:
        normalized_manifest_path = _coerce_project_relative_path(base_path, manifest_path)
    except ValueError as exc:
        return DatasetIntakeValidationResult(
            manifest_path=raw_manifest_path,
            issues=[
                DatasetIntakeIssue(
                    code="invalid_value",
                    field_path="manifest_path",
                    message=str(exc),
                    path=raw_manifest_path,
                )
            ],
        )

    checked_paths = [normalized_manifest_path]
    absolute_manifest_path = (base_path / normalized_manifest_path).resolve()
    if not absolute_manifest_path.exists():
        return DatasetIntakeValidationResult(
            manifest_path=normalized_manifest_path,
            checked_paths=checked_paths,
            issues=[
                DatasetIntakeIssue(
                    code="missing_file",
                    field_path="manifest_path",
                    message="Dataset manifest file does not exist.",
                    path=normalized_manifest_path,
                )
            ],
        )

    try:
        payload = _load_document_payload(absolute_manifest_path)
    except Exception as exc:
        return DatasetIntakeValidationResult(
            manifest_path=normalized_manifest_path,
            checked_paths=checked_paths,
            issues=[
                DatasetIntakeIssue(
                    code="invalid_document",
                    field_path="manifest_path",
                    message=f"Dataset manifest could not be parsed: {exc}",
                    path=normalized_manifest_path,
                )
            ],
        )

    if not isinstance(payload, dict):
        return DatasetIntakeValidationResult(
            manifest_path=normalized_manifest_path,
            checked_paths=checked_paths,
            issues=[
                DatasetIntakeIssue(
                    code="invalid_document",
                    field_path="manifest",
                    message="Dataset manifest must deserialize to a mapping.",
                    path=normalized_manifest_path,
                )
            ],
        )

    try:
        manifest = DatasetManifest.model_validate(payload)
    except ValidationError as exc:
        return DatasetIntakeValidationResult(
            manifest_path=normalized_manifest_path,
            checked_paths=checked_paths,
            issues=_dedupe_issues(
                [
                    *_issues_from_validation_error(exc),
                    *_payload_level_issues(
                        payload,
                        expected_reference_build=expected_reference_build,
                    ),
                ]
            ),
        )

    issues = _analysis_ready_issues(
        manifest,
        expected_reference_build=expected_reference_build,
    )
    if manifest.sample_sheet_path is not None:
        issues.extend(
            _missing_file_issue(
                base_path=base_path,
                relative_path=manifest.sample_sheet_path,
                field_path="sample_sheet_path",
            )
        )
        checked_paths.append(manifest.sample_sheet_path)

    for index, source_path in enumerate(manifest.source_files):
        issues.extend(
            _missing_file_issue(
                base_path=base_path,
                relative_path=source_path,
                field_path=f"source_files[{index}]",
            )
        )
        checked_paths.append(source_path)

    return DatasetIntakeValidationResult(
        manifest_path=normalized_manifest_path,
        checked_paths=checked_paths,
        issues=_dedupe_issues(issues),
        manifest=manifest,
    )


def ensure_valid_dataset_intake_manifest(
    base_dir: Path | str,
    manifest_path: str | Path,
    *,
    expected_reference_build: str | None = None,
) -> DatasetIntakeValidationResult:
    result = validate_dataset_intake_manifest(
        base_dir,
        manifest_path,
        expected_reference_build=expected_reference_build,
    )
    if not result.ok:
        raise DatasetIntakeValidationError(result)
    return result


def _coerce_project_relative_path(base_dir: Path, value: str | Path) -> str:
    candidate = Path(str(value))
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            return resolved.relative_to(base_dir).as_posix()
        except ValueError as exc:
            raise ValueError(f"Path {resolved} must stay under {base_dir}.") from exc

    normalized = PurePosixPath(str(value))
    if normalized.is_absolute():
        raise ValueError(f"Path {value!r} must stay relative to the project root.")
    if any(part == ".." for part in normalized.parts):
        raise ValueError(f"Path {value!r} must not escape the project root.")
    if str(normalized).strip() == "":
        raise ValueError("Path must not be empty.")
    return normalized.as_posix()


def _load_document_payload(path: Path) -> dict:
    raw_text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(raw_text)
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(raw_text)
    raise ValueError(f"Unsupported dataset manifest extension: {path.suffix!r}")


def _issues_from_validation_error(exc: ValidationError) -> list[DatasetIntakeIssue]:
    issues: list[DatasetIntakeIssue] = []
    for error in exc.errors():
        field_path = _format_error_location(error.get("loc", ()))
        message = str(error.get("msg", "Invalid value."))
        if field_path == "design" and "condition_fields" in message:
            field_path = "design.condition_fields"
        elif field_path == "design" and "batch_fields" in message:
            field_path = "design.batch_fields"
        error_type = str(error.get("type", "value_error"))
        code: DatasetIntakeIssueCode
        if error_type == "missing":
            code = "missing_field"
        else:
            code = "invalid_value"
        issues.append(
            DatasetIntakeIssue(
                code=code,
                field_path=field_path,
                message=message,
            )
        )
    return issues


def _payload_level_issues(
    payload: dict,
    *,
    expected_reference_build: str | None = None,
) -> list[DatasetIntakeIssue]:
    issues: list[DatasetIntakeIssue] = []

    sample_sheet_path = payload.get("sample_sheet_path")
    if not _has_non_empty_value(sample_sheet_path):
        issues.append(
            DatasetIntakeIssue(
                code="missing_field",
                field_path="sample_sheet_path",
                message="Analysis-ready dataset manifests must include sample_sheet_path.",
            )
        )

    reference_build = payload.get("reference_build")
    reference_resource = payload.get("reference_resource")
    if not _has_non_empty_value(reference_build) and not _has_non_empty_value(reference_resource):
        issues.append(
            DatasetIntakeIssue(
                code="missing_field",
                field_path="manifest",
                message="Dataset manifests must include at least one of reference_build or reference_resource.",
            )
        )

    design = payload.get("design")
    if not isinstance(design, dict):
        return issues
    if design.get("analysis_kind") != "comparative":
        return issues

    condition_fields = design.get("condition_fields")
    if not isinstance(condition_fields, list) or not any(str(item).strip() for item in condition_fields):
        issues.append(
            DatasetIntakeIssue(
                code="missing_field" if condition_fields is None else "invalid_value",
                field_path="design.condition_fields",
                message="Comparative dataset designs must include non-empty condition_fields.",
            )
        )

    if "batch_fields" not in design or design.get("batch_fields") is None:
        issues.append(
            DatasetIntakeIssue(
                code="missing_field",
                field_path="design.batch_fields",
                message=(
                    "Comparative dataset designs must declare batch_fields explicitly "
                    "(use [] when no batch field applies)."
                ),
            )
        )

    if expected_reference_build is not None:
        if not _has_non_empty_value(reference_build):
            issues.append(
                DatasetIntakeIssue(
                    code="missing_field",
                    field_path="reference_build",
                    message=(
                        "This workflow requires manifest.reference_build so it can be validated "
                        "against the workflow input reference_build."
                    ),
                )
            )
        elif str(reference_build).strip() != expected_reference_build:
            issues.append(
                DatasetIntakeIssue(
                    code="invalid_value",
                    field_path="reference_build",
                    message=(
                        f"Manifest reference_build {reference_build!r} does not match "
                        f"workflow input reference_build {expected_reference_build!r}."
                    ),
                )
            )
    return issues


def _analysis_ready_issues(
    manifest: DatasetManifest,
    *,
    expected_reference_build: str | None,
) -> list[DatasetIntakeIssue]:
    issues: list[DatasetIntakeIssue] = []

    if manifest.sample_sheet_path is None:
        issues.append(
            DatasetIntakeIssue(
                code="missing_field",
                field_path="sample_sheet_path",
                message="Analysis-ready dataset manifests must include sample_sheet_path.",
            )
        )

    if not _has_non_empty_value(manifest.reference_build) and not _has_non_empty_value(
        manifest.reference_resource
    ):
        issues.append(
            DatasetIntakeIssue(
                code="missing_field",
                field_path="manifest",
                message="Dataset manifests must include at least one of reference_build or reference_resource.",
            )
        )

    if manifest.design.analysis_kind == "comparative":
        if not manifest.design.condition_fields:
            issues.append(
                DatasetIntakeIssue(
                    code="missing_field",
                    field_path="design.condition_fields",
                    message="Comparative dataset designs must include non-empty condition_fields.",
                )
            )
        if manifest.design.batch_fields is None:
            issues.append(
                DatasetIntakeIssue(
                    code="missing_field",
                    field_path="design.batch_fields",
                    message=(
                        "Comparative dataset designs must declare batch_fields explicitly "
                        "(use [] when no batch field applies)."
                    ),
                )
            )

    if expected_reference_build is not None:
        if manifest.reference_build is None:
            issues.append(
                DatasetIntakeIssue(
                    code="missing_field",
                    field_path="reference_build",
                    message=(
                        "This workflow requires manifest.reference_build so it can be validated "
                        "against the workflow input reference_build."
                    ),
                )
            )
        elif manifest.reference_build != expected_reference_build:
            issues.append(
                DatasetIntakeIssue(
                    code="invalid_value",
                    field_path="reference_build",
                    message=(
                        f"Manifest reference_build {manifest.reference_build!r} does not match "
                        f"workflow input reference_build {expected_reference_build!r}."
                    ),
                )
            )

    return issues


def _format_error_location(location: tuple[object, ...]) -> str:
    if not location:
        return "manifest"

    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if not parts:
                parts.append(f"[{item}]")
            else:
                parts[-1] = f"{parts[-1]}[{item}]"
            continue
        token = str(item)
        if not parts:
            parts.append(token)
        else:
            parts.append(token)
    return ".".join(parts)


def _missing_file_issue(
    *,
    base_path: Path,
    relative_path: str,
    field_path: str,
) -> list[DatasetIntakeIssue]:
    candidate = (base_path / relative_path).resolve()
    if candidate.exists():
        return []
    return [
        DatasetIntakeIssue(
            code="missing_file",
            field_path=field_path,
            message="Referenced file does not exist.",
            path=relative_path,
        )
    ]


def _format_issue(issue: DatasetIntakeIssue) -> str:
    path_suffix = f" ({issue.path})" if issue.path else ""
    return f"{issue.field_path}{path_suffix}: {issue.message}"


def _dedupe_issues(issues: list[DatasetIntakeIssue]) -> list[DatasetIntakeIssue]:
    seen: set[tuple[str, str, str, str | None]] = set()
    deduped: list[DatasetIntakeIssue] = []
    for issue in issues:
        key = (issue.code, issue.field_path, issue.message, issue.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _has_non_empty_value(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
