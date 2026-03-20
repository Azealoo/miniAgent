"""MultiQC execution and report-inspection helpers for workflow integrations."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


@dataclass(frozen=True)
class MultiQCCommandResult:
    executable: str
    command: tuple[str, ...]
    tool_version: str
    stdout: str
    stderr: str
    report_html_path: str
    data_directory_path: str | None


@dataclass(frozen=True)
class MultiQCReportSummary:
    sample_names: tuple[str, ...]
    module_names: tuple[str, ...]
    summary_data_path: str | None
    data_directory_path: str | None


def probe_multiqc_version(executable: str, *, base_dir: Path | str) -> str:
    base_path = Path(base_dir).resolve()
    result = _run_subprocess((executable, "--version"), cwd=base_path)
    if result.returncode != 0:
        raise RuntimeError(_process_error_message(result, executable=executable, purpose="version check"))
    combined_output = "\n".join(
        line.strip()
        for line in (result.stdout, result.stderr)
        if isinstance(line, str) and line.strip()
    )
    first_line = next((line.strip() for line in combined_output.splitlines() if line.strip()), "")
    if not first_line:
        raise RuntimeError(f"MultiQC version check using {executable!r} returned no version output.")
    return first_line


def run_multiqc(
    *,
    executable: str,
    input_paths: Sequence[str],
    output_dir: str,
    report_filename: str = "multiqc_report.html",
    extra_args: Sequence[str] = (),
    base_dir: Path | str,
) -> MultiQCCommandResult:
    base_path = Path(base_dir).resolve()
    output_dir_relpath = _coerce_project_relative_path(base_path, output_dir)
    report_name = Path(report_filename).name.strip() or "multiqc_report.html"
    tool_version = probe_multiqc_version(executable, base_dir=base_path)
    command = (
        executable,
        "--outdir",
        output_dir_relpath,
        "--filename",
        report_name,
        "--force",
        *tuple(extra_args),
        *tuple(input_paths),
    )
    result = _run_subprocess(command, cwd=base_path)
    if result.returncode != 0:
        raise RuntimeError(_process_error_message(result, executable=executable, purpose="execution"))

    report_html_path = str(PurePosixPath(output_dir_relpath) / report_name)
    report_html_abs = (base_path / report_html_path).resolve()
    if not report_html_abs.exists():
        raise RuntimeError(
            f"MultiQC completed without producing expected HTML report {report_html_path!r}."
        )

    data_directory_relpath = str(PurePosixPath(output_dir_relpath) / "multiqc_data")
    data_directory_abs = (base_path / data_directory_relpath).resolve()
    resolved_data_directory = data_directory_relpath if data_directory_abs.is_dir() else None

    return MultiQCCommandResult(
        executable=executable,
        command=command,
        tool_version=tool_version,
        stdout=result.stdout,
        stderr=result.stderr,
        report_html_path=report_html_path,
        data_directory_path=resolved_data_directory,
    )


def inspect_multiqc_report(
    base_dir: Path | str,
    output_dir: str | Path,
) -> MultiQCReportSummary:
    base_path = Path(base_dir).resolve()
    output_dir_relpath = _coerce_project_relative_path(base_path, output_dir)
    data_directory_relpath = str(PurePosixPath(output_dir_relpath) / "multiqc_data")
    data_directory_abs = (base_path / data_directory_relpath).resolve()
    if not data_directory_abs.is_dir():
        return MultiQCReportSummary(
            sample_names=(),
            module_names=(),
            summary_data_path=None,
            data_directory_path=None,
        )

    summary_candidates = [
        data_directory_abs / "bioapex_multiqc_summary.json",
        data_directory_abs / "multiqc_data.json",
    ]
    for candidate in summary_candidates:
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        return MultiQCReportSummary(
            sample_names=tuple(_extract_sample_names(payload)),
            module_names=tuple(_extract_module_names(payload)),
            summary_data_path=candidate.relative_to(base_path).as_posix(),
            data_directory_path=data_directory_relpath,
        )

    return MultiQCReportSummary(
        sample_names=(),
        module_names=(),
        summary_data_path=None,
        data_directory_path=data_directory_relpath,
    )


def _run_subprocess(command: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"MultiQC executable {command[0]!r} was not found.") from exc
    except OSError as exc:
        raise RuntimeError(f"MultiQC command {command[0]!r} could not be started: {exc}") from exc


def _process_error_message(
    result: subprocess.CompletedProcess[str],
    *,
    executable: str,
    purpose: str,
) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit code {result.returncode}"
    return f"MultiQC {purpose} failed for executable {executable!r}: {detail}"


def _coerce_project_relative_path(base_dir: Path, value: str | Path) -> str:
    candidate = Path(str(value))
    if candidate.is_absolute():
        resolved = candidate.resolve()
        try:
            return resolved.relative_to(base_dir).as_posix()
        except ValueError as exc:
            raise ValueError(f"Path {resolved} must stay under {base_dir}.") from exc

    normalized = PurePosixPath(str(value))
    if normalized.is_absolute():
        raise ValueError(f"Path {value!r} must stay relative to the project root.")
    if any(part == ".." for part in normalized.parts):
        raise ValueError(f"Path {value!r} must not escape the project root.")
    if not str(normalized).strip():
        raise ValueError("Path must not be empty.")
    return normalized.as_posix()


def _extract_sample_names(payload: Any) -> list[str]:
    sample_names: list[str] = []
    seen: set[str] = set()

    def remember(value: Any) -> None:
        if not isinstance(value, str):
            return
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        sample_names.append(candidate)

    if isinstance(payload, dict):
        _remember_string_list(payload.get("sample_names"), remember)
        samples = payload.get("samples")
        if isinstance(samples, dict):
            for key in samples:
                remember(key)
        else:
            _remember_string_list(samples, remember)
        _collect_general_stats_sample_names(payload.get("report_general_stats_data"), remember)
        saved_raw_data = payload.get("report_saved_raw_data")
        if isinstance(saved_raw_data, dict):
            for item in saved_raw_data.values():
                _collect_mapping_keys(item, remember)

    return sample_names


def _extract_module_names(payload: Any) -> list[str]:
    module_names: list[str] = []
    seen: set[str] = set()

    def remember(value: Any) -> None:
        if not isinstance(value, str):
            return
        candidate = value.strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        module_names.append(candidate)

    if isinstance(payload, dict):
        _remember_string_list(payload.get("module_names"), remember)
        report_modules = payload.get("report_modules")
        if isinstance(report_modules, list):
            for item in report_modules:
                if isinstance(item, str):
                    remember(item)
                elif isinstance(item, dict):
                    remember(item.get("name") or item.get("title") or item.get("anchor"))
        saved_raw_data = payload.get("report_saved_raw_data")
        if isinstance(saved_raw_data, dict):
            for key in saved_raw_data:
                remember(key)

    return module_names


def _remember_string_list(value: Any, remember) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        remember(item)


def _collect_general_stats_sample_names(value: Any, remember) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_general_stats_sample_names(item, remember)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        lowered = str(key).strip().lower()
        if lowered in {"sample", "sample_name", "sample id", "sample_id", "name"}:
            remember(item)
            continue
        if isinstance(item, dict):
            remember(key)


def _collect_mapping_keys(value: Any, remember) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict):
                remember(key)
            elif isinstance(item, list):
                _collect_mapping_keys(item, remember)
    elif isinstance(value, list):
        for item in value:
            _collect_mapping_keys(item, remember)
