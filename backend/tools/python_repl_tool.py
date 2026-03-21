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
import ast
import asyncio
import builtins
import codecs
import io
import importlib
import os
import pathlib
import pty
import re
import subprocess
import sys
import types
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Type

import config
from hardening import is_secret_like_path
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

_MAX_OUTPUT = 5_000
_PATH_READ_METHODS = {"read_text", "read_bytes", "open"}
_PATH_CONSTRUCTOR_NAMES = {
    "Path",
    "PurePath",
    "PosixPath",
    "PurePosixPath",
    "WindowsPath",
    "PureWindowsPath",
}
_SENSITIVE_SYSTEM_PATHS = {
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
}
_SENSITIVE_SYSTEM_PREFIXES = ("/etc/ssh/",)
_SECRET_FILE_BLOCK_REASON = "reading a credential or secret file"
_SECRET_FILE_BLOCK_MESSAGE = "Access to credential / secret files is not allowed."
_NATIVE_FFI_BLOCK_REASON = "native FFI module access"
_NATIVE_FFI_BLOCK_MESSAGE = "Native FFI modules are not allowed in this REPL."
_PROCESS_EXEC_BLOCK_REASON = "process execution"
_PROCESS_EXEC_BLOCK_MESSAGE = "Child process execution is not allowed in this REPL."
_BLOCKED_NATIVE_MODULES = frozenset({"ctypes", "_ctypes", "cffi"})
_BLOCKED_PTY_ATTRIBUTES = frozenset({"fork", "spawn"})
_BLOCKED_OS_PROCESS_FUNCTIONS = frozenset({
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "fork",
    "forkpty",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "popen",
    "posix_spawn",
    "posix_spawnp",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "system",
})
_BLOCKED_SUBPROCESS_ATTRIBUTES = frozenset({
    "Popen",
    "call",
    "check_call",
    "check_output",
    "getoutput",
    "getstatusoutput",
    "run",
})
_BLOCKED_ASYNCIO_PROCESS_ATTRIBUTES = frozenset({
    "create_subprocess_exec",
    "create_subprocess_shell",
})

# (compiled regex, human-readable reason) — checked before every execution
_BLOCKED_CODE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Process execution from the persistent REPL is blocked outright.
    (re.compile(r"\bpty\.(fork|spawn)\b"), _PROCESS_EXEC_BLOCK_REASON),
    (re.compile(r"\bsubprocess\.(run|call|check_call|check_output|getoutput|getstatusoutput|Popen)\b"), _PROCESS_EXEC_BLOCK_REASON),
    (re.compile(r"\bos\.(system|popen|fork|forkpty|posix_spawn|posix_spawnp|execl|execle|execlp|execlpe|execv|execve|execvp|execvpe|spawnl|spawnle|spawnlp|spawnlpe|spawnv|spawnve|spawnvp|spawnvpe)\b"), _PROCESS_EXEC_BLOCK_REASON),
    (re.compile(r"\basyncio\.(create_subprocess_exec|create_subprocess_shell)\b"), _PROCESS_EXEC_BLOCK_REASON),
    (re.compile(r"\basyncio\.subprocess\.(create_subprocess_exec|create_subprocess_shell)\b"), _PROCESS_EXEC_BLOCK_REASON),
    (re.compile(r"\bos\.remove\s*\(|\bos\.unlink\s*\(|\bos\.rmdir\s*\("), "os file-deletion functions"),
    # Dynamic code execution — block bare eval() but allow method calls like pd.eval()
    # The negative lookbehind excludes '.' so that 'pd.eval(' passes through.
    (re.compile(r"(?<!['\.\w])\beval\s*\("), "bare eval()"),
    (re.compile(r"\b__import__\s*\("), "__import__()"),
    (re.compile(r"open\s*\(\s*['\"][^'\"]*/(passwd|shadow|sudoers)['\"]"), "open() on sensitive system file"),
    # Writing outside project root (absolute paths that aren't under /gpfs/projects/hrbomics)
    (re.compile(r"open\s*\(\s*['\"]/((?!gpfs/projects/hrbomics)[^'\"]*)['\"].*['\"]w"), "open() write to absolute path outside project"),
]


