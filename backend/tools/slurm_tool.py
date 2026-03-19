"""
Safe Slurm helper: submit job (sbatch), query queue (squeue), query accounting (sacct).
Only allows predefined commands; no arbitrary shell.

Security: uses shlex.split + shell=False so semicolons, pipes, and other shell
metacharacters in the command string are treated as literals and never interpreted
by a shell.
"""
import re
import shlex
import subprocess
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

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


class SlurmToolInput(BaseModel):
    command: str = Field(
        description="One of: sbatch <script_path>, squeue [options], sacct [options], scontrol show job <id>, sinfo."
    )


class SlurmTool(BaseTool):
    name: str = "slurm_tool"
    description: str = (
        "Run Slurm commands: sbatch <script>, squeue, sacct, scontrol show job <id>, sinfo. "
        "Use for submitting jobs and checking queue/accounting. Input: full command string."
    )
    args_schema: Type[BaseModel] = SlurmToolInput
    response_format: str = "content_and_artifact"
    base_dir: str = ""

    def _run(self, command: str) -> tuple[str, dict]:
        # Parse with shlex so shell metacharacters (;, |, &&, $()) are never interpreted
        try:
            parts = shlex.split(command.strip())
        except ValueError as e:
            return invalid_input_result(
                self.name,
                f"Invalid command syntax: {e}",
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
            # Find the script path: first non-flag, non-assignment token after 'sbatch'
            script_arg = next(
                (p for p in parts[1:] if not p.startswith("-") and "=" not in p),
                None,
            )
            if script_arg is None:
                return invalid_input_result(
                    self.name,
                    "sbatch requires a script path.",
                    metadata={"command": command, "subcommand": cmd_name},
                )
            script = Path(script_arg)
            if not script.is_absolute():
                script = (Path(self.base_dir) / script).resolve()
            if not script.exists():
                return invalid_input_result(
                    self.name,
                    f"Script not found: {script_arg}",
                    metadata={
                        "command": command,
                        "subcommand": cmd_name,
                        "script_path": script_arg,
                        "resolved_script_path": str(script),
                    },
                )
            base_resolved = Path(self.base_dir).resolve()
            try:
                script.relative_to(base_resolved)
            except ValueError:
                return blocked_result(
                    self.name,
                    "sbatch path must be under project directory.",
                    metadata={
                        "command": command,
                        "subcommand": cmd_name,
                        "script_path": script_arg,
                        "resolved_script_path": str(script),
                    },
                )
            if ".." in script_arg:
                return blocked_result(
                    self.name,
                    "sbatch path must be under project directory.",
                    metadata={
                        "command": command,
                        "subcommand": cmd_name,
                        "script_path": script_arg,
                        "resolved_script_path": str(script),
                    },
                )
            script_ref = artifact_ref(path=str(script), label="sbatch_script")

        try:
            cwd = Path(self.base_dir) if self.base_dir else None
            result = subprocess.run(
                parts,       # list form — shell=False eliminates injection risk
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
                match = re.search(r"Submitted batch job (\d+)", result.stdout)
                if match:
                    job_id = match.group(1)

            structured_payload = {
                "command": command,
                "argv": parts,
                "subcommand": cmd_name,
                "returncode": result.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "job_id": job_id,
            }
            if script_ref:
                structured_payload["script_path"] = script_ref.path

            refs = [script_ref] if script_ref else []

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

    async def _arun(self, command: str) -> tuple[str, dict]:
        return self._run(command)
