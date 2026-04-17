from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import config

MAX_COMPONENT_CHARS = 20_000
MAX_PROJECT_INSTRUCTION_FILE_CHARS = 2_000
MAX_PROJECT_INSTRUCTION_TOTAL_CHARS = 8_000
MAX_GIT_CONTEXT_CHARS = 2_000
MAX_RETRIEVED_MEMORY_BLOCK_CHARS = 1_600
MAX_RETRIEVED_MEMORY_ITEM_CHARS = 280

_RAG_MEMORY_GUIDANCE = (
    "<!-- Long-term Memory -->\n"
    "Your long-term memory is managed via RAG (Retrieval-Augmented Generation). "
    "Relevant memories will be dynamically retrieved and injected as context before each response. "
    "Use retrieved memory as background guidance only: it may include templates, heuristics, or "
    "prior-session notes. Do not present retrieved memory as something you verified in the current "
    "turn unless you explicitly inspected the referenced file or tool output."
)
_TOOL_RESULT_ERROR_GUIDANCE = (
    "<!-- Tool Result Error Contract -->\n"
    "Every tool call returns a structured envelope (contract_version = `tool_result.v1`) with a "
    "top-level `status` field (`success` or `error`), an `outcome` tag, and — when something went "
    "wrong — a populated `error` object of shape "
    "`{ code: 'blocked' | 'invalid_input' | 'retriable_failure' | 'execution_failure', "
    "message: string, retriable: boolean }`. If a wrapped tool raises an uncaught exception "
    "the wrapper will NOT silently drop it: it logs the traceback and returns an envelope with "
    "`status = 'error'` and `outcome = 'execution_failure'` (or `'retriable_failure'` for "
    "timeouts / connection / rate-limit style errors). Treat any envelope where `status == 'error'` "
    "as a failed call: do not assume the underlying action succeeded, do not fabricate output, and "
    "do not proceed with downstream steps that depend on the failed result. React based on "
    "`error.code`: retry only when `error.retriable` is true (after addressing the cause), ask the "
    "user or adjust inputs when `code == 'invalid_input'`, respect policy when `code == 'blocked'`, "
    "and surface the failure to the user with `error.message` when `code == 'execution_failure'`."
)
_PROJECT_REFERENCE_RE = re.compile(r"(?m)^\s*(?:[-*]\s+)?@(?P<path>[^\s#]+)")
_PROJECT_INSTRUCTION_FILENAMES = (
    "AGENTS.md",
    "CLAW.md",
    "CLAW.local.md",
)
_PROJECT_INSTRUCTION_RELATIVE_PATHS = (
    Path(".claw") / "CLAW.md",
    Path(".claw") / "instructions.md",
)


def _truncate_text(text: str, max_chars: int, *, marker: str = "\n...[truncated]") -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + marker, True


def _format_retrieved_memory_label(result: dict[str, Any]) -> str:
    source = result.get("source")
    if not isinstance(source, str) or not source:
        return ""

    label_parts: list[str] = []
    memory_type_label = result.get("memory_type_label")
    if not isinstance(memory_type_label, str) or not memory_type_label.strip():
        memory_type = result.get("memory_type")
        if isinstance(memory_type, str) and memory_type.strip():
            memory_type_label = memory_type.replace("_", " ")
    if isinstance(memory_type_label, str) and memory_type_label.strip():
        label_parts.append(f"[{memory_type_label.strip()}]")

    memory_name = result.get("memory_name")
    if isinstance(memory_name, str) and memory_name.strip():
        label_parts.append(memory_name.strip())

    label_parts.append(f"@ {source}")
    return " ".join(label_parts)


def build_retrieved_memory_block(results: list[dict]) -> str:
    lines = ["[Retrieved Memory - background context only; not verified current project state]"]

    for result in results:
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        label = _format_retrieved_memory_label(result)
        if not label:
            continue

        compact_text = " ".join(text.split())
        compact_text, _ = _truncate_text(
            compact_text,
            MAX_RETRIEVED_MEMORY_ITEM_CHARS,
            marker="...",
        )
        lines.append(f"- {label}: {compact_text}")

    if len(lines) == 1:
        return ""

    rendered = "\n".join(lines)
    rendered, _ = _truncate_text(
        rendered,
        MAX_RETRIEVED_MEMORY_BLOCK_CHARS,
        marker="\n...[retrieved memory truncated]",
    )
    return rendered


def _read_component(path: Path, *, max_chars: int = MAX_COMPONENT_CHARS) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    content, _ = _truncate_text(content, max_chars)
    return content


def _iter_ancestor_dirs(start: Path) -> list[Path]:
    directories: list[Path] = []
    current = start.resolve()
    while True:
        directories.append(current)
        if current.parent == current:
            break
        current = current.parent
    directories.reverse()
    return directories


def _discover_project_instruction_files(base_dir: Path) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for directory in _iter_ancestor_dirs(base_dir):
        candidates = [directory / name for name in _PROJECT_INSTRUCTION_FILENAMES]
        candidates.extend(directory / relative for relative in _PROJECT_INSTRUCTION_RELATIVE_PATHS)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen or not candidate.exists() or not candidate.is_file():
                continue
            seen.add(resolved)
            discovered.append(candidate)
    return discovered


def _extract_project_reference_files(instruction_file: Path, content: str) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for match in _PROJECT_REFERENCE_RE.finditer(content):
        raw_ref = match.group("path").strip()
        if not raw_ref or "://" in raw_ref or raw_ref.startswith("app://"):
            continue
        candidate = (instruction_file.parent / raw_ref).resolve()
        if candidate in seen or not candidate.exists() or not candidate.is_file():
            continue
        seen.add(candidate)
        discovered.append(candidate)
    return discovered


