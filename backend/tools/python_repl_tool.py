"""
Thin wrapper around LangChain's PythonREPLTool that renames it to 'python_repl'
and trims overly long outputs.

The underlying PythonREPLTool instance is created lazily on first use and reused
for the lifetime of this tool instance, making variables, imports, and state defined
in one call available in subsequent calls (true persistent REPL).
"""
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

_MAX_OUTPUT = 5_000


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
