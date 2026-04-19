"""Legacy command-mode execution for the Slurm tool.

Supports the raw ``sbatch``/``squeue``/``sacct``/``scontrol``/``sinfo`` string
commands kept around for backwards compatibility. Prefer the structured
``submit``/``status`` actions in ``slurm_tool`` when possible.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import config

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
from .slurm_schema import (
    _ALLOWED,
    _MAX_OUTPUT,
    _TIMEOUT,
    _parse_submission_job_id,
    _resolve_under_base,
)


def run_legacy_slurm_command(
    *,
    tool_name: str,
    base_dir: str,
    command: str,
) -> tuple[str, dict]:
    if base_dir:
        policy = config.get_production_hardening_policy()
        if not policy.tools.slurm_legacy_commands_enabled:
            return blocked_result(
                tool_name,
                "Legacy Slurm commands are disabled by production hardening policy.",
                metadata={"command": command},
            )
    try:
        parts = shlex.split(command.strip())
    except ValueError as exc:
        return invalid_input_result(
            tool_name,
            f"Invalid command syntax: {exc}",
            metadata={"command": command},
        )

    if not parts:
        return invalid_input_result(
            tool_name,
            "Empty command.",
            metadata={"command": command},
        )
    cmd_name = parts[0].lower()
    if cmd_name not in _ALLOWED:
        return blocked_result(
            tool_name,
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
                tool_name,
                "sbatch requires a script path.",
                metadata={"command": command, "subcommand": cmd_name},
            )
        try:
            _script_resolved, script_relpath = _resolve_under_base(
                Path(base_dir).resolve(),
                script_arg,
                field_name="script_path",
                must_exist=True,
            )
        except ValueError as exc:
            message = str(exc)
            if "must stay under" in message:
                return blocked_result(
                    tool_name,
                    "sbatch path must be under project directory.",
                    metadata={"command": command, "subcommand": cmd_name, "script_path": script_arg},
                )
            return invalid_input_result(
                tool_name,
                message,
                metadata={"command": command, "subcommand": cmd_name, "script_path": script_arg},
            )
        script_ref = artifact_ref(path=script_relpath, label="sbatch_script")

    try:
        cwd = Path(base_dir) if base_dir else None
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
        metadata = {"working_directory": str(cwd) if cwd else None}

        if result.returncode != 0:
            return execution_error_result(
                tool_name,
                summary if summary.startswith("[ERROR]") else f"[ERROR] {summary}",
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings,
                metadata=metadata,
            )
        if summary == "(no output)":
            return empty_result(
                tool_name,
                summary,
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings,
                metadata=metadata,
            )
        return success_result(
            tool_name,
            summary,
            structured_payload=structured_payload,
            artifact_refs=refs,
            warnings=warnings,
            metadata=metadata,
        )
    except subprocess.TimeoutExpired:
        return retriable_error_result(
            tool_name,
            "Command timed out.",
            metadata={"command": command, "subcommand": cmd_name},
        )
    except Exception as exc:
        return execution_error_result(
            tool_name,
            str(exc),
            metadata={"command": command, "subcommand": cmd_name},
        )


__all__ = ["run_legacy_slurm_command"]
