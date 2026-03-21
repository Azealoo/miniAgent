"""Structured, safe Slurm run manager with legacy command compatibility."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

from artifacts import (
    ArtifactReference,
    SCHEMA_PACK_VERSION,
    SlurmJobArtifact,
    SlurmJobLogCapture,
    SlurmResourceRequest,
    SlurmStatusObservation,
    generate_run_id,
    load_artifact_document,
    prepare_run_directory,
    resolve_artifact_path,
    stable_artifact_name,
)

from .contracts import (
    artifact_ref,
    blocked_result,
    empty_result,
    execution_error_result,
    invalid_input_result,
    retriable_error_result,
    success_result,
    truncate_text,
)

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


def _normalize_log_path(
    base_dir: Path,
    value: str,
) -> str:
    raw = _ensure_non_empty(value, field_name="log path")
    placeholder = "__SLURM_JOB_ID__"
    substituted = raw.replace("%j", placeholder)
    _resolved, relative = _resolve_under_base(
        base_dir,
        substituted,
        field_name="log path",
        must_exist=False,
    )
    return relative.replace(placeholder, "%j")


def _materialize_log_path(template_path: str | None, job_id: str | None) -> str | None:
    if template_path is None:
        return None
    if job_id is None:
        return template_path
    return template_path.replace("%j", job_id)


def _default_log_templates(
    *,
    run_relative_dir: PurePosixPath,
    script_path: str,
    job_name: str | None,
) -> tuple[str, str]:
    label = _slugify(job_name or Path(script_path).stem)
    log_dir = run_relative_dir / "outputs" / "generated" / "slurm"
    return (
        (log_dir / f"{label}-%j.stdout.log").as_posix(),
        (log_dir / f"{label}-%j.stderr.log").as_posix(),
    )


def _ensure_log_parents(base_dir: Path, *relative_paths: str | None) -> None:
    for path in relative_paths:
        if path is None:
            continue
        placeholder_path = Path(path.replace("%j", "__SLURM_JOB_ID__"))
        target_dir = resolve_artifact_path(base_dir, placeholder_path.parent)
        target_dir.mkdir(parents=True, exist_ok=True)


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


def _build_sbatch_argv(
    *,
    script_path: str,
    working_directory: str | None,
    resource_request: SlurmResourceRequest,
    job_name: str | None,
    stdout_path: str | None,
    stderr_path: str | None,
    export_environment: Mapping[str, str] | None = None,
) -> list[str]:
    argv = ["sbatch"]
    if job_name:
        argv.extend(["--job-name", job_name])
    if resource_request.cpus is not None:
        argv.extend(["--cpus-per-task", str(resource_request.cpus)])
    if resource_request.memory is not None:
        argv.extend(["--mem", resource_request.memory])
    if resource_request.wall_time is not None:
        argv.extend(["--time", resource_request.wall_time])
    if resource_request.gpus not in {None, 0}:
        argv.extend(["--gpus", str(resource_request.gpus)])
    if resource_request.partition is not None:
        argv.extend(["--partition", resource_request.partition])
    if resource_request.qos is not None:
        argv.extend(["--qos", resource_request.qos])
    if resource_request.account is not None:
        argv.extend(["--account", resource_request.account])
    if resource_request.constraint is not None:
        argv.extend(["--constraint", resource_request.constraint])
    if stdout_path is not None:
        argv.extend(["--output", stdout_path])
    if stderr_path is not None:
        argv.extend(["--error", stderr_path])
    if working_directory is not None:
        argv.extend(["--chdir", working_directory])
    if export_environment:
        argv.extend(["--export", "ALL"])
    argv.append(script_path)
    return argv


def _truncate_for_storage(value: str) -> str | None:
    if not value.strip():
        return None
    truncated, _was_truncated = truncate_text(value, _MAX_OUTPUT)
    return truncated


def _read_runtime_log(base_dir: Path, relative_path: str | None) -> str | None:
    if relative_path is None:
        return None
    try:
        resolved, _relative = _resolve_under_base(
            base_dir,
            relative_path,
            field_name="log path",
            must_exist=False,
        )
    except ValueError:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    try:
        with resolved.open("r", encoding="utf-8", errors="replace") as handle:
            preview = handle.read(_MAX_OUTPUT + 1)
        return _truncate_for_storage(preview)
    except OSError:
        return None


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


def _find_run_dir(base_dir: Path, run_id: str) -> Path | None:
    artifacts_root = base_dir / "artifacts"
    if not artifacts_root.exists():
        return None
    matches = sorted(path for path in artifacts_root.glob(f"*/*/{run_id}") if path.is_dir())
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"Multiple artifact run directories were found for run_id {run_id!r}.")
    return matches[0]


def ensure_slurm_persistence_context(
    base_dir: Path | str,
    *,
    run_id: str | None = None,
) -> SlurmPersistenceContext:
    base_path = Path(base_dir).resolve()
    existing_run_dir = _find_run_dir(base_path, run_id) if run_id else None
    if existing_run_dir is None:
        layout = prepare_run_directory(
            base_path,
            "slurm-jobs",
            run_id=run_id or generate_run_id(),
            created_at=_created_at_from_run_id(run_id) if run_id else None,
        )
        return SlurmPersistenceContext(
            run_id=layout.run_id,
            run_dir=layout.run_dir,
            relative_run_dir=layout.relative_run_dir,
            run_record_ref=ArtifactReference(
                artifact_type="workflow_run",
                path=(layout.relative_run_dir / "run.json").as_posix(),
                run_id=layout.run_id,
            ),
        )

    relative_run_dir = PurePosixPath(existing_run_dir.relative_to(base_path).as_posix())
    return SlurmPersistenceContext(
        run_id=run_id or existing_run_dir.name,
        run_dir=existing_run_dir,
        relative_run_dir=relative_run_dir,
        run_record_ref=ArtifactReference(
            artifact_type="workflow_run",
            path=(relative_run_dir / "run.json").as_posix(),
            run_id=run_id or existing_run_dir.name,
        ),
    )


def _choose_job_record_relpath(
    *,
    base_dir: Path,
    context: SlurmPersistenceContext,
    job_id: str,
    explicit_path: str | None = None,
) -> str:
    if explicit_path is not None:
        _resolved, relative = _resolve_under_base(
            base_dir,
            explicit_path,
            field_name="job_record_path",
            must_exist=False,
        )
        return relative

    stable_relpath = (context.relative_run_dir / stable_artifact_name("slurm_job")).as_posix()
    stable_path = resolve_artifact_path(base_dir, stable_relpath)
    if not stable_path.exists():
        return stable_relpath

    generated_relpath = (
        context.relative_run_dir
        / "outputs"
        / "generated"
        / "slurm"
        / f"slurm-job-{_slugify(job_id)}.json"
    )
    return generated_relpath.as_posix()


def _parse_submission_job_id(stdout_text: str) -> str:
    match = _SBATCH_JOB_ID_RE.search(stdout_text)
    if match is None:
        raise ValueError("sbatch did not return a parseable job ID.")
    return match.group("job_id")


def submit_slurm_job(
    *,
    base_dir: Path | str,
    run_id: str,
    run_relative_dir: PurePosixPath,
    script_path: str,
    resource_request: SlurmResourceRequest | dict[str, Any] | None = None,
    working_directory: str | None = None,
    job_name: str | None = None,
    stdout_path: str | None = None,
    stderr_path: str | None = None,
    run_record_ref: ArtifactReference | None = None,
    extra_related_refs: list[ArtifactReference] | None = None,
    source_workflow: str | None = None,
    source_tool: str | None = "slurm_tool",
    export_environment: Mapping[str, str] | None = None,
) -> SlurmJobOperationResult:
    base_path = Path(base_dir).resolve()
    resource_model = (
        resource_request
        if isinstance(resource_request, SlurmResourceRequest)
        else SlurmResourceRequest.model_validate(resource_request or {})
    )
    _script_resolved, script_relpath = _resolve_under_base(
        base_path,
        script_path,
        field_name="script_path",
        must_exist=True,
    )

    if working_directory is None:
        working_directory_relpath = "."
    else:
        _working_directory_resolved, working_directory_relpath = _resolve_under_base(
            base_path,
            working_directory,
            field_name="working_directory",
            must_exist=True,
            expect_directory=True,
            allow_root=True,
        )

    if stdout_path is None or stderr_path is None:
        default_stdout, default_stderr = _default_log_templates(
            run_relative_dir=run_relative_dir,
            script_path=script_relpath,
            job_name=job_name,
        )
        stdout_template = _normalize_log_path(base_path, stdout_path) if stdout_path is not None else default_stdout
        stderr_template = _normalize_log_path(base_path, stderr_path) if stderr_path is not None else default_stderr
    else:
        stdout_template = _normalize_log_path(base_path, stdout_path)
        stderr_template = _normalize_log_path(base_path, stderr_path)

    _ensure_log_parents(base_path, stdout_template, stderr_template)

    argv = _build_sbatch_argv(
        script_path=script_relpath,
        working_directory=working_directory_relpath,
        resource_request=resource_model,
        job_name=job_name,
        stdout_path=stdout_template,
        stderr_path=stderr_template,
        export_environment=export_environment,
    )
    submission_env = None
    if export_environment:
        submission_env = os.environ.copy()
        submission_env.update(export_environment)
    completed = subprocess.run(
        argv,
        cwd=base_path,
        shell=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        env=submission_env,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "sbatch failed.")

    job_id = _parse_submission_job_id(completed.stdout)
    submitted_at = _utcnow()
    actual_stdout_path = _materialize_log_path(stdout_template, job_id)
    actual_stderr_path = _materialize_log_path(stderr_template, job_id)

    related_refs = _build_job_related_refs(
        run_record_ref=run_record_ref,
        script_path=script_relpath,
        stdout_path=actual_stdout_path,
        stderr_path=actual_stderr_path,
        extra_refs=extra_related_refs,
    )
    latest_status = SlurmStatusObservation(
        observed_at=submitted_at,
        source="submission",
        normalized_status="pending",
        raw_state="SUBMITTED",
        raw_reason=None,
        exit_code=None,
    )
    artifact = SlurmJobArtifact(
        schema_version=SCHEMA_PACK_VERSION,
        artifact_type="slurm_job",
        id=f"slurm-job-{_slugify(job_id)}-{run_id.lower()}",
        run_id=run_id,
        created_at=submitted_at,
        source_workflow=source_workflow,
        source_tool=source_tool,
        related_artifacts=related_refs,
        job_id=job_id,
        job_name=job_name or Path(script_relpath).stem,
        script_path=script_relpath,
        working_directory=working_directory_relpath,
        submission_command=argv,
        environment_keys=sorted(export_environment) if export_environment else [],
        resource_request=resource_model,
        status="pending",
        submitted_at=submitted_at,
        completed_at=None,
        latest_status=latest_status,
        status_history=[latest_status],
        logs=SlurmJobLogCapture(
            stdout_path=actual_stdout_path,
            stderr_path=actual_stderr_path,
            submission_stdout=_truncate_for_storage(completed.stdout),
            submission_stderr=_truncate_for_storage(completed.stderr),
        ),
    )
    return SlurmJobOperationResult(
        artifact=artifact,
        summary=f"Submitted Slurm job {job_id} for {script_relpath}.",
        raw_stdout=completed.stdout,
        raw_stderr=completed.stderr,
        commands=[argv],
    )


def _parse_squeue_query(base_dir: Path, job_id: str) -> SlurmQueryResult | None:
    argv = ["squeue", "-h", "-j", job_id, "-o", "%i|%T|%R|%Z|%j"]
    completed = subprocess.run(
        argv,
        cwd=base_dir,
        shell=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    stdout_text = completed.stdout.strip()
    if completed.returncode != 0 or not stdout_text:
        return None

    first_line = stdout_text.splitlines()[0]
    parts = first_line.split("|", 4)
    if len(parts) != 5:
        return None

    raw_state = parts[1].strip() or None
    raw_reason = parts[2].strip() or None
    working_directory = _safe_relative_if_under_base(base_dir, parts[3].strip(), allow_root=True)
    job_name = parts[4].strip() or None
    latest_status = SlurmStatusObservation(
        observed_at=_utcnow(),
        source="squeue",
        normalized_status=normalize_slurm_status(raw_state),
        raw_state=raw_state,
        raw_reason=raw_reason,
        exit_code=None,
    )
    return SlurmQueryResult(
        latest_status=latest_status,
        working_directory=working_directory,
        job_name=job_name,
        stdout_path=None,
        stderr_path=None,
        raw_stdout=completed.stdout,
        raw_stderr=completed.stderr,
        commands=[argv],
    )


def _select_sacct_row(lines: list[str], job_id: str) -> list[str] | None:
    def _matches(candidate: str) -> bool:
        if candidate == job_id:
            return True
        return candidate.split(".", 1)[0] == job_id

    parsed_rows = [line.split("|") for line in lines if line.strip()]
    for row in parsed_rows:
        if row and _matches(row[0].strip()):
            return row
    return None


def _parse_sacct_query(base_dir: Path, job_id: str) -> SlurmQueryResult | None:
    argv = [
        "sacct",
        "-n",
        "-P",
        "-j",
        job_id,
        "-o",
        "JobIDRaw,State,ExitCode,Elapsed,Timelimit,Reason,WorkDir,StdOut,StdErr,JobName",
    ]
    completed = subprocess.run(
        argv,
        cwd=base_dir,
        shell=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    stdout_text = completed.stdout.strip()
    if completed.returncode != 0 or not stdout_text:
        return None

    row = _select_sacct_row(stdout_text.splitlines(), job_id)
    if row is None or len(row) < 10:
        return None

    raw_state = row[1].strip() or None
    exit_code = row[2].strip() or None
    raw_reason = row[5].strip() or None
    working_directory = _safe_relative_if_under_base(base_dir, row[6].strip(), allow_root=True)
    stdout_path = _safe_relative_if_under_base(base_dir, row[7].strip())
    stderr_path = _safe_relative_if_under_base(base_dir, row[8].strip())
    job_name = row[9].strip() or None
    latest_status = SlurmStatusObservation(
        observed_at=_utcnow(),
        source="sacct",
        normalized_status=normalize_slurm_status(raw_state),
        raw_state=raw_state,
        raw_reason=raw_reason,
        exit_code=exit_code,
    )
    return SlurmQueryResult(
        latest_status=latest_status,
        working_directory=working_directory,
        job_name=job_name,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        raw_stdout=completed.stdout,
        raw_stderr=completed.stderr,
        commands=[argv],
    )


def _parse_scontrol_query(base_dir: Path, job_id: str) -> SlurmQueryResult | None:
    argv = ["scontrol", "show", "job", job_id, "-o"]
    completed = subprocess.run(
        argv,
        cwd=base_dir,
        shell=False,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    stdout_text = completed.stdout.strip()
    if completed.returncode != 0 or not stdout_text:
        return None

    line = stdout_text.splitlines()[0]
    fields: dict[str, str] = {}
    for token in line.split():
        key, separator, raw_value = token.partition("=")
        if separator != "=":
            continue
        fields[key] = raw_value

    raw_state = fields.get("JobState")
    raw_reason = fields.get("Reason")
    working_directory = _safe_relative_if_under_base(base_dir, fields.get("WorkDir"), allow_root=True)
    stdout_path = _safe_relative_if_under_base(base_dir, fields.get("StdOut"))
    stderr_path = _safe_relative_if_under_base(base_dir, fields.get("StdErr"))
    job_name = fields.get("JobName")
    exit_code = fields.get("ExitCode")
    latest_status = SlurmStatusObservation(
        observed_at=_utcnow(),
        source="scontrol",
        normalized_status=normalize_slurm_status(raw_state),
        raw_state=raw_state,
        raw_reason=raw_reason,
        exit_code=exit_code,
    )
    return SlurmQueryResult(
        latest_status=latest_status,
        working_directory=working_directory,
        job_name=job_name,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        raw_stdout=completed.stdout,
        raw_stderr=completed.stderr,
        commands=[argv],
    )


def query_slurm_job_status(
    *,
    base_dir: Path | str,
    job_id: str,
) -> SlurmQueryResult:
    base_path = Path(base_dir).resolve()

    squeue_result = _parse_squeue_query(base_path, job_id)
    if squeue_result is not None:
        return squeue_result

    sacct_result = _parse_sacct_query(base_path, job_id)
    if sacct_result is not None:
        return sacct_result

    scontrol_result = _parse_scontrol_query(base_path, job_id)
    if scontrol_result is not None:
        return scontrol_result

    raise RuntimeError(f"Could not determine Slurm status for job {job_id}.")


def load_slurm_job_artifact(base_dir: Path | str, relative_path: str) -> SlurmJobArtifact:
    document = load_artifact_document(resolve_artifact_path(base_dir, relative_path))
    if not isinstance(document, SlurmJobArtifact):
        raise ValueError(f"{relative_path!r} is not a slurm_job artifact.")
    return document


def refresh_slurm_job_artifact(
    *,
    base_dir: Path | str,
    artifact: SlurmJobArtifact,
) -> SlurmJobOperationResult:
    base_path = Path(base_dir).resolve()
    query_result = query_slurm_job_status(base_dir=base_path, job_id=artifact.job_id)
    history = [*artifact.status_history, query_result.latest_status]
    status = query_result.latest_status.normalized_status
    completed_at = artifact.completed_at
    if status in {"completed", "failed", "cancelled", "timed_out"} and completed_at is None:
        completed_at = query_result.latest_status.observed_at

    stdout_path = query_result.stdout_path or artifact.logs.stdout_path
    stderr_path = query_result.stderr_path or artifact.logs.stderr_path
    runtime_stdout = _read_runtime_log(base_path, stdout_path) or artifact.logs.runtime_stdout
    runtime_stderr = _read_runtime_log(base_path, stderr_path) or artifact.logs.runtime_stderr
    logs = artifact.logs.model_copy(
        update={
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "runtime_stdout": runtime_stdout,
            "runtime_stderr": runtime_stderr,
        }
    )
    related_refs = _build_job_related_refs(
        run_record_ref=next(
            (ref for ref in artifact.related_artifacts if ref.artifact_type == "workflow_run"),
            None,
        ),
        script_path=artifact.script_path,
        stdout_path=logs.stdout_path,
        stderr_path=logs.stderr_path,
        extra_refs=[
            ref
            for ref in artifact.related_artifacts
            if ref.artifact_type not in {"workflow_run", "sbatch_script", "log_file"}
        ],
    )
    refreshed = SlurmJobArtifact.model_validate(
        artifact.model_copy(
            update={
                "job_name": query_result.job_name or artifact.job_name,
                "working_directory": query_result.working_directory or artifact.working_directory,
                "status": status,
                "completed_at": completed_at,
                "latest_status": query_result.latest_status,
                "status_history": history,
                "logs": logs,
                "related_artifacts": related_refs,
            }
        ).model_dump(mode="json")
    )
    return SlurmJobOperationResult(
        artifact=refreshed,
        summary=f"Job {artifact.job_id} status: {status}.",
        raw_stdout=query_result.raw_stdout,
        raw_stderr=query_result.raw_stderr,
        commands=query_result.commands,
    )


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


class SlurmTool(BaseTool):
    name: str = "slurm_tool"
    description: str = (
        "Manage Slurm jobs safely. Prefer structured actions for submit/status with explicit "
        "resource contracts, and use legacy command mode only for compatible sbatch/squeue/sacct/"
        "scontrol/sinfo commands."
    )
    args_schema: Type[BaseModel] = SlurmToolInput
    response_format: str = "content_and_artifact"
    base_dir: str = ""

    def _run(
        self,
        command: str | None = None,
        action: Literal["submit", "status"] | None = None,
        script_path: str | None = None,
        job_id: str | None = None,
        job_record_path: str | None = None,
        run_id: str | None = None,
        working_directory: str | None = None,
        resource_request: SlurmResourceRequest | dict[str, Any] | None = None,
        job_name: str | None = None,
        stdout_path: str | None = None,
        stderr_path: str | None = None,
    ) -> tuple[str, dict]:
        if command is not None:
            return self._run_legacy_command(command)
        if action == "submit":
            return self._run_structured_submit(
                script_path=script_path or "",
                run_id=run_id,
                working_directory=working_directory,
                resource_request=resource_request,
                job_name=job_name,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                job_record_path=job_record_path,
            )
        if action == "status":
            return self._run_structured_status(
                job_id=job_id,
                job_record_path=job_record_path,
            )
        return invalid_input_result(self.name, "Unsupported Slurm action.")

    def _run_structured_submit(
        self,
        *,
        script_path: str,
        run_id: str | None,
        working_directory: str | None,
        resource_request: SlurmResourceRequest | dict[str, Any] | None,
        job_name: str | None,
        stdout_path: str | None,
        stderr_path: str | None,
        job_record_path: str | None,
    ) -> tuple[str, dict]:
        base_path = Path(self.base_dir).resolve()
        try:
            context = ensure_slurm_persistence_context(base_path, run_id=run_id)
            operation = submit_slurm_job(
                base_dir=base_path,
                run_id=context.run_id,
                run_relative_dir=context.relative_run_dir,
                script_path=script_path,
                resource_request=resource_request,
                working_directory=working_directory,
                job_name=job_name,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                run_record_ref=context.run_record_ref,
                source_tool=self.name,
            )
            persisted_relpath = _choose_job_record_relpath(
                base_dir=base_path,
                context=context,
                job_id=operation.artifact.job_id,
                explicit_path=job_record_path,
            )
            target = resolve_artifact_path(base_path, persisted_relpath)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_dump_json(operation.artifact.model_dump(mode="json")), encoding="utf-8")
            structured_payload = {
                "action": "submit",
                "job_id": operation.artifact.job_id,
                "status": operation.artifact.status,
                "run_id": operation.artifact.run_id,
                "script_path": operation.artifact.script_path,
                "working_directory": operation.artifact.working_directory,
                "resource_request": operation.artifact.resource_request.model_dump(mode="json"),
                "job_record_path": persisted_relpath,
                "stdout_path": operation.artifact.logs.stdout_path,
                "stderr_path": operation.artifact.logs.stderr_path,
                "environment_keys": operation.artifact.environment_keys,
                "submission_command": operation.artifact.submission_command,
                "submission_stdout": operation.artifact.logs.submission_stdout,
                "submission_stderr": operation.artifact.logs.submission_stderr,
            }
            refs = [
                artifact_ref(
                    path=persisted_relpath,
                    artifact_type="slurm_job",
                    identifier=operation.artifact.id,
                ),
                artifact_ref(path=operation.artifact.script_path, artifact_type="sbatch_script"),
            ]
            if operation.artifact.logs.stdout_path is not None:
                refs.append(artifact_ref(path=operation.artifact.logs.stdout_path, artifact_type="log_file"))
            if operation.artifact.logs.stderr_path is not None:
                refs.append(artifact_ref(path=operation.artifact.logs.stderr_path, artifact_type="log_file"))
            return success_result(
                self.name,
                f"{operation.summary} Job record saved to {persisted_relpath}.",
                structured_payload=structured_payload,
                artifact_refs=refs,
                metadata={
                    "action": "submit",
                    "working_directory": operation.artifact.working_directory,
                },
            )
        except subprocess.TimeoutExpired:
            return retriable_error_result(self.name, "Structured Slurm submission timed out.")
        except ValueError as exc:
            return invalid_input_result(self.name, str(exc))
        except RuntimeError as exc:
            return execution_error_result(self.name, str(exc))
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

    def _run_structured_status(
        self,
        *,
        job_id: str | None,
        job_record_path: str | None,
    ) -> tuple[str, dict]:
        base_path = Path(self.base_dir).resolve()
        try:
            if job_record_path is not None:
                existing = load_slurm_job_artifact(base_path, job_record_path)
                operation = refresh_slurm_job_artifact(base_dir=base_path, artifact=existing)
                target = resolve_artifact_path(base_path, job_record_path)
                target.write_text(_dump_json(operation.artifact.model_dump(mode="json")), encoding="utf-8")
                structured_payload = {
                    "action": "status",
                    "job_id": operation.artifact.job_id,
                    "status": operation.artifact.status,
                    "job_record_path": job_record_path,
                    "working_directory": operation.artifact.working_directory,
                    "stdout_path": operation.artifact.logs.stdout_path,
                    "stderr_path": operation.artifact.logs.stderr_path,
                    "environment_keys": operation.artifact.environment_keys,
                    "runtime_stdout": operation.artifact.logs.runtime_stdout,
                    "runtime_stderr": operation.artifact.logs.runtime_stderr,
                    "latest_status": operation.artifact.latest_status.model_dump(mode="json"),
                }
                refs = [
                    artifact_ref(
                        path=job_record_path,
                        artifact_type="slurm_job",
                        identifier=operation.artifact.id,
                    )
                ]
                if operation.artifact.logs.stdout_path is not None:
                    refs.append(artifact_ref(path=operation.artifact.logs.stdout_path, artifact_type="log_file"))
                if operation.artifact.logs.stderr_path is not None:
                    refs.append(artifact_ref(path=operation.artifact.logs.stderr_path, artifact_type="log_file"))
                return success_result(
                    self.name,
                    operation.summary,
                    structured_payload=structured_payload,
                    artifact_refs=refs,
                    metadata={
                        "action": "status",
                        "status_source": operation.artifact.latest_status.source,
                    },
                )

            queried_job_id = _ensure_non_empty(job_id or "", field_name="job_id")
            query_result = query_slurm_job_status(base_dir=base_path, job_id=queried_job_id)
            structured_payload = {
                "action": "status",
                "job_id": queried_job_id,
                "status": query_result.latest_status.normalized_status,
                "latest_status": query_result.latest_status.model_dump(mode="json"),
                "working_directory": query_result.working_directory,
                "job_name": query_result.job_name,
                "stdout_path": query_result.stdout_path,
                "stderr_path": query_result.stderr_path,
            }
            refs = []
            if query_result.stdout_path is not None:
                refs.append(artifact_ref(path=query_result.stdout_path, artifact_type="log_file"))
            if query_result.stderr_path is not None:
                refs.append(artifact_ref(path=query_result.stderr_path, artifact_type="log_file"))
            return success_result(
                self.name,
                f"Job {queried_job_id} status: {query_result.latest_status.normalized_status}.",
                structured_payload=structured_payload,
                artifact_refs=refs,
                metadata={
                    "action": "status",
                    "status_source": query_result.latest_status.source,
                },
            )
        except subprocess.TimeoutExpired:
            return retriable_error_result(self.name, "Structured Slurm status query timed out.")
        except ValueError as exc:
            return invalid_input_result(self.name, str(exc))
        except RuntimeError as exc:
            return execution_error_result(self.name, str(exc))
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

    def _run_legacy_command(self, command: str) -> tuple[str, dict]:
        try:
            parts = shlex.split(command.strip())
        except ValueError as exc:
            return invalid_input_result(
                self.name,
                f"Invalid command syntax: {exc}",
                metadata={"command": command},
            )

        if not parts:
            return invalid_input_result(
                self.name,
                "Empty command.",
                metadata={"command": command},
            )
        cmd_name = parts[0].lower()
        if cmd_name not in _ALLOWED:
            return blocked_result(
                self.name,
                f"Only these Slurm commands are allowed: {sorted(_ALLOWED)}.",
                metadata={"command": command, "subcommand": cmd_name},
            )

        script_ref = None
        if cmd_name == "sbatch":
            script_arg = next(
                (part for part in parts[1:] if not part.startswith("-") and "=" not in part),
                None,
            )
            if script_arg is None:
                return invalid_input_result(
                    self.name,
                    "sbatch requires a script path.",
                    metadata={"command": command, "subcommand": cmd_name},
                )
            try:
                script_resolved, script_relpath = _resolve_under_base(
                    Path(self.base_dir).resolve(),
                    script_arg,
                    field_name="script_path",
                    must_exist=True,
                )
            except ValueError as exc:
                message = str(exc)
                if "must stay under" in message:
                    return blocked_result(
                        self.name,
                        "sbatch path must be under project directory.",
                        metadata={"command": command, "subcommand": cmd_name, "script_path": script_arg},
                    )
                return invalid_input_result(
                    self.name,
                    message,
                    metadata={"command": command, "subcommand": cmd_name, "script_path": script_arg},
                )
            parts = [parts[0], *parts[1:]]
            script_ref = artifact_ref(path=script_relpath, label="sbatch_script")

        try:
            cwd = Path(self.base_dir) if self.base_dir else None
            result = subprocess.run(
                parts,
                shell=False,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                cwd=cwd,
            )
            stdout_text, stdout_truncated = truncate_text(result.stdout, _MAX_OUTPUT)
            stderr_text, stderr_truncated = truncate_text(result.stderr, _MAX_OUTPUT)
            combined = (result.stdout + result.stderr).strip()
            summary, combined_truncated = truncate_text(combined or "(no output)", _MAX_OUTPUT)
            warnings = []
            if stdout_truncated or stderr_truncated or combined_truncated:
                warnings.append("output_truncated")

            job_id = None
            if cmd_name == "sbatch":
                try:
                    job_id = _parse_submission_job_id(result.stdout)
                except ValueError:
                    job_id = None

            structured_payload = {
                "command": command,
                "argv": parts,
                "subcommand": cmd_name,
                "returncode": result.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "job_id": job_id,
            }
            refs = [script_ref] if script_ref is not None else []

            if result.returncode != 0:
                return execution_error_result(
                    self.name,
                    summary if summary.startswith("[ERROR]") else f"[ERROR] {summary}",
                    structured_payload=structured_payload,
                    artifact_refs=refs,
                    warnings=warnings,
                    metadata={"working_directory": str(cwd) if cwd else None},
                )

            if summary == "(no output)":
                return empty_result(
                    self.name,
                    summary,
                    structured_payload=structured_payload,
                    artifact_refs=refs,
                    warnings=warnings,
                    metadata={"working_directory": str(cwd) if cwd else None},
                )

            return success_result(
                self.name,
                summary,
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings,
                metadata={"working_directory": str(cwd) if cwd else None},
            )
        except subprocess.TimeoutExpired:
            return retriable_error_result(
                self.name,
                "Command timed out.",
                metadata={"command": command, "subcommand": cmd_name},
            )
        except Exception as exc:
            return execution_error_result(
                self.name,
                str(exc),
                metadata={"command": command, "subcommand": cmd_name},
            )

    async def _arun(self, **kwargs) -> tuple[str, dict]:
        return self._run(**kwargs)
