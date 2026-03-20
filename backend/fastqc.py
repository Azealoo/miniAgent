"""FastQC execution and parsing helpers for workflow integrations."""

from __future__ import annotations

import csv
import hashlib
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

FastQCSequencingLayout = Literal["single_end", "paired_end"]
FastQCReadLabel = Literal["single", "read1", "read2"]
FastQCStatus = Literal["pass", "warn", "fail"]

_FASTQ_SUFFIXES = (
    ".fastq.gz",
    ".fq.gz",
    ".fastq.bz2",
    ".fq.bz2",
    ".fastq",
    ".fq",
)
_NORMALIZE_IDENTIFIER_CHARS_RE = re.compile(r"[^a-z0-9._:-]+")


@dataclass(frozen=True)
class FastQCReadInput:
    sample_id: str
    read_label: FastQCReadLabel
    relative_path: str
    absolute_path: Path
    row_number: int


@dataclass(frozen=True)
class FastQCModuleResult:
    module_id: str
    module_name: str
    status: FastQCStatus


@dataclass(frozen=True)
class FastQCParsedReport:
    sample_id: str
    read_label: FastQCReadLabel
    input_relpath: str
    total_sequences: int | None
    sequences_flagged_as_poor_quality: int | None
    sequence_length: str | None
    percent_gc: float | None
    min_per_base_quality: float | None
    module_results: tuple[FastQCModuleResult, ...]
    overall_status: FastQCStatus


@dataclass(frozen=True)
class FastQCCommandResult:
    executable: str
    command: tuple[str, ...]
    tool_version: str
    stdout: str
    stderr: str


def load_fastqc_inputs(
    base_dir: Path | str,
    sample_sheet_path: str | Path,
) -> tuple[FastQCSequencingLayout, list[FastQCReadInput]]:
    base_path = Path(base_dir).resolve()
    normalized_sample_sheet_path = _coerce_project_relative_path(base_path, sample_sheet_path)
    sample_sheet_abs = (base_path / normalized_sample_sheet_path).resolve()
    if not sample_sheet_abs.exists():
        raise ValueError(f"FastQC sample sheet {normalized_sample_sheet_path!r} does not exist.")

    delimiter = "\t" if sample_sheet_abs.suffix.lower() in {".tsv", ".txt"} else ","
    with sample_sheet_abs.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fieldnames = [_normalize_header(field) for field in (reader.fieldnames or [])]
        normalized_rows = [
            {_normalize_header(key): (value.strip() if isinstance(value, str) else "") for key, value in row.items()}
            for row in reader
        ]

    required_columns = {"sample_id", "fastq_r1"}
    missing_columns = sorted(column for column in required_columns if column not in fieldnames)
    if missing_columns:
        raise ValueError(
            "FastQC sample sheet must include columns "
            f"{', '.join(sorted(required_columns))}; missing {', '.join(missing_columns)}."
        )

    records: list[FastQCReadInput] = []
    seen_sample_ids: set[str] = set()
    has_read2 = False
    has_single_end = False
    for row_number, row in enumerate(normalized_rows, start=2):
        if _row_is_empty(row):
            continue

        sample_id = str(row.get("sample_id", "")).strip()
        fastq_r1 = str(row.get("fastq_r1", "")).strip()
        fastq_r2 = str(row.get("fastq_r2", "")).strip()

        if not sample_id:
            raise ValueError(f"FastQC sample sheet row {row_number} is missing sample_id.")
        if sample_id in seen_sample_ids:
            raise ValueError(
                f"FastQC sample sheet row {row_number} repeats sample_id {sample_id!r}; "
                "this authored contract requires one row per sample_id."
            )
        seen_sample_ids.add(sample_id)

        if not fastq_r1:
            raise ValueError(f"FastQC sample sheet row {row_number} is missing fastq_r1.")

        read1_relpath = _coerce_project_relative_path(base_path, fastq_r1)
        read1_abs = (base_path / read1_relpath).resolve()
        if not read1_abs.exists():
            raise ValueError(
                f"FastQC sample sheet row {row_number} references missing FASTQ file {read1_relpath!r}."
            )
        if fastq_r2:
            has_read2 = True
            read2_relpath = _coerce_project_relative_path(base_path, fastq_r2)
            read2_abs = (base_path / read2_relpath).resolve()
            if not read2_abs.exists():
                raise ValueError(
                    f"FastQC sample sheet row {row_number} references missing FASTQ file {read2_relpath!r}."
                )
            records.append(
                FastQCReadInput(
                    sample_id=sample_id,
                    read_label="read1",
                    relative_path=read1_relpath,
                    absolute_path=read1_abs,
                    row_number=row_number,
                )
            )
            records.append(
                FastQCReadInput(
                    sample_id=sample_id,
                    read_label="read2",
                    relative_path=read2_relpath,
                    absolute_path=read2_abs,
                    row_number=row_number,
                )
            )
        else:
            has_single_end = True
            records.append(
                FastQCReadInput(
                    sample_id=sample_id,
                    read_label="single",
                    relative_path=read1_relpath,
                    absolute_path=read1_abs,
                    row_number=row_number,
                )
            )

    if not records:
        raise ValueError("FastQC sample sheet must include at least one non-empty data row.")
    if has_read2 and has_single_end:
        raise ValueError("FastQC sample sheet must use a consistent layout across rows.")

    layout: FastQCSequencingLayout = "paired_end" if has_read2 else "single_end"
    return layout, records


