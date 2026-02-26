"""
Thin wrapper around LangChain's PythonREPLTool that renames it to 'python_repl'
and trims overly long outputs.

The underlying PythonREPLTool instance is created lazily on first use and reused
for the lifetime of this tool instance, making variables, imports, and state defined
in one call available in subsequent calls (true persistent REPL).

Safety: a pre-execution scanner blocks the most dangerous operations (shell
execution, arbitrary file deletion, credential file reads). This is defence-in-depth
and not a complete sandbox; use it alongside the other tool safeguards.
"""
import re
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

_MAX_OUTPUT = 5_000

# (compiled regex, human-readable reason) — checked before every execution
_BLOCKED_CODE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Shell execution via os module
    (re.compile(r"\bos\.system\s*\("), "os.system()"),
    (re.compile(r"\bos\.popen\s*\("), "os.popen()"),
    (re.compile(r"\bos\.remove\s*\(|\bos\.unlink\s*\(|\bos\.rmdir\s*\("), "os file-deletion functions"),
    # subprocess — allow import but block execution with shell=True on any line
    # re.DOTALL so '.*' matches newlines: catches multi-line call blocks.
    (re.compile(r"\bsubprocess\.(run|call|check_output|Popen)\b[\s\S]*?shell\s*=\s*True", re.DOTALL), "subprocess with shell=True"),
    # Dynamic code execution — block bare eval() but allow method calls like pd.eval()
    # The negative lookbehind excludes '.' so that 'pd.eval(' passes through.
    (re.compile(r"(?<!['\.\w])\beval\s*\("), "bare eval()"),
    (re.compile(r"\b__import__\s*\("), "__import__()"),
    # Reading credential / secret files
    (re.compile(r"open\s*\(\s*['\"][^'\"]*\.env['\"]"), "open() on .env file"),
    (re.compile(r"open\s*\(\s*['\"][^'\"]*/(passwd|shadow|sudoers)['\"]"), "open() on sensitive system file"),
    # Writing outside project root (absolute paths that aren't under /gpfs/projects/hrbomics)
    (re.compile(r"open\s*\(\s*['\"]/((?!gpfs/projects/hrbomics)[^'\"]*)['\"].*['\"]w"), "open() write to absolute path outside project"),
]


def _scan_code(code: str) -> str | None:
    """Return a [BLOCKED] message if *code* matches any dangerous pattern, else None."""
    for pattern, reason in _BLOCKED_CODE_PATTERNS:
        if pattern.search(code):
            return f"[BLOCKED] Code refused — contains forbidden operation: {reason}."
    return None


class PythonReplInput(BaseModel):
    code: str = Field(description="Python code to execute.")


class PythonReplTool(BaseTool):
    name: str = "python_repl"
    description: str = (
        "Execute Python code for calculations, data processing, or scripting. "
        "The interpreter is persistent across calls within a session. "
        "Input: valid Python source code."
    )
    args_schema: Type[BaseModel] = PythonReplInput

    _repl: Any = PrivateAttr(default=None)

    def _run(self, code: str) -> str:
        blocked = _scan_code(code)
        if blocked:
            return blocked
        try:
            if self._repl is None:
                from langchain_experimental.tools import PythonREPLTool

                self._repl = PythonREPLTool()
            output = self._repl.run(code)
            if len(str(output)) > _MAX_OUTPUT:
                output = str(output)[:_MAX_OUTPUT] + "\n...[output truncated]"
            return str(output)
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, code: str) -> str:  # type: ignore[override]
        return self._run(code)
