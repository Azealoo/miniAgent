"""sbatch submission path: argv building, log templates, and the submit entrypoint."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from audit.store import append_job_submitted_event

from artifacts import (
    ArtifactReference,
    SCHEMA_PACK_VERSION,
    SlurmJobArtifact,
    SlurmJobLogCapture,
    SlurmResourceRequest,
    SlurmStatusObservation,
    generate_run_id,
    prepare_run_directory,
    resolve_artifact_path,
    stable_artifact_name,
)

from .slurm_schema import (
    _TIMEOUT,
    _build_job_related_refs,
    _created_at_from_run_id,
    _ensure_non_empty,
    _parse_submission_job_id,
    _resolve_under_base,
    _slugify,
    _truncate_for_storage,
    _utcnow,
    SlurmJobOperationResult,
    SlurmPersistenceContext,
)


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


def _normalize_log_path(base_dir: Path, value: str) -> str:
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


def submit_slurm_job(
    *,
    base_dir: Path | str,
    session_id: str | None = None,
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
    step_id: str | None = None,
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
    append_job_submitted_event(
        base_path,
        session_id=session_id,
        run_id=run_id,
        job_id=job_id,
        script_path=script_relpath,
        working_directory=working_directory_relpath,
        resource_request=resource_model.model_dump(mode="json"),
        stdout_path=actual_stdout_path,
        stderr_path=actual_stderr_path,
        workflow_id=source_workflow,
        step_id=step_id,
        tool_name=source_tool,
    )
    return SlurmJobOperationResult(
        artifact=artifact,
        summary=f"Submitted Slurm job {job_id} for {script_relpath}.",
        raw_stdout=completed.stdout,
        raw_stderr=completed.stderr,
        commands=[argv],
    )


__all__ = [
    "_build_sbatch_argv",
    "_choose_job_record_relpath",
    "_default_log_templates",
    "_ensure_log_parents",
    "_find_run_dir",
    "_materialize_log_path",
    "_normalize_log_path",
    "ensure_slurm_persistence_context",
    "submit_slurm_job",
]