def probe_fastqc_version(executable: str, *, base_dir: Path | str) -> str:
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
        raise RuntimeError(f"FastQC version check using {executable!r} returned no version output.")
    return first_line


def run_fastqc(
    *,
    executable: str,
    input_paths: Sequence[str],
    output_dir: str,
    extra_args: Sequence[str] = (),
    base_dir: Path | str,
) -> FastQCCommandResult:
    base_path = Path(base_dir).resolve()
    tool_version = probe_fastqc_version(executable, base_dir=base_path)
    command = (executable, "--outdir", output_dir, *tuple(extra_args), *tuple(input_paths))
    result = _run_subprocess(command, cwd=base_path)
    if result.returncode != 0:
        raise RuntimeError(_process_error_message(result, executable=executable, purpose="execution"))
    return FastQCCommandResult(
        executable=executable,
        command=command,
        tool_version=tool_version,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fastqc_output_prefix(input_path: str | Path) -> str:
    name = Path(str(input_path)).name
    lower_name = name.lower()
    for suffix in _FASTQ_SUFFIXES:
        if lower_name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def parse_fastqc_archive(
    archive_path: Path | str,
    *,
    sample_id: str,
    read_label: FastQCReadLabel,
    input_relpath: str,
) -> FastQCParsedReport:
    archive = Path(archive_path)
    with zipfile.ZipFile(archive) as zipped:
        summary_text = _read_member_text(zipped, "summary.txt")
        fastqc_data_text = _read_member_text(zipped, "fastqc_data.txt")

    module_results = tuple(_parse_summary(summary_text))
    module_statuses = {result.module_id: result.status for result in module_results}
    sections = _parse_fastqc_sections(fastqc_data_text)
    basic_statistics = _parse_basic_statistics(sections.get("Basic Statistics", []))
    min_per_base_quality = _parse_per_base_quality(sections.get("Per base sequence quality", []))

    return FastQCParsedReport(
        sample_id=sample_id,
        read_label=read_label,
        input_relpath=input_relpath,
        total_sequences=_safe_int(basic_statistics.get("Total Sequences")),
        sequences_flagged_as_poor_quality=_safe_int(basic_statistics.get("Sequences flagged as poor quality")),
        sequence_length=_clean_optional_string(basic_statistics.get("Sequence length")),
        percent_gc=_safe_float(basic_statistics.get("%GC")),
        min_per_base_quality=min_per_base_quality,
        module_results=module_results,
        overall_status=_worst_status(module_statuses.values()),
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
        raise ValueError(f"FastQC executable {command[0]!r} was not found.") from exc
    except OSError as exc:
        raise RuntimeError(f"FastQC command {command[0]!r} could not be started: {exc}") from exc


def _process_error_message(
    result: subprocess.CompletedProcess[str],
    *,
    executable: str,
    purpose: str,
) -> str:
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit code {result.returncode}"
    return f"FastQC {purpose} failed for executable {executable!r}: {detail}"


def _normalize_header(value: str | None) -> str:
    if value is None:
        return ""
    return value.lstrip("\ufeff").strip()


def _row_is_empty(row: dict[str, str]) -> bool:
    return not any(str(value).strip() for value in row.values())


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


def _read_member_text(archive: zipfile.ZipFile, suffix: str) -> str:
    candidates = [name for name in archive.namelist() if name.endswith(suffix)]
    if not candidates:
        raise ValueError(f"FastQC archive is missing {suffix!r}.")
    with archive.open(sorted(candidates)[0]) as handle:
        return handle.read().decode("utf-8")


def _parse_summary(summary_text: str) -> list[FastQCModuleResult]:
    results: list[FastQCModuleResult] = []
    for line in summary_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        status_text, module_name, *_ = stripped.split("\t")
        normalized_name = module_name.strip()
        results.append(
            FastQCModuleResult(
                module_id=_normalize_identifier(normalized_name),
                module_name=normalized_name,
                status=_normalize_status(status_text),
            )
        )
    if not results:
        raise ValueError("FastQC summary.txt did not contain any module results.")
    return results


def _parse_fastqc_sections(fastqc_data_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_name: str | None = None
    current_rows: list[str] = []
    for raw_line in fastqc_data_text.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith(">>END_MODULE"):
            if current_name is not None:
                sections[current_name] = list(current_rows)
            current_name = None
            current_rows = []
            continue
        if line.startswith("##FastQC"):
            continue
        if line.startswith(">>"):
            body = line[2:]
            section_name, _, _status = body.partition("\t")
            current_name = section_name.strip()
            current_rows = []
            continue
        if current_name is not None:
            current_rows.append(line)
    return sections


def _parse_basic_statistics(rows: Sequence[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in rows:
        if not row or row.startswith("#"):
            continue
        parts = row.split("\t")
        if len(parts) < 2:
            continue
        values[parts[0].strip()] = parts[1].strip()
    return values


def _parse_per_base_quality(rows: Sequence[str]) -> float | None:
    header: list[str] | None = None
    mean_index: int | None = None
    means: list[float] = []

    for row in rows:
        if not row.strip():
            continue
        if row.startswith("#"):
            header = [item.strip() for item in row.lstrip("#").split("\t")]
            try:
                mean_index = header.index("Mean")
            except ValueError as exc:
                raise ValueError("FastQC per-base quality section is missing the Mean column.") from exc
            continue
        if mean_index is None:
            continue
        parts = row.split("\t")
        if mean_index >= len(parts):
            continue
        mean_value = _safe_float(parts[mean_index])
        if mean_value is not None:
            means.append(mean_value)

    if not means:
        return None
    return min(means)


def _normalize_status(value: str) -> FastQCStatus:
    normalized = value.strip().lower()
    if normalized in {"pass", "warn", "fail"}:
        return normalized  # type: ignore[return-value]
    raise ValueError(f"Unsupported FastQC status {value!r}.")


def _worst_status(statuses: Sequence[FastQCStatus]) -> FastQCStatus:
    seen = set(statuses)
    if "fail" in seen:
        return "fail"
    if "warn" in seen:
        return "warn"
    return "pass"


def _normalize_identifier(value: str) -> str:
    candidate = value.strip().lower().replace("/", "-").replace(" ", "-")
    candidate = _NORMALIZE_IDENTIFIER_CHARS_RE.sub("-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("._:-")
    if not candidate:
        raise ValueError(f"Could not normalize FastQC identifier from {value!r}.")
    return candidate


def _clean_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _safe_int(value: str | None) -> int | None:
    cleaned = _clean_optional_string(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _safe_float(value: str | None) -> float | None:
    cleaned = _clean_optional_string(value)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
