import subprocess
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_BLACKLIST = [
    "rm -rf /",
    "mkfs",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "dd if=",
    ":(){ :|:& };:",  # fork bomb
    "> /dev/sda",
    "chmod -R 777 /",
    "chown -R",
]

_TIMEOUT = 30
_MAX_OUTPUT = 5_000


class TerminalInput(BaseModel):
    command: str = Field(description="The shell command to execute.")


class TerminalTool(BaseTool):
    name: str = "terminal"
    description: str = (
        "Execute a shell command in the project directory. "
        "Use for file operations, running scripts, installing packages, "
        "checking system info, etc. "
        "Input: a shell command string."
    )
    args_schema: Type[BaseModel] = TerminalInput
    base_dir: str = ""

    def _run(self, command: str) -> str:
        # Safety check
        for blocked in _BLACKLIST:
            if blocked in command:
                return f"[BLOCKED] Command refused — contains forbidden pattern: '{blocked}'"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                cwd=self.base_dir or None,
            )
            output = (result.stdout + result.stderr).strip()
            if not output:
                return "(no output)"
            if len(output) > _MAX_OUTPUT:
                output = output[:_MAX_OUTPUT] + "\n...[output truncated]"
            return output
        except subprocess.TimeoutExpired:
            return f"[ERROR] Command timed out after {_TIMEOUT} seconds."
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, command: str) -> str:  # type: ignore[override]
        return self._run(command)