def _is_path_constructor(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _PATH_CONSTRUCTOR_NAMES
    if isinstance(node, ast.Attribute) and node.attr in _PATH_CONSTRUCTOR_NAMES:
        if isinstance(node.value, ast.Name):
            return node.value.id == "pathlib"
    return False


def _coerce_runtime_path(value: Any) -> str | None:
    if isinstance(value, int):
        return None
    try:
        coerced = os.fspath(value)
    except TypeError:
        return None
    return str(coerced).strip()


def _is_sensitive_system_path(value: Any) -> bool:
    candidate = _coerce_runtime_path(value)
    if candidate is None:
        return False
    normalized = candidate.strip()
    if normalized in _SENSITIVE_SYSTEM_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in _SENSITIVE_SYSTEM_PREFIXES)


def _is_runtime_blocked_path(value: Any) -> bool:
    candidate = _coerce_runtime_path(value)
    if candidate is None:
        return False
    return is_secret_like_path(candidate) or _is_sensitive_system_path(candidate)


def _is_literal_blocked_path(value: str) -> bool:
    return is_secret_like_path(value) or _is_sensitive_system_path(value)


def _literal_path_from_node(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and _is_path_constructor(node.func) and node.args:
        return _literal_path_from_node(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _literal_path_from_node(node.left)
        right = _literal_path_from_node(node.right)
        if left is not None and right is not None:
            return str(Path(left) / right)
    return None


def _call_targets_secret_path(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open" and node.args:
        literal = _literal_path_from_node(node.args[0])
        return literal is not None and _is_literal_blocked_path(literal)
    if isinstance(func, ast.Attribute) and func.attr in _PATH_READ_METHODS:
        literal = _literal_path_from_node(func.value)
        return literal is not None and _is_literal_blocked_path(literal)
    if isinstance(func, ast.Attribute) and func.attr == "open" and node.args:
        literal = _literal_path_from_node(node.args[0])
        return literal is not None and _is_literal_blocked_path(literal)
    return False


def _code_targets_secret_path(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_targets_secret_path(node):
            return True
    return False


def _code_imports_blocked_native_module(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if top_level in _BLOCKED_NATIVE_MODULES:
                    return top_level
        if isinstance(node, ast.ImportFrom) and node.module:
            top_level = node.module.split(".", 1)[0]
            if top_level in _BLOCKED_NATIVE_MODULES:
                return top_level
    return None


def _scan_code(code: str) -> str | None:
    """Return a [BLOCKED] message if *code* matches any dangerous pattern, else None."""
    blocked_native_module = _code_imports_blocked_native_module(code)
    if blocked_native_module is not None:
        return (
            "[BLOCKED] Code refused — contains forbidden operation: "
            f"{_NATIVE_FFI_BLOCK_REASON} ({blocked_native_module})."
        )
    if _code_targets_secret_path(code):
        return f"[BLOCKED] Code refused — contains forbidden operation: {_SECRET_FILE_BLOCK_REASON}."
    for pattern, reason in _BLOCKED_CODE_PATTERNS:
        if pattern.search(code):
            return f"[BLOCKED] Code refused — contains forbidden operation: {reason}."
    return None


def _is_secret_runtime_block(output: Any) -> bool:
    rendered = str(output)
    return "PermissionError" in rendered and _SECRET_FILE_BLOCK_MESSAGE in rendered


def _is_native_runtime_block(output: Any) -> bool:
    rendered = str(output)
    return "PermissionError" in rendered and _NATIVE_FFI_BLOCK_MESSAGE in rendered


def _is_process_runtime_block(output: Any) -> bool:
    rendered = str(output)
    return "PermissionError" in rendered and _PROCESS_EXEC_BLOCK_MESSAGE in rendered


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
    base_dir: str = ""

    _repl: Any = PrivateAttr(default=None)
    _runtime_guards_installed: bool = PrivateAttr(default=False)
    _safe_import: Any = PrivateAttr(default=None)
    _safe_import_module: Any = PrivateAttr(default=None)
    _safe_modules: dict[str, types.ModuleType] = PrivateAttr(default_factory=dict)
    _safe_open: Any = PrivateAttr(default=None)

    def _run_with_global_runtime_patches(self, code: str) -> Any:
        if self._safe_import is None or self._safe_import_module is None or self._safe_open is None:
            return self._repl.run(code)

        safe_modules = self._safe_modules
        missing = object()
        attr_patches: list[tuple[object, str, Any]] = []
        sys_module_patches: list[tuple[str, Any]] = []

        def patch_attr(target: object, attr_name: str, value: Any) -> None:
            original = getattr(target, attr_name, missing)
            attr_patches.append((target, attr_name, original))
            setattr(target, attr_name, value)

        def patch_module_entry(module_name: str, module_value: types.ModuleType) -> None:
            original = sys.modules.get(module_name, missing)
            sys_module_patches.append((module_name, original))
            sys.modules[module_name] = module_value

        try:
            patch_attr(builtins, "__import__", self._safe_import)
            patch_attr(builtins, "open", self._safe_open)
            patch_attr(importlib, "import_module", self._safe_import_module)

            safe_os = safe_modules.get("os")
            if safe_os is not None:
                for attr_name in {"open", *_BLOCKED_OS_PROCESS_FUNCTIONS}:
                    if hasattr(os, attr_name) and hasattr(safe_os, attr_name):
                        patch_attr(os, attr_name, getattr(safe_os, attr_name))

            native_os_module = sys.modules.get(os.name)
            safe_native_os = safe_modules.get(os.name)
            if native_os_module is not None and safe_native_os is not None:
                for attr_name in {"open", *_BLOCKED_OS_PROCESS_FUNCTIONS}:
                    if hasattr(native_os_module, attr_name) and hasattr(safe_native_os, attr_name):
                        patch_attr(native_os_module, attr_name, getattr(safe_native_os, attr_name))

            safe_subprocess = safe_modules.get("subprocess")
            if safe_subprocess is not None:
                for attr_name in _BLOCKED_SUBPROCESS_ATTRIBUTES:
                    if hasattr(subprocess, attr_name) and hasattr(safe_subprocess, attr_name):
                        patch_attr(subprocess, attr_name, getattr(safe_subprocess, attr_name))

            safe_asyncio = safe_modules.get("asyncio")
            if safe_asyncio is not None:
                for attr_name in _BLOCKED_ASYNCIO_PROCESS_ATTRIBUTES:
                    if hasattr(asyncio, attr_name) and hasattr(safe_asyncio, attr_name):
                        patch_attr(asyncio, attr_name, getattr(safe_asyncio, attr_name))

            asyncio_subprocess_module = sys.modules.get("asyncio.subprocess")
            safe_asyncio_subprocess = safe_modules.get("asyncio.subprocess")
            if asyncio_subprocess_module is not None and safe_asyncio_subprocess is not None:
                for attr_name in _BLOCKED_ASYNCIO_PROCESS_ATTRIBUTES:
                    if hasattr(asyncio_subprocess_module, attr_name) and hasattr(safe_asyncio_subprocess, attr_name):
                        patch_attr(asyncio_subprocess_module, attr_name, getattr(safe_asyncio_subprocess, attr_name))

            pty_module = sys.modules.get("pty")
            safe_pty = safe_modules.get("pty")
            if pty_module is not None and safe_pty is not None:
                for attr_name in _BLOCKED_PTY_ATTRIBUTES:
                    if hasattr(pty_module, attr_name) and hasattr(safe_pty, attr_name):
                        patch_attr(pty_module, attr_name, getattr(safe_pty, attr_name))

            safe_io = safe_modules.get("io")
            if safe_io is not None:
                for attr_name in ("open", "FileIO", "open_code"):
                    if hasattr(io, attr_name) and hasattr(safe_io, attr_name):
                        patch_attr(io, attr_name, getattr(safe_io, attr_name))

            raw_io_module = sys.modules.get("_io")
            safe_raw_io = safe_modules.get("_io")
            if raw_io_module is not None and safe_raw_io is not None:
                for attr_name in ("open", "FileIO", "open_code"):
                    if hasattr(raw_io_module, attr_name) and hasattr(safe_raw_io, attr_name):
                        patch_attr(raw_io_module, attr_name, getattr(safe_raw_io, attr_name))

            safe_codecs = safe_modules.get("codecs")
            if safe_codecs is not None and hasattr(codecs, "open") and hasattr(safe_codecs, "open"):
                patch_attr(codecs, "open", safe_codecs.open)

            for module_name, module_value in safe_modules.items():
                if module_name == "sys":
                    continue
                patch_module_entry(module_name, module_value)

            return self._repl.run(code)
        finally:
            for module_name, original in reversed(sys_module_patches):
                if original is missing:
                    sys.modules.pop(module_name, None)
                else:
                    sys.modules[module_name] = original
            for target, attr_name, original in reversed(attr_patches):
                if original is missing:
                    delattr(target, attr_name)
                else:
                    setattr(target, attr_name, original)

    def _ensure_runtime_guards(self) -> None:
        if self._repl is None or self._runtime_guards_installed:
            return

        python_repl = self._repl.python_repl
        original_open = builtins.open
        original_import = builtins.__import__
        original_os_open = os.open
        original_io_open = io.open
        original_codecs_open = codecs.open
        original_import_module = importlib.import_module
        original_file_io = io.FileIO
        original_asyncio_subprocess_module = None
        original_native_os_module = None
        original_pty_module = None
        original_raw_io_module = None
        original_open_code = getattr(io, "open_code", None)
        concrete_path_class = type(Path())
        try:
            original_asyncio_subprocess_module = original_import_module("asyncio.subprocess")
        except ModuleNotFoundError:
            pass
        try:
            original_pty_module = original_import_module("pty")
        except ModuleNotFoundError:
            pass
        try:
            original_native_os_module = original_import_module(os.name)
        except ModuleNotFoundError:
            pass
        try:
            original_raw_io_module = original_import_module("_io")
        except ModuleNotFoundError:
            pass

        class BlockedModule(types.ModuleType):
            def __getattr__(self, attr: str) -> Any:
                raise PermissionError(_NATIVE_FFI_BLOCK_MESSAGE)

        class SafePath(concrete_path_class):
            def open(self, *args, **kwargs):
                if _is_runtime_blocked_path(self):
                    raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
                return super().open(*args, **kwargs)

        def safe_open(*args, **kwargs):
            path_value = args[0] if args else kwargs.get("file")
            if _is_runtime_blocked_path(path_value):
                raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
            return original_open(*args, **kwargs)

        def safe_os_open(path, flags, *args, **kwargs):
            if _is_runtime_blocked_path(path):
                raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
            return original_os_open(path, flags, *args, **kwargs)

        def safe_io_open(file, *args, **kwargs):
            if _is_runtime_blocked_path(file):
                raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
            return original_io_open(file, *args, **kwargs)

        def safe_codecs_open(filename, *args, **kwargs):
            if _is_runtime_blocked_path(filename):
                raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
            return original_codecs_open(filename, *args, **kwargs)

        def safe_open_code(path, *args, **kwargs):
            if _is_runtime_blocked_path(path):
                raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
            if original_open_code is None:
                return original_open(path, *args, **kwargs)
            return original_open_code(path, *args, **kwargs)

        def blocked_process_call(*args, **kwargs):
            raise PermissionError(_PROCESS_EXEC_BLOCK_MESSAGE)

        class SafeFileIO(original_file_io):
            def __init__(self, file, *args, **kwargs):
                if _is_runtime_blocked_path(file):
                    raise PermissionError(_SECRET_FILE_BLOCK_MESSAGE)
                super().__init__(file, *args, **kwargs)

        class SafeModuleRegistry(MutableMapping[str, types.ModuleType]):
            def __init__(self, backing: dict[str, types.ModuleType], overrides: dict[str, types.ModuleType]):
                self._backing = backing
                self._overrides = overrides

            def __getitem__(self, key: str) -> types.ModuleType:
                if key in self._overrides:
                    return self._overrides[key]
                top_level = key.split(".", 1)[0]
                if top_level in _BLOCKED_NATIVE_MODULES and top_level in self._overrides:
                    return self._overrides[top_level]
                return self._backing[key]

            def __setitem__(self, key: str, value: types.ModuleType) -> None:
                top_level = key.split(".", 1)[0]
                if key in self._overrides or (top_level in _BLOCKED_NATIVE_MODULES and top_level in self._overrides):
                    raise PermissionError("Protected runtime modules are not writable in this REPL.")
                self._backing[key] = value

            def __delitem__(self, key: str) -> None:
                top_level = key.split(".", 1)[0]
                if key in self._overrides or (top_level in _BLOCKED_NATIVE_MODULES and top_level in self._overrides):
                    raise PermissionError("Protected runtime modules cannot be removed from this REPL.")
                del self._backing[key]

            def __iter__(self):
                seen = set(self._overrides)
                yield from self._overrides
                for key in self._backing:
                    if key not in seen:
                        yield key

            def __len__(self) -> int:
                return len(set(self._backing) | set(self._overrides))

        def _copy_module(module: types.ModuleType, **overrides: Any) -> types.ModuleType:
            safe_module = types.ModuleType(module.__name__)
            for attr_name in dir(module):
                setattr(safe_module, attr_name, getattr(module, attr_name))
            for attr_name, attr_value in overrides.items():
                setattr(safe_module, attr_name, attr_value)
            return safe_module

        safe_pathlib = _copy_module(pathlib, Path=SafePath)
        if hasattr(safe_pathlib, concrete_path_class.__name__):
            setattr(safe_pathlib, concrete_path_class.__name__, SafePath)

        safe_builtins_module = _copy_module(
            builtins,
            open=safe_open,
        )
        safe_os_overrides: dict[str, Any] = {"open": safe_os_open}
        for attr_name in _BLOCKED_OS_PROCESS_FUNCTIONS:
            if hasattr(os, attr_name):
                safe_os_overrides[attr_name] = blocked_process_call
        safe_os = _copy_module(os, **safe_os_overrides)
        safe_io = _copy_module(io, open=safe_io_open, open_code=safe_open_code, FileIO=SafeFileIO)
        safe_codecs = _copy_module(codecs, open=safe_codecs_open)
        safe_subprocess_overrides = {
            attr_name: blocked_process_call
            for attr_name in _BLOCKED_SUBPROCESS_ATTRIBUTES
            if hasattr(subprocess, attr_name)
        }
        safe_subprocess = _copy_module(subprocess, **safe_subprocess_overrides)
        safe_asyncio_subprocess = None
        if original_asyncio_subprocess_module is not None:
            safe_asyncio_subprocess_overrides = {
                attr_name: blocked_process_call
                for attr_name in _BLOCKED_ASYNCIO_PROCESS_ATTRIBUTES
                if hasattr(original_asyncio_subprocess_module, attr_name)
            }
            safe_asyncio_subprocess = _copy_module(original_asyncio_subprocess_module, **safe_asyncio_subprocess_overrides)
        safe_asyncio_overrides = {
            attr_name: blocked_process_call
            for attr_name in _BLOCKED_ASYNCIO_PROCESS_ATTRIBUTES
            if hasattr(asyncio, attr_name)
        }
        if safe_asyncio_subprocess is not None:
            safe_asyncio_overrides["subprocess"] = safe_asyncio_subprocess
        safe_asyncio = _copy_module(asyncio, **safe_asyncio_overrides)
        safe_pty = None
        if original_pty_module is not None:
            safe_pty_overrides = {
                attr_name: blocked_process_call
                for attr_name in _BLOCKED_PTY_ATTRIBUTES
                if hasattr(original_pty_module, attr_name)
            }
            safe_pty = _copy_module(original_pty_module, **safe_pty_overrides)
        safe_modules: dict[str, types.ModuleType] = {
            "asyncio": safe_asyncio,
            "builtins": safe_builtins_module,
            "codecs": safe_codecs,
            "io": safe_io,
            "os": safe_os,
            "pathlib": safe_pathlib,
            "subprocess": safe_subprocess,
        }
        if safe_asyncio_subprocess is not None:
            safe_modules["asyncio.subprocess"] = safe_asyncio_subprocess
        if safe_pty is not None:
            safe_modules["pty"] = safe_pty
        if original_native_os_module is not None and hasattr(original_native_os_module, "open"):
            native_os_overrides: dict[str, Any] = {"open": safe_os_open}
            for attr_name in _BLOCKED_OS_PROCESS_FUNCTIONS:
                if hasattr(original_native_os_module, attr_name):
                    native_os_overrides[attr_name] = blocked_process_call
            safe_modules[os.name] = _copy_module(original_native_os_module, **native_os_overrides)
        if original_raw_io_module is not None:
            raw_io_overrides: dict[str, Any] = {"FileIO": SafeFileIO}
            if hasattr(original_raw_io_module, "open"):
                raw_io_overrides["open"] = safe_io_open
            if hasattr(original_raw_io_module, "open_code"):
                raw_io_overrides["open_code"] = safe_open_code
            safe_modules["_io"] = _copy_module(original_raw_io_module, **raw_io_overrides)
        for blocked_module_name in _BLOCKED_NATIVE_MODULES:
            if blocked_module_name not in safe_modules:
                safe_modules[blocked_module_name] = BlockedModule(blocked_module_name)
        safe_sys = _copy_module(
            sys,
            modules=SafeModuleRegistry(sys.modules, safe_modules),
        )
        safe_modules["sys"] = safe_sys

        def safe_import_module(name: str, package: str | None = None):
            top_level = name.split(".", 1)[0]
            if top_level in _BLOCKED_NATIVE_MODULES:
                return safe_modules[top_level]
            if name in safe_modules:
                return safe_modules[name]
            return original_import_module(name, package)

        safe_importlib = _copy_module(importlib, import_module=safe_import_module)
        safe_modules["importlib"] = safe_importlib

        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            top_level = name.split(".", 1)[0]
            if top_level in _BLOCKED_NATIVE_MODULES:
                return safe_modules[top_level]
            module = original_import(name, globals, locals, fromlist, level)
            return safe_modules.get(name, module)

        safe_builtins_module.__import__ = safe_import

        safe_builtins = dict(builtins.__dict__)
        safe_builtins["open"] = safe_open
        safe_builtins["__import__"] = safe_import
        self._safe_import = safe_import
        self._safe_import_module = safe_import_module
        self._safe_modules = safe_modules
        self._safe_open = safe_open
        python_repl.globals["__builtins__"] = safe_builtins
        python_repl.globals["asyncio"] = safe_asyncio
        python_repl.globals["builtins"] = safe_builtins_module
        python_repl.globals["codecs"] = safe_codecs
        python_repl.globals["importlib"] = safe_importlib
        python_repl.globals["io"] = safe_io
        python_repl.globals["open"] = safe_open
        python_repl.globals["os"] = safe_os
        python_repl.globals["Path"] = SafePath
        python_repl.globals["pathlib"] = safe_pathlib
        python_repl.globals["sys"] = safe_sys
        self._runtime_guards_installed = True

    def _run(self, code: str) -> str:
        if self.base_dir:
            policy = config.get_production_hardening_policy()
            if not policy.tools.python_repl_enabled:
                return "[BLOCKED] Python REPL tool is disabled by production hardening policy."
        blocked = _scan_code(code)
        if blocked:
            return blocked
        try:
            if self._repl is None:
                from langchain_experimental.tools import PythonREPLTool

                self._repl = PythonREPLTool()
            self._ensure_runtime_guards()
            output = self._run_with_global_runtime_patches(code)
            if len(str(output)) > _MAX_OUTPUT:
                output = str(output)[:_MAX_OUTPUT] + "\n...[output truncated]"
            if _is_secret_runtime_block(output):
                return f"[BLOCKED] Code refused — contains forbidden operation: {_SECRET_FILE_BLOCK_REASON}."
            if _is_native_runtime_block(output):
                return f"[BLOCKED] Code refused — contains forbidden operation: {_NATIVE_FFI_BLOCK_REASON}."
            if _is_process_runtime_block(output):
                return f"[BLOCKED] Code refused — contains forbidden operation: {_PROCESS_EXEC_BLOCK_REASON}."
            return str(output)
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, code: str) -> str:  # type: ignore[override]
        return self._run(code)
