"""Shared schema, constants, and path helpers for the Slurm tool."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Type

from pydantic import BaseModel, Field, model_validator

from artifacts import (
    ArtifactReference,
    SlurmJobArtifact,
    SlurmResourceRequest,
    SlurmStatusObservation,
)

from .contracts import truncate_text

_TIMEOUT = 15
_MAX_OUTPUT = 8_000

_ALLOWED = {"sbatch", "squeue", "sacct", "scontrol", "sinfo"}
_STRUCTURED_ACTIONS = {"submit", "status"}

_SBATCH_JOB_ID_RE = re.compile(r"Submitted batch job (?P<job_id>[A-Za-z0-9_.-]+)")
_RUN_ID_RE = re.compile(r"^run-(?P<stamp>\d{8}T\d{6}Z)-(?P<suffix>[0-9a-f]{8})$")
_PENDING_STATES = {"CF", "CONFIGURING", "PD", "PENDING"}
_RUNNING_STATES = {"CG", "COMPLETING", "R", "RUNNING", "S", "SI", "SO", "SUSPENDED"}
_COMPLETED_STATES = {"CD", "COMPLETED"}
_FAILED_STATES = {
    "BF",
    "BOOT_FAIL",
    "DL",
    "DEADLINE",
    "F",
    "FAILED",
    "NF",
    "NODE_FAIL",
    "OOM",
    "OUT_OF_MEMORY",
    "PR",
    "PREEMPTED",
    "REVOKED",
    "SE",
    "SPECIAL_EXIT",
}
_CANCELLED_STATES = {"CA", "CANCELLED"}
_TIMED_OUT_STATES = {"TIMEOUT", "TO"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _created_at_from_run_id(run_id: str) -> datetime:
    match = _RUN_ID_RE.fullmatch(run_id)
    if match is None:
        raise ValueError(f"Invalid run_id format: {run_id!r}")
    return datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _dedupe_refs(refs: list[ArtifactReference]) -> list[ArtifactReference]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for ref in refs:
        key = (ref.artifact_type, ref.path, ref.id, ref.run_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _ensure_non_empty(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def _slugify(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return candidate.lower() or "slurm-job"


def _relative_to_base(base_dir: Path, target: Path, *, allow_root: bool = False) -> str:
    try:
        relative = target.resolve().relative_to(base_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Path {target.resolve()} must stay under {base_dir.resolve()}.") from exc
    if not relative.parts:
        if allow_root:
            return "."
        raise ValueError("Path must not resolve to the project root.")
    return relative.as_posix()


def _resolve_under_base(
    base_dir: Path,
    value: str | Path,
    *,
    field_name: str,
    must_exist: bool = False,
    expect_directory: bool = False,
    allow_root: bool = False,
) -> tuple[Path, str]:
    candidate = Path(str(value).strip())
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()

    relative = _relative_to_base(base_dir, resolved, allow_root=allow_root)

    if must_exist and not resolved.exists():
        raise ValueError(f"{field_name} not found: {value}")
    if must_exist and expect_directory and not resolved.is_dir():
        raise ValueError(f"{field_name} must be a directory: {value}")
    if must_exist and not expect_directory and not resolved.is_file():
        raise ValueError(f"{field_name} must be a file: {value}")
    return resolved, relative


def _safe_relative_if_under_base(base_dir: Path, value: str | None, *, allow_root: bool = False) -> str | None:
    if value is None:
        return None
    try:
        _resolved, relative = _resolve_under_base(
            base_dir,
            value,
            field_name="path",
            must_exist=False,
            allow_root=allow_root,
        )
    except ValueError:
        return None
    return relative


def normalize_slurm_status(raw_state: str | None) -> Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
]:
    if raw_state is None or not raw_state.strip():
        return "pending"

    normalized = raw_state.strip().upper()
    normalized = normalized.split()[0].rstrip("+")
    normalized = normalized.split("(")[0]

    if normalized.startswith("CANCELLED") or normalized in _CANCELLED_STATES:
        return "cancelled"
    if normalized.startswith("TIMEOUT") or normalized in _TIMED_OUT_STATES:
        return "timed_out"
    if normalized in _PENDING_STATES:
        return "pending"
    if normalized in _RUNNING_STATES:
        return "running"
    if normalized in _COMPLETED_STATES:
        return "completed"
    if normalized in _FAILED_STATES:
        return "failed"
    return "failed"


def _parse_submission_job_id(stdout_text: str) -> str:
    match = _SBATCH_JOB_ID_RE.search(stdout_text)
    if match is None:
        raise ValueError("sbatch did not return a parseable job ID.")
    return match.group("job_id")


def _truncate_for_storage(value: str) -> str | None:
    if not value.strip():
        return None
    truncated, _was_truncated = truncate_text(value, _MAX_OUTPUT)
    return truncated


def _build_job_related_refs(
    *,
    run_record_ref: ArtifactReference | None,
    script_path: str,
    stdout_path: str | None,
    stderr_path: str | None,
    extra_refs: list[ArtifactReference] | None = None,
) -> list[ArtifactReference]:
    refs: list[ArtifactReference] = []
    if run_record_ref is not None:
        refs.append(run_record_ref)
    refs.append(ArtifactReference(artifact_type="sbatch_script", path=script_path))
    if stdout_path is not None:
        refs.append(ArtifactReference(artifact_type="log_file", path=stdout_path))
    if stderr_path is not None:
        refs.append(ArtifactReference(artifact_type="log_file", path=stderr_path))
    if extra_refs:
        refs.extend(extra_refs)
    return _dedupe_refs(refs)


@dataclass(frozen=True)
class SlurmPersistenceContext:
    run_id: str
    run_dir: Path
    relative_run_dir: PurePosixPath
    run_record_ref: ArtifactReference


@dataclass(frozen=True)
class SlurmQueryResult:
    latest_status: SlurmStatusObservation
    working_directory: str | None
    job_name: str | None
    stdout_path: str | None
    stderr_path: str | None
    raw_stdout: str
    raw_stderr: str
    commands: list[list[str]]


@dataclass(frozen=True)
class SlurmJobOperationResult:
    artifact: SlurmJobArtifact
    summary: str
    raw_stdout: str
    raw_stderr: str
    commands: list[list[str]]


class SlurmToolInput(BaseModel):
    command: str | None = Field(
        default=None,
        description=(
            "Legacy mode. One of: sbatch <script_path>, squeue [options], sacct [options], "
            "scontrol show job <id>, sinfo."
        ),
    )
    action: Literal["submit", "status"] | None = Field(
        default=None,
        description="Structured mode. Prefer 'submit' and 'status' over opaque command strings.",
    )
    script_path: str | None = None
    job_id: str | None = None
    job_record_path: str | None = None
    run_id: str | None = None
    working_directory: str | None = None
    resource_request: SlurmResourceRequest | None = None
    job_name: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None

    @model_validator(mode="after")
    def _validate_contract(self) -> "SlurmToolInput":
        if self.command is not None:
            if any(
                value is not None
                for value in (
                    self.action,
                    self.script_path,
                    self.job_id,
                    self.job_record_path,
                    self.run_id,
                    self.working_directory,
                    self.resource_request,
                    self.job_name,
                    self.stdout_path,
                    self.stderr_path,
                )
            ):
                raise ValueError("Legacy command mode cannot be combined with structured Slurm fields.")
            return self

        if self.action is None:
            raise ValueError("Provide either legacy command or structured action.")
        if self.action not in _STRUCTURED_ACTIONS:
            raise ValueError(f"Unsupported structured action {self.action!r}.")
        if self.action == "submit" and self.script_path is None:
            raise ValueError("Structured submit requires script_path.")
        if self.action == "status" and self.job_record_path is None and self.job_id is None:
            raise ValueError("Structured status requires job_record_path or job_id.")
        return self


__all__ = [
    "_ALLOWED",
    "_CANCELLED_STATES",
    "_COMPLETED_STATES",
    "_FAILED_STATES",
    "_MAX_OUTPUT",
    "_PENDING_STATES",
    "_RUNNING_STATES",
    "_RUN_ID_RE",
    "_SBATCH_JOB_ID_RE",
    "_STRUCTURED_ACTIONS",
    "_TIMED_OUT_STATES",
    "_TIMEOUT",
    "_build_job_related_refs",
    "_created_at_from_run_id",
    "_dedupe_refs",
    "_dump_json",
    "_ensure_non_empty",
    "_parse_submission_job_id",
    "_relative_to_base",
    "_resolve_under_base",
    "_safe_relative_if_under_base",
    "_slugify",
    "_truncate_for_storage",
    "_utcnow",
    "normalize_slurm_status",
    "SlurmJobOperationResult",
    "SlurmPersistenceContext",
    "SlurmQueryResult",
    "SlurmToolInput",
]