def _display_project_reference(instruction_file: Path, referenced_file: Path) -> str:
    try:
        return str(referenced_file.relative_to(instruction_file.parent))
    except ValueError:
        return referenced_file.name


def _build_project_instruction_context(base_dir: Path) -> str:
    sections: list[str] = []
    seen: set[Path] = set()
    remaining_chars = MAX_PROJECT_INSTRUCTION_TOTAL_CHARS

    for instruction_file in _discover_project_instruction_files(base_dir):
        resolved_instruction = instruction_file.resolve()
        if resolved_instruction in seen or remaining_chars <= 0:
            continue

        instruction_content = _read_component(
            instruction_file,
            max_chars=min(MAX_PROJECT_INSTRUCTION_FILE_CHARS, remaining_chars),
        )
        if not instruction_content:
            continue

        seen.add(resolved_instruction)
        sections.append(
            f"<!-- Project Instructions: {instruction_file.name} -->\n{instruction_content}"
        )
        remaining_chars = max(0, remaining_chars - len(instruction_content))
        if remaining_chars <= 0:
            break

        for referenced_file in _extract_project_reference_files(
            instruction_file,
            instruction_content,
        ):
            resolved_reference = referenced_file.resolve()
            if resolved_reference in seen or remaining_chars <= 0:
                continue

            reference_content = _read_component(
                referenced_file,
                max_chars=min(MAX_PROJECT_INSTRUCTION_FILE_CHARS, remaining_chars),
            )
            if not reference_content:
                continue

            seen.add(resolved_reference)
            sections.append(
                (
                    "<!-- Project Context File: "
                    f"{_display_project_reference(instruction_file, referenced_file)} -->\n"
                    f"{reference_content}"
                )
            )
            remaining_chars = max(0, remaining_chars - len(reference_content))

    if remaining_chars == 0:
        sections.append("<!-- Project Context -->\n...[project context truncated]")

    return "\n\n".join(sections)


def _run_git_command(base_dir: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=base_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""

    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _build_git_context(base_dir: Path) -> str:
    include_git_context_env = os.getenv("BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT", "").strip().lower()
    if include_git_context_env:
        include_git_context = include_git_context_env in {"1", "true", "yes", "on"}
    else:
        include_git_context = bool(
            config.get_prompt_context_settings().get("include_git_context", False)
        )
    if not include_git_context:
        return ""

    status = _run_git_command(base_dir, "status", "--short", "--branch")
    diff_stat = _run_git_command(base_dir, "diff", "--stat")

    if not status and not diff_stat:
        return ""

    sections: list[str] = []
    if status:
        sections.append(f"Git status snapshot:\n{status}")
    if diff_stat:
        sections.append(f"Git diff stat:\n{diff_stat}")

    rendered, _ = _truncate_text("\n\n".join(sections), MAX_GIT_CONTEXT_CHARS)
    return f"<!-- Project Git Context -->\n{rendered}"


def _build_skills_snapshot_context(
    base_dir: Path,
    *,
    skill_entries: list[dict[str, Any]] | None = None,
) -> str:
    from tools.skills_scanner import collect_skill_entries, iter_skill_files, render_skills_snapshot

    if skill_entries is not None:
        return render_skills_snapshot(skill_entries)

    runtime_skill_entries = collect_skill_entries(base_dir, respect_enabled=True)
    if runtime_skill_entries or iter_skill_files(base_dir):
        return render_skills_snapshot(runtime_skill_entries)
    return _read_component(base_dir / "SKILLS_SNAPSHOT.md")


def build_system_prompt(
    base_dir: Path,
    rag_mode: bool = False,
    *,
    skill_entries: list[dict[str, Any]] | None = None,
) -> str:
    """
    Assemble the system prompt from the 6 ordered workspace components and
    any additive project context discovered around the workspace root.
    Components exceeding MAX_COMPONENT_CHARS are truncated.
    """
    parts: list[str] = []

    snap = _build_skills_snapshot_context(base_dir, skill_entries=skill_entries)
    if snap:
        parts.append(f"<!-- Skills Snapshot -->\n{snap}")

    soul = _read_component(base_dir / "workspace" / "SOUL.md")
    if soul:
        parts.append(f"<!-- Soul -->\n{soul}")

    identity = _read_component(base_dir / "workspace" / "IDENTITY.md")
    if identity:
        parts.append(f"<!-- Identity -->\n{identity}")

    user = _read_component(base_dir / "workspace" / "USER.md")
    if user:
        parts.append(f"<!-- User Profile -->\n{user}")

    agents = _read_component(base_dir / "workspace" / "AGENTS.md")
    if agents:
        parts.append(f"<!-- Agents Guide -->\n{agents}")

    project_instructions = _build_project_instruction_context(base_dir)
    if project_instructions:
        parts.append(project_instructions)

    git_context = _build_git_context(base_dir)
    if git_context:
        parts.append(git_context)

    parts.append(_TOOL_RESULT_ERROR_GUIDANCE)

    if rag_mode:
        parts.append(_RAG_MEMORY_GUIDANCE)
    else:
        memory = _read_component(base_dir / "memory" / "MEMORY.md")
        if memory:
            parts.append(f"<!-- Long-term Memory -->\n{memory}")

    return "\n\n".join(parts)
