"""
Safe Slurm helper: submit job (sbatch), query queue (squeue), query accounting (sacct).
Only allows predefined commands; no arbitrary shell.
"""
import subprocess
from pathlib import Path
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

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
    base_dir: str = ""

    def _run(self, command: str) -> str:
        parts = command.strip().split()
        if not parts:
            return "[ERROR] Empty command."
        cmd_name = parts[0].lower()
        if cmd_name not in _ALLOWED:
            return f"[BLOCKED] Only these Slurm commands are allowed: {sorted(_ALLOWED)}."
        if cmd_name == "sbatch" and len(parts) >= 2:
            script = Path(parts[1])
            if not script.is_absolute():
                script = (Path(self.base_dir) / script).resolve()
            if not script.exists():
                return f"[ERROR] Script not found: {parts[1]}"
            if ".." in parts[1] or not str(script).startswith(str(Path(self.base_dir).resolve())):
                return "[BLOCKED] sbatch path must be under project directory."
        try:
            cwd = Path(self.base_dir) if self.base_dir else None
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                cwd=cwd,
            )
            out = (result.stdout + result.stderr).strip()
            if not out:
                out = "(no output)"
            if len(out) > _MAX_OUTPUT:
                out = out[:_MAX_OUTPUT] + "\n...[truncated]"
            if result.returncode != 0 and not out:
                out = f"[exit {result.returncode}]"
            return out
        except subprocess.TimeoutExpired:
            return "[ERROR] Command timed out."
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, command: str) -> str:
        return self._run(command)
