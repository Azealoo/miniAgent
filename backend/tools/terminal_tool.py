import glob
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Type

import config
from hardening import is_secret_like_path
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
    (
        re.compile(
            r"(cat|less|more|head|tail|vi|nano|vim|tee|cp|mv)\s+.*(\.pem|\.key|\.p12|\.pfx|\.crt|\.cer|id_(rsa|dsa|ecdsa|ed25519))(\s|$|[;|&'\"])",
            re.I,
        ),
        "reading credential or private-key file",
    ),
    (re.compile(r"/etc/(passwd|shadow|sudoers|ssh/)"), "sensitive /etc files"),
    # Remote code execution patterns
    (re.compile(r"\bcurl\b.+\|\s*(bash|sh|zsh|python3?)\b", re.I), "curl pipe to shell"),
    (re.compile(r"\bwget\b.+\|\s*(bash|sh|zsh|python3?)\b", re.I), "wget pipe to shell"),
    # Shell config overwrite
    (re.compile(r">\s*~/?\.(bash|zsh|profile|bashrc|zshrc)\b", re.I), "overwriting shell config"),
    # Unsafe eval
    (re.compile(r"\beval\b\s+[\"'`$\(]", re.I), "eval with dynamic content"),
    (re.compile(r"\$\{"), "braced shell parameter expansion"),
    (re.compile(r"(?<![\w])\$(?:\d+|[@*#?$!-])"), "shell positional or special parameter expansion"),
    (re.compile(r"\$\("), "shell command substitution"),
    (re.compile(r"`"), "shell command substitution"),
    (re.compile(r"(?<!\$)(?:<|>)\("), "shell process substitution"),
    (
        re.compile(
            r"(?:(?:/bin/)?(?:ba|z|da|k)?sh)\b[^A-Za-z0-9]{0,8}-[A-Za-z]*c\b",
            re.I,
        ),
        "nested shell script execution",
    ),
    (
        re.compile(
            r"(^|[;|&()]\s*)(?:[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S+)\s+)*"
            r"(?:\"?\$[A-Za-z_][A-Za-z0-9_]*\"?|\$\{[A-Za-z_][A-Za-z0-9_]*\})\s+-[A-Za-z]*c\b",
        ),
        "variable-driven nested shell script execution",
    ),
    (
        re.compile(
            r"\bpython(?:3)?\b.+-c.+\b(?:os\.(?:system|popen)|subprocess\.(?:Popen|run|call|check_call|check_output|getoutput|getstatusoutput))\b",
            re.I,
        ),
        "interpreter child-process execution",
    ),
    (re.compile(r"\bfind\b.+-(exec|execdir|ok|okdir)\b", re.I), "find nested execution"),
    (re.compile(r"\bxargs\b"), "xargs-driven argument expansion"),
    (re.compile(r"(^|[;|&()]\s*)(set\s+--|shift\b)"), "shell positional parameter mutation"),
    (re.compile(r"(^|[;|&()]\s*)(for|while|until|if|case|select)\b"), "shell control flow"),
    (re.compile(r"(^|[;|&()]\s*)(declare|typeset|local|readonly)\b"), "shell variable declaration"),
    (re.compile(r"(^|[;|&()]\s*)printf\s+-v\b"), "shell variable assignment via printf -v"),
    (re.compile(r"(^|[;|&()]\s*)(source|\.)\s+"), "shell sourcing"),
    (
        re.compile(r"(^|[;|&()]\s*)(function\s+[A-Za-z_][A-Za-z0-9_]*\b|[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*\{)"),
        "shell function definition",
    ),
    (re.compile(r"(^|[;|&()]\s*)[A-Za-z_][A-Za-z0-9_]*=\("), "shell array assignment"),
    (
        re.compile(
            r"(^|[;|&()]\s*)(?:while\s+|if\s+|then\s+|do\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|\"[^\"]*\"|\S+)\s+)*"
            r"(read|mapfile|readarray)\b"
        ),
        "stdin-driven shell variable assignment",
    ),
    # Moving/deleting project data directories
    (re.compile(r"\b(rm|mv)\b.+/gpfs/projects/hrbomics/(data|predictions|gears-env)\b", re.I), "destructive op on lab data"),
]

