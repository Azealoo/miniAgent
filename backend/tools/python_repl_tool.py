"""
Thin wrapper around LangChain's PythonREPLTool that renames it to 'python_repl'
and trims overly long outputs.
"""
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

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

    def _run(self, code: str) -> str:
        try:
            from langchain_experimental.tools import PythonREPLTool

            repl = PythonREPLTool()
            output = repl.run(code)
            if len(str(output)) > _MAX_OUTPUT:
                output = str(output)[:_MAX_OUTPUT] + "\n...[output truncated]"
            return str(output)
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, code: str) -> str:  # type: ignore[override]
        return self._run(code)
