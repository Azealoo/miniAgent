"""squeue/sacct/scontrol query flow and job artifact refresh."""

from __future__ import annotations

import subprocess
from pathlib import Path

from artifacts import (
    SlurmJobArtifact,
    SlurmStatusObservation,
    load_artifact_document,
    resolve_artifact_path,
)

from .slurm_schema import (
    _MAX_OUTPUT,
    _TIMEOUT,
    _build_job_related_refs,
    _resolve_under_base,
    _safe_relative_if_under_base,
    _truncate_for_storage,
    _utcnow,
    normalize_slurm_status,
    SlurmJobOperationResult,
    SlurmQueryResult,
)


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


__all__ = [
    "_parse_sacct_query",
    "_parse_scontrol_query",
    "_parse_squeue_query",
    "_read_runtime_log",
    "_select_sacct_row",
    "load_slurm_job_artifact",
    "query_slurm_job_status",
    "refresh_slurm_job_artifact",
]