_TIMEOUT = 30
_MAX_OUTPUT = 5_000
_QUOTED_LITERAL_RE = re.compile(r"""(['"])(?P<value>[^'"]+)\1""")
_BRACE_GROUP_RE = re.compile(r"\{([^{}]+)\}")
_SHELL_ASSIGNMENT_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_SHELL_VARIABLE_RE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")
_SHELL_CONTROL_CHARS = frozenset(";&|()<>")
_NESTED_SHELL_INTERPRETERS = frozenset({"sh", "bash", "dash", "zsh", "ksh"})
_PYTHON_INTERPRETER_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?$", re.I)
_BLOCKED_CODE_INTERPRETERS = frozenset({
    "awk",
    "gawk",
    "julia",
    "lua",
    "luajit",
    "mawk",
    "nawk",
    "node",
    "nodejs",
    "perl",
    "php",
    "ruby",
    "rscript",
    "tclsh",
    "wish",
})
_BLOCKED_RECIPE_LAUNCHERS = frozenset({
    "fab",
    "fabric",
    "gmake",
    "inv",
    "invoke",
    "just",
    "make",
    "ninja",
    "nox",
    "rake",
    "task",
    "tox",
})
_BLOCKED_WRAPPER_LAUNCHERS: dict[str, frozenset[str]] = {
    "bun": frozenset({"run", "test", "x"}),
    "npm": frozenset({"exec", "run", "start", "test"}),
    "pipenv": frozenset({"run"}),
    "pnpm": frozenset({"dlx", "exec", "run", "start", "test"}),
    "poetry": frozenset({"run"}),
    "uv": frozenset({"run", "tool", "x"}),
    "yarn": frozenset({"dlx", "exec", "run", "start", "test"}),
}
_SAFE_PYTHON_METADATA_ARGS = frozenset({
    "-V",
    "-VV",
    "--version",
    "-h",
    "--help",
    "--help-env",
    "--help-xoptions",
    "--help-all",
})


def _candidate_touches_secret_path(candidate: str) -> bool:
    cleaned = candidate.strip().strip("\"'").strip("()[]{};|&")
    return bool(cleaned) and is_secret_like_path(cleaned)


