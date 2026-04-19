"""Structured, safe Slurm run manager with legacy command compatibility.

This module is the public entry point for the Slurm tool. The submission,
monitoring, and schema helpers live in ``slurm_submit``, ``slurm_monitor``,
and ``slurm_schema``; they are re-exported here so existing imports such as
``from tools.slurm_tool import SlurmTool`` continue to work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Literal, Type

import config
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from artifacts import SlurmResourceRequest, resolve_artifact_path

from .contracts import (
    artifact_ref,
    blocked_result,
    execution_error_result,
    invalid_input_result,
    retriable_error_result,
    success_result,
)
from .slurm_legacy import run_legacy_slurm_command
from .slurm_monitor import (
    load_slurm_job_artifact,
    query_slurm_job_status,
    refresh_slurm_job_artifact,
)
from .slurm_schema import _dump_json, _ensure_non_empty, SlurmToolInput
from .slurm_submit import (
    _choose_job_record_relpath,
    ensure_slurm_persistence_context,
    submit_slurm_job,
)


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
        if self.base_dir:
            policy = config.get_production_hardening_policy()
            if not policy.tools.slurm_enabled:
                return blocked_result(
                    self.name,
                    "Slurm tool is disabled by production hardening policy.",
                )
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
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

    def _run_legacy_command(self, command: str) -> tuple[str, dict]:
        return run_legacy_slurm_command(
            tool_name=self.name,
            base_dir=self.base_dir,
            command=command,
        )

    async def _arun(self, **kwargs) -> tuple[str, dict]:
        return self._run(**kwargs)


__all__ = [
    "SlurmTool",
    "SlurmToolInput",
    "ensure_slurm_persistence_context",
    "load_slurm_job_artifact",
    "query_slurm_job_status",
    "refresh_slurm_job_artifact",
    "submit_slurm_job",
]
