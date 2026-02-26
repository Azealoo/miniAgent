import re
import subprocess
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# Each entry: (compiled regex, human-readable reason)
_BLOCKED_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Recursive / forced deletion  (-r, -R, -rf, --recursive, --force)
    (re.compile(r"\brm\b.*-[a-zA-Z]*[rR]", re.I), "rm with -r/-R flag"),
    (re.compile(r"\brm\b.*--recursive\b", re.I), "rm with --recursive flag"),
    (re.compile(r"\brm\b\s+(-\S+\s+)?/"), "rm on absolute path"),
    (re.compile(r"\bshred\b", re.I), "shred"),
    # Disk / filesystem
    (re.compile(r"\bmkfs\b", re.I), "mkfs"),
    (re.compile(r"\bfdisk\b|\bparted\b", re.I), "fdisk/parted"),
    (re.compile(r"\bdd\b.+\bif="), "dd with if="),
    (re.compile(r">\s*/dev/sd"), "write to block device"),
    # System shutdown
    (re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b", re.I), "system shutdown"),
    # Privilege escalation
    (re.compile(r"\bsudo\b", re.I), "sudo"),
    (re.compile(r"\bsu\b\s+-(\s|$)", re.I), "su -"),
    # Fork bomb
    (re.compile(r":\(\s*\)\s*\{"), "fork bomb"),
    # Mass permission changes
    (re.compile(r"\bchmod\b.+777.+/", re.I), "chmod 777 on /"),
    (re.compile(r"\bchown\b.+-R", re.I), "chown -R"),
    # Sensitive file reads
    (re.compile(r"(cat|less|more|head|tail|vi|nano|vim|tee|cp|mv)\s+.*\.env(\s|$|[;|&'\"])", re.I), "reading .env file"),
    (re.compile(r"/etc/(passwd|shadow|sudoers|ssh/)"), "sensitive /etc files"),
    # Remote code execution patterns
    (re.compile(r"\bcurl\b.+\|\s*(bash|sh|zsh|python3?)\b", re.I), "curl pipe to shell"),
    (re.compile(r"\bwget\b.+\|\s*(bash|sh|zsh|python3?)\b", re.I), "wget pipe to shell"),
    # Shell config overwrite
    (re.compile(r">\s*~/?\.(bash|zsh|profile|bashrc|zshrc)\b", re.I), "overwriting shell config"),
    # Unsafe eval
    (re.compile(r"\beval\b\s+[\"'`$\(]", re.I), "eval with dynamic content"),
    # Moving/deleting project data directories
    (re.compile(r"\b(rm|mv)\b.+/gpfs/projects/hrbomics/(data|predictions|gears-env)\b", re.I), "destructive op on lab data"),
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
        # Safety check — regex-based pattern matching
        for pattern, reason in _BLOCKED_PATTERNS:
            if pattern.search(command):
                return f"[BLOCKED] Command refused — {reason}."

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