def _expand_brace_patterns(pattern: str) -> set[str]:
    match = _BRACE_GROUP_RE.search(pattern)
    if match is None:
        return {pattern}
    prefix = pattern[:match.start()]
    suffix = pattern[match.end():]
    expanded: set[str] = set()
    for option in match.group(1).split(","):
        for tail in _expand_brace_patterns(suffix):
            expanded.add(prefix + option + tail)
    return expanded


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _expand_shell_variables(candidate: str, shell_vars: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        if name is None:
            return match.group(0)
        if name in shell_vars:
            return shell_vars[name]
        return os.environ.get(name, "")

    return _SHELL_VARIABLE_RE.sub(replace, candidate)


def _expanded_shell_patterns(candidate: str, shell_vars: dict[str, str]) -> set[str]:
    expanded = _expand_shell_variables(candidate, shell_vars)
    return {pattern.strip() for pattern in _expand_brace_patterns(expanded) if pattern.strip()}


def _is_shell_control_token(token: str) -> bool:
    return bool(token) and set(token) <= _SHELL_CONTROL_CHARS


def _command_basename(token: str) -> str:
    cleaned = token.strip().strip("\"'")
    if not cleaned:
        return ""
    return Path(cleaned).name


def _segment_invokes_blocked_interpreter(segment_tokens: list[str], shell_vars: dict[str, str]) -> str | None:
    if not segment_tokens:
        return None

    expanded_tokens = [
        _expand_shell_variables(token, shell_vars).strip()
        for token in segment_tokens
        if token.strip()
    ]
    expanded_tokens = [token for token in expanded_tokens if token]
    if not expanded_tokens:
        return None

    idx = 0
    while idx < len(expanded_tokens) and _SHELL_ASSIGNMENT_RE.match(expanded_tokens[idx]):
        idx += 1
    if idx >= len(expanded_tokens):
        return None

    if expanded_tokens[idx] == "export":
        idx += 1
        while idx < len(expanded_tokens) and (
            expanded_tokens[idx].startswith("-") or _SHELL_ASSIGNMENT_RE.match(expanded_tokens[idx])
        ):
            idx += 1
    if idx >= len(expanded_tokens):
        return None

    if expanded_tokens[idx] == "env":
        idx += 1
        while idx < len(expanded_tokens) and (
            expanded_tokens[idx].startswith("-") or _SHELL_ASSIGNMENT_RE.match(expanded_tokens[idx])
        ):
            idx += 1
    if idx >= len(expanded_tokens):
        return None

    command_name = _command_basename(expanded_tokens[idx])
    args = expanded_tokens[idx + 1 :]
    if command_name.lower() in _NESTED_SHELL_INTERPRETERS:
        return "nested shell interpreter execution"
    if _PYTHON_INTERPRETER_RE.fullmatch(command_name):
        if not args or any(arg not in _SAFE_PYTHON_METADATA_ARGS for arg in args):
            return "nested Python interpreter execution"
    if command_name.lower() in _BLOCKED_CODE_INTERPRETERS:
        return "nested interpreter execution"
    if command_name.lower() in _BLOCKED_RECIPE_LAUNCHERS:
        return "file-driven recipe launcher execution"
    blocked_wrapper_subcommands = _BLOCKED_WRAPPER_LAUNCHERS.get(command_name.lower())
    if blocked_wrapper_subcommands is not None:
        for arg in args:
            if arg.startswith("-"):
                continue
            if arg in blocked_wrapper_subcommands:
                return "wrapper launcher execution"
            break
    return None


def _pattern_matches_secret_path(pattern: str, *, base_dir: str = "") -> bool:
    if not glob.has_magic(pattern):
        return False
    root = Path(base_dir).resolve() if base_dir else Path.cwd()
    search_pattern = pattern if os.path.isabs(pattern) else str(root / pattern)
    return any(is_secret_like_path(match) for match in glob.glob(search_pattern, recursive=True))


def _command_touches_secret_path(command: str, *, base_dir: str = "") -> bool:
    try:
        tokens = _shell_tokens(command)
    except ValueError:
        tokens = command.split()
    persistent_shell_vars: dict[str, str] = {}
    segment_shell_vars: dict[str, str] = {}
    segment_has_command = False
    export_mode = False
    for token in tokens:
        candidate = token.strip()
        if not candidate:
            continue
        if _is_shell_control_token(candidate):
            if not segment_has_command and segment_shell_vars:
                persistent_shell_vars.update(segment_shell_vars)
            segment_shell_vars = {}
            segment_has_command = False
            export_mode = False
            continue
        if candidate == "export" and not segment_has_command and not segment_shell_vars:
            export_mode = True
            segment_has_command = True
            continue
        assignment = _SHELL_ASSIGNMENT_RE.match(candidate)
        if assignment and (not segment_has_command or export_mode):
            current_shell_vars = {**persistent_shell_vars, **segment_shell_vars}
            value = assignment.group("value")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            expanded_value = _expand_shell_variables(value, current_shell_vars)
            if export_mode:
                persistent_shell_vars[assignment.group("name")] = expanded_value
            else:
                segment_shell_vars[assignment.group("name")] = expanded_value
            continue
        current_shell_vars = {**persistent_shell_vars, **segment_shell_vars}
        if candidate.startswith("-"):
            segment_has_command = True
            export_mode = False
            continue
        for expanded_candidate in _expanded_shell_patterns(candidate, current_shell_vars):
            if _candidate_touches_secret_path(expanded_candidate):
                return True
            if _pattern_matches_secret_path(expanded_candidate, base_dir=base_dir):
                return True
            for match in _QUOTED_LITERAL_RE.finditer(expanded_candidate):
                if _candidate_touches_secret_path(match.group("value")):
                    return True
        for match in _QUOTED_LITERAL_RE.finditer(candidate):
            expanded_literal = _expand_shell_variables(match.group("value"), current_shell_vars)
            if _candidate_touches_secret_path(expanded_literal):
                return True
        segment_has_command = True
        export_mode = False
    if not segment_has_command and segment_shell_vars:
        persistent_shell_vars.update(segment_shell_vars)
    expanded_command = _expand_shell_variables(command, persistent_shell_vars)
    for match in _QUOTED_LITERAL_RE.finditer(expanded_command):
        if _candidate_touches_secret_path(match.group("value")):
            return True
    return False


def _blocked_interpreter_reason(command: str) -> str | None:
    try:
        tokens = _shell_tokens(command)
    except ValueError:
        tokens = command.split()
    persistent_shell_vars: dict[str, str] = {}
    segment_shell_vars: dict[str, str] = {}
    segment_tokens: list[str] = []
    segment_has_command = False
    export_mode = False

    def finalize_segment() -> str | None:
        current_shell_vars = {**persistent_shell_vars, **segment_shell_vars}
        return _segment_invokes_blocked_interpreter(segment_tokens, current_shell_vars)

    for token in tokens:
        candidate = token.strip()
        if not candidate:
            continue
        if _is_shell_control_token(candidate):
            reason = finalize_segment()
            if reason is not None:
                return reason
            if not segment_has_command and segment_shell_vars:
                persistent_shell_vars.update(segment_shell_vars)
            segment_shell_vars = {}
            segment_tokens = []
            segment_has_command = False
            export_mode = False
            continue
        if candidate == "export" and not segment_has_command and not segment_shell_vars:
            export_mode = True
            segment_tokens.append(candidate)
            segment_has_command = True
            continue
        assignment = _SHELL_ASSIGNMENT_RE.match(candidate)
        if assignment and (not segment_has_command or export_mode):
            current_shell_vars = {**persistent_shell_vars, **segment_shell_vars}
            value = assignment.group("value")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            expanded_value = _expand_shell_variables(value, current_shell_vars)
            if export_mode:
                persistent_shell_vars[assignment.group("name")] = expanded_value
            else:
                segment_shell_vars[assignment.group("name")] = expanded_value
            segment_tokens.append(candidate)
            continue
        segment_tokens.append(candidate)
        segment_has_command = True
        export_mode = False

    return finalize_segment()


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
        if self.base_dir:
            policy = config.get_production_hardening_policy()
            if not policy.tools.terminal_enabled:
                return "[BLOCKED] Terminal tool is disabled by production hardening policy."

        # Safety check — regex-based pattern matching
        for pattern, reason in _BLOCKED_PATTERNS:
            if pattern.search(command):
                return f"[BLOCKED] Command refused — {reason}."
        interpreter_reason = _blocked_interpreter_reason(command)
        if interpreter_reason is not None:
            return f"[BLOCKED] Command refused — {interpreter_reason}."
        if _command_touches_secret_path(command, base_dir=self.base_dir):
            return "[BLOCKED] Command refused — reading credential or secret file."

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
