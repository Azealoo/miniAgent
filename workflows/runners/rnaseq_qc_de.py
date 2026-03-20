"""Python executors for the authored RNA-seq workflow."""

from __future__ import annotations

import csv
import math
import os
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from artifacts import (
    CountMatrix,
    DatasetManifest,
    FastQCMetrics,
    FastQCRun,
    RUN_RECORD_FILENAME,
    WorkflowRun,
    build_generated_output_relpath,
    load_artifact_document,
    stable_artifact_name,
)
from dataset_intake import ensure_valid_dataset_intake_manifest
from fastqc import (
    FastQCParsedReport,
    fastqc_output_prefix,
    hash_file,
    load_fastqc_inputs,
    parse_fastqc_archive,
    run_fastqc,
)
from multiqc import inspect_multiqc_report, run_multiqc


_RNASEQ_WORKFLOW_VERSION = "1.0.0"
_QUANTIFICATION_ENGINE = "bioapex_deterministic_quantification"
_DIFFERENTIAL_EXPRESSION_ENGINE = "bioapex_mean_centered_t_test"
_ENGINE_VERSION = "1.0.0"
_DE_SIGNIFICANCE_THRESHOLD = 0.05
_DE_LOG2_EFFECT_FLOOR = 1.0
_REPORT_BUNDLE_STEP_ID = "report_bundle"
_REPORT_BUNDLE_FILENAME = "rnaseq_report_bundle.md"
_REPORT_BUNDLE_WORKFLOW_OUTPUT_ARTIFACT_TYPES: tuple[str, ...] = (
    "fastqc_run",
    "fastqc_metrics",
    "multiqc_run",
    "multiqc_metrics",
    "count_matrix",
    "normalized_count_matrix",
    "differential_expression_results",
    "differential_expression_run",
)
_REPORT_BUNDLE_SECTIONS: tuple[str, ...] = (
    "executive_summary",
    "inputs_used",
    "workflow_version",
    "qc_summary",
    "key_outputs",
    "warnings_and_failures",
    "deviations",
    "provenance_pointers",
    "next_recommended_actions",
)
_DE_GENE_PANEL: tuple[dict[str, Any], ...] = (
    {
        "gene_id": "ENSG00000185745",
        "gene_symbol": "IFIT1",
        "baseline_count": 1800,
        "contrast_delta": 2600,
        "batch_weight": 80,
    },
    {
        "gene_id": "ENSG00000187608",
        "gene_symbol": "ISG15",
        "baseline_count": 950,
        "contrast_delta": 1700,
        "batch_weight": 55,
    },
    {
        "gene_id": "ENSG00000111335",
        "gene_symbol": "OAS1",
        "baseline_count": 720,
        "contrast_delta": 1200,
        "batch_weight": 35,
    },
    {
        "gene_id": "ENSG00000157601",
        "gene_symbol": "MX1",
        "baseline_count": 840,
        "contrast_delta": 1350,
        "batch_weight": 28,
    },
    {
        "gene_id": "ENSG00000169245",
        "gene_symbol": "CXCL10",
        "baseline_count": 280,
        "contrast_delta": 920,
        "batch_weight": 18,
    },
    {
        "gene_id": "ENSG00000111640",
        "gene_symbol": "GAPDH",
        "baseline_count": 6400,
        "contrast_delta": 120,
        "batch_weight": 65,
    },
    {
        "gene_id": "ENSG00000075624",
        "gene_symbol": "ACTB",
        "baseline_count": 5200,
        "contrast_delta": -180,
        "batch_weight": 40,
    },
    {
        "gene_id": "ENSG00000100316",
        "gene_symbol": "RPLP0",
        "baseline_count": 4300,
        "contrast_delta": -120,
        "batch_weight": 24,
    },
    {
        "gene_id": "ENSG00000115414",
        "gene_symbol": "FN1",
        "baseline_count": 2100,
        "contrast_delta": -900,
        "batch_weight": 95,
    },
    {
        "gene_id": "ENSG00000100985",
        "gene_symbol": "MMP9",
        "baseline_count": 1450,
        "contrast_delta": -620,
        "batch_weight": 72,
    },
)


def validate_inputs(inputs, context):
    result = ensure_valid_dataset_intake_manifest(context.base_dir, inputs["dataset_manifest"])
    manifest = _load_manifest(context, result.manifest_path)
    condition_field = str(inputs["condition_field"]).strip()
    baseline_condition = str(inputs["baseline_condition"]).strip()
    comparison_condition = str(inputs["comparison_condition"]).strip()

    if manifest.assay_type != "bulk_rna_seq":
        raise ValueError(
            "RNA-seq workflow requires dataset_manifest.assay_type 'bulk_rna_seq'."
        )
    if manifest.design.analysis_kind != "comparative":
        raise ValueError(
            "RNA-seq workflow requires dataset_manifest.design.analysis_kind 'comparative'."
        )
    if condition_field not in (manifest.design.condition_fields or []):
        raise ValueError(
            f"RNA-seq workflow requires condition_field {condition_field!r} to appear in dataset_manifest.design.condition_fields."
        )
    if baseline_condition == comparison_condition:
        raise ValueError("baseline_condition and comparison_condition must differ.")

    return {"validated_manifest": result.manifest_path}


def run_raw_qc(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    if manifest.sample_sheet_path is None:
        raise ValueError("RNA-seq FastQC stage requires dataset_manifest.sample_sheet_path.")

    sequencing_layout, fastqc_inputs = load_fastqc_inputs(context.base_dir, manifest.sample_sheet_path)
    executable, extra_args = _fastqc_config(manifest)

    fastqc_output_dir = _generated_subdir_relative_path(context, step="raw_qc", name="fastqc")
    fastqc_output_dir_relpath = _join_run_relative(context, fastqc_output_dir)
    fastqc_output_dir_abs = context.base_dir / fastqc_output_dir_relpath
    fastqc_output_dir_abs.mkdir(parents=True, exist_ok=True)

    command_result = run_fastqc(
        executable=executable,
        input_paths=[item.relative_path for item in fastqc_inputs],
        output_dir=fastqc_output_dir_relpath,
        extra_args=extra_args,
        base_dir=context.base_dir,
    )

    stdout_relpath = _write_generated_text(
        context,
        step="raw_qc",
        filename="fastqc.stdout.txt",
        content=command_result.stdout,
    )
    stderr_relpath = _write_generated_text(
        context,
        step="raw_qc",
        filename="fastqc.stderr.txt",
        content=command_result.stderr,
    )

    parsed_reports: list[FastQCParsedReport] = []
    raw_report_refs: list[dict[str, Any]] = []
    report_sets: list[dict[str, Any]] = []
    input_file_records: list[dict[str, Any]] = []
    sample_metrics: list[dict[str, Any]] = []

    for read_input in fastqc_inputs:
        input_file_records.append(
            {
                "sample_id": read_input.sample_id,
                "read_label": read_input.read_label,
                "path": read_input.relative_path,
                "sha256": hash_file(read_input.absolute_path),
                "size_bytes": read_input.absolute_path.stat().st_size,
                "row_number": read_input.row_number,
            }
        )

        output_prefix = fastqc_output_prefix(read_input.relative_path)
        html_relpath = _join_run_relative(context, fastqc_output_dir, f"{output_prefix}_fastqc.html")
        zip_relpath = _join_run_relative(context, fastqc_output_dir, f"{output_prefix}_fastqc.zip")
        html_abspath = context.base_dir / html_relpath
        zip_abspath = context.base_dir / zip_relpath
        if not html_abspath.exists():
            raise RuntimeError(
                f"FastQC completed without producing expected HTML report {html_relpath!r}."
            )
        if not zip_abspath.exists():
            raise RuntimeError(
                f"FastQC completed without producing expected ZIP archive {zip_relpath!r}."
            )

        html_ref = _artifact_ref("fastqc_html_report", html_relpath, run_id=context.run_id)
        zip_ref = _artifact_ref("fastqc_zip_archive", zip_relpath, run_id=context.run_id)
        raw_report_refs.extend([html_ref, zip_ref])
        report_sets.append(
            {
                "sample_id": read_input.sample_id,
                "read_label": read_input.read_label,
                "html_report": html_ref,
                "zip_archive": zip_ref,
            }
        )

        parsed = parse_fastqc_archive(
            zip_abspath,
            sample_id=read_input.sample_id,
            read_label=read_input.read_label,
            input_relpath=read_input.relative_path,
        )
        parsed_reports.append(parsed)
        sample_metrics.append(
            {
                "sample_id": parsed.sample_id,
                "read_label": parsed.read_label,
                "input_file": _artifact_ref("fastq", parsed.input_relpath),
                "html_report": html_ref,
                "zip_archive": zip_ref,
                "total_sequences": parsed.total_sequences,
                "sequences_flagged_as_poor_quality": parsed.sequences_flagged_as_poor_quality,
                "sequence_length": parsed.sequence_length,
                "percent_gc": parsed.percent_gc,
                "min_per_base_quality": parsed.min_per_base_quality,
                "module_results": [
                    {
                        "module_id": module.module_id,
                        "module_name": module.module_name,
                        "status": module.status,
                    }
                    for module in parsed.module_results
                ],
                "overall_status": parsed.overall_status,
            }
        )

    aggregate_metrics = _aggregate_fastqc_reports(parsed_reports)
    fastqc_run_ref = _artifact_ref(
        "fastqc_run",
        _generated_output_path(context, "fastqc_run.json", step="raw_qc"),
        run_id=context.run_id,
    )
    fastqc_metrics_ref = _artifact_ref(
        "fastqc_metrics",
        _generated_output_path(context, "fastqc_metrics.json", step="raw_qc"),
        run_id=context.run_id,
    )
    stdout_ref = _artifact_ref("fastqc_stdout", stdout_relpath, run_id=context.run_id)
    stderr_ref = _artifact_ref("fastqc_stderr", stderr_relpath, run_id=context.run_id)

    generated_artifacts = _dedupe_artifacts(
        [
            fastqc_run_ref,
            fastqc_metrics_ref,
            stdout_ref,
            stderr_ref,
            *raw_report_refs,
        ]
    )
    metrics_related_artifacts = _dedupe_artifacts([fastqc_run_ref, *raw_report_refs])
    run_related_artifacts = _dedupe_artifacts([fastqc_metrics_ref, stdout_ref, stderr_ref, *raw_report_refs])

    metrics_artifact = {
        "tool_version": command_result.tool_version,
        "sequencing_layout": sequencing_layout,
        "sample_sheet_path": manifest.sample_sheet_path,
        "run_artifact": fastqc_run_ref,
        "related_artifacts": metrics_related_artifacts,
        "sample_metrics": sample_metrics,
        "aggregate_metrics": aggregate_metrics,
    }
    run_artifact = {
        "tool_version": command_result.tool_version,
        "sequencing_layout": sequencing_layout,
        "sample_sheet_path": manifest.sample_sheet_path,
        "output_directory": fastqc_output_dir_relpath,
        "command": list(command_result.command),
        "parameters": {
            "extra_args": list(extra_args),
            "input_count": len(fastqc_inputs),
        },
        "input_files": input_file_records,
        "reports": report_sets,
        "stdout_path": stdout_relpath,
        "stderr_path": stderr_relpath,
        "metrics_artifact": fastqc_metrics_ref,
        "related_artifacts": run_related_artifacts,
    }

    metrics_source = {
        "artifact_type": "fastqc_metrics",
        "path": fastqc_metrics_ref["path"],
        "run_id": context.run_id,
    }
    raw_qc_bundle = {
        "stage": "raw_qc",
        "workflow_id": context.workflow_id,
        "study_name": manifest.design.study_name,
        "assay_type": manifest.assay_type,
        "sequencing_layout": sequencing_layout,
        "sample_sheet_path": manifest.sample_sheet_path,
        "fastqc_run_artifact": fastqc_run_ref,
        "fastqc_metrics_artifact": fastqc_metrics_ref,
        "generated_artifacts": generated_artifacts,
        "aggregate_metrics": aggregate_metrics,
        "qc_evidence": {
            "upstream_tools": ["fastqc"],
            "metrics": [
                {
                    "metric_name": "min_per_base_quality",
                    "observed_value": aggregate_metrics["min_per_base_quality"],
                    "source_artifact": metrics_source,
                },
                {
                    "metric_name": "total_reads_millions",
                    "observed_value": aggregate_metrics["total_reads_millions"],
                    "source_artifact": metrics_source,
                },
                {
                    "metric_name": "fastqc_pass_rate",
                    "observed_value": aggregate_metrics["fastqc_pass_rate"],
                    "source_artifact": metrics_source,
                },
            ],
            "notes": "Concrete FastQC metrics were extracted from the per-read FastQC report archives.",
        },
        "notes": [
            "Raw-read QC completed with FastQC and produced provenance-rich execution plus metrics artifacts.",
            "The downstream aggregated QC stage will reuse these FastQC artifacts when MultiQC runs.",
        ],
    }

    return {
        "raw_qc_bundle": raw_qc_bundle,
        "fastqc_run": run_artifact,
        "fastqc_metrics": metrics_artifact,
    }


def aggregate_qc(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    raw_qc_bundle = inputs["raw_qc_bundle"] if isinstance(inputs["raw_qc_bundle"], Mapping) else {}
    fastqc_run_ref = _require_artifact_ref(
        raw_qc_bundle.get("fastqc_run_artifact"),
        artifact_type="fastqc_run",
        field_name="raw_qc_bundle.fastqc_run_artifact",
    )
    fastqc_metrics_ref = _require_artifact_ref(
        raw_qc_bundle.get("fastqc_metrics_artifact"),
        artifact_type="fastqc_metrics",
        field_name="raw_qc_bundle.fastqc_metrics_artifact",
    )
    fastqc_run = _load_fastqc_run_document(context, fastqc_run_ref["path"])
    fastqc_metrics = _load_fastqc_metrics_document(context, fastqc_metrics_ref["path"])

    executable, extra_args = _multiqc_config(manifest)
    multiqc_output_dir = _generated_subdir_relative_path(context, step="aggregated_qc", name="multiqc")
    multiqc_output_dir_relpath = _join_run_relative(context, multiqc_output_dir)
    multiqc_output_dir_abs = context.base_dir / multiqc_output_dir_relpath
    multiqc_output_dir_abs.mkdir(parents=True, exist_ok=True)

    command_result = run_multiqc(
        executable=executable,
        input_paths=[fastqc_run.output_directory],
        output_dir=multiqc_output_dir_relpath,
        report_filename="multiqc_report.html",
        extra_args=extra_args,
        base_dir=context.base_dir,
    )

    stdout_relpath = _write_generated_text(
        context,
        step="aggregated_qc",
        filename="multiqc.stdout.txt",
        content=command_result.stdout,
    )
    stderr_relpath = _write_generated_text(
        context,
        step="aggregated_qc",
        filename="multiqc.stderr.txt",
        content=command_result.stderr,
    )

    report_summary = inspect_multiqc_report(context.base_dir, multiqc_output_dir_relpath)
    sample_metrics = _build_multiqc_sample_metrics(fastqc_metrics, report_summary.sample_names)
    aggregate_metrics = _build_multiqc_aggregate_metrics(fastqc_metrics, report_summary, sample_metrics)

    multiqc_run_ref = _artifact_ref(
        "multiqc_run",
        _generated_output_path(context, "multiqc_run.json", step="aggregated_qc"),
        run_id=context.run_id,
    )
    multiqc_metrics_ref = _artifact_ref(
        "multiqc_metrics",
        _generated_output_path(context, "multiqc_metrics.json", step="aggregated_qc"),
        run_id=context.run_id,
    )
    report_html_ref = _artifact_ref(
        "multiqc_html_report",
        command_result.report_html_path,
        run_id=context.run_id,
    )
    data_dir_ref = (
        _artifact_ref("multiqc_data_directory", command_result.data_directory_path, run_id=context.run_id)
        if command_result.data_directory_path is not None
        else None
    )
    summary_data_ref = (
        _artifact_ref("multiqc_summary_data", report_summary.summary_data_path, run_id=context.run_id)
        if report_summary.summary_data_path is not None
        else None
    )
    stdout_ref = _artifact_ref("multiqc_stdout", stdout_relpath, run_id=context.run_id)
    stderr_ref = _artifact_ref("multiqc_stderr", stderr_relpath, run_id=context.run_id)

    generated_artifacts = _dedupe_artifacts(
        [
            multiqc_run_ref,
            multiqc_metrics_ref,
            report_html_ref,
            stdout_ref,
            stderr_ref,
            *([data_dir_ref] if data_dir_ref is not None else []),
            *([summary_data_ref] if summary_data_ref is not None else []),
        ]
    )
    metrics_related_artifacts = _dedupe_artifacts(
        [
            multiqc_run_ref,
            report_html_ref,
            *([data_dir_ref] if data_dir_ref is not None else []),
            *([summary_data_ref] if summary_data_ref is not None else []),
            fastqc_run_ref,
            fastqc_metrics_ref,
        ]
    )
    run_related_artifacts = _dedupe_artifacts(
        [
            multiqc_metrics_ref,
            report_html_ref,
            stdout_ref,
            stderr_ref,
            *([data_dir_ref] if data_dir_ref is not None else []),
            *([summary_data_ref] if summary_data_ref is not None else []),
            fastqc_run_ref,
            fastqc_metrics_ref,
        ]
    )

    metrics_artifact = {
        "tool_version": command_result.tool_version,
        "sample_sheet_path": manifest.sample_sheet_path,
        "run_artifact": multiqc_run_ref,
        "upstream_fastqc_run": fastqc_run_ref,
        "upstream_fastqc_metrics": fastqc_metrics_ref,
        "report_html": report_html_ref,
        "report_data_directory": data_dir_ref,
        "report_summary_data": summary_data_ref,
        "sample_names": list(report_summary.sample_names),
        "report_modules": list(aggregate_metrics["report_modules"]),
        "related_artifacts": metrics_related_artifacts,
        "sample_metrics": sample_metrics,
        "aggregate_metrics": aggregate_metrics,
    }
    run_artifact = {
        "tool_version": command_result.tool_version,
        "sample_sheet_path": manifest.sample_sheet_path,
        "output_directory": multiqc_output_dir_relpath,
        "input_directories": [fastqc_run.output_directory],
        "command": list(command_result.command),
        "parameters": {
            "extra_args": list(extra_args),
            "input_count": 1,
            "report_filename": "multiqc_report.html",
        },
        "upstream_fastqc_run": fastqc_run_ref,
        "upstream_fastqc_metrics": fastqc_metrics_ref,
        "report_html": report_html_ref,
        "report_data_directory": data_dir_ref,
        "report_summary_data": summary_data_ref,
        "stdout_path": stdout_relpath,
        "stderr_path": stderr_relpath,
        "metrics_artifact": multiqc_metrics_ref,
        "related_artifacts": run_related_artifacts,
    }
    metrics_source = {
        "artifact_type": "multiqc_metrics",
        "path": multiqc_metrics_ref["path"],
        "run_id": context.run_id,
    }
    summary_metrics = [
        {
            "stage": "aggregated_qc",
            "metric_name": "fastqc_pass_rate",
            "value": aggregate_metrics["fastqc_pass_rate"],
            "source_artifact": metrics_source,
        },
        {
            "stage": "aggregated_qc",
            "metric_name": "total_reads_millions",
            "value": aggregate_metrics["total_reads_millions"],
            "source_artifact": metrics_source,
        },
        {
            "stage": "aggregated_qc",
            "metric_name": "min_per_base_quality",
            "value": aggregate_metrics["min_per_base_quality"],
            "source_artifact": metrics_source,
        },
        {
            "stage": "aggregated_qc",
            "metric_name": "report_sample_count",
            "value": aggregate_metrics["report_sample_count"],
            "source_artifact": metrics_source,
        },
    ]

    return {
        "aggregated_qc_bundle": {
            "stage": "aggregated_qc",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "assay_type": manifest.assay_type,
            "upstream_stage": "raw_qc",
            "source_fastqc_run_artifact": fastqc_run_ref,
            "source_fastqc_metrics_artifact": fastqc_metrics_ref,
            "multiqc_run_artifact": multiqc_run_ref,
            "multiqc_metrics_artifact": multiqc_metrics_ref,
            "generated_artifacts": generated_artifacts,
            "aggregate_metrics": aggregate_metrics,
            "summary_metrics": summary_metrics,
            "qc_evidence": {
                "upstream_tools": ["fastqc", "multiqc"],
                "metrics": [
                    {
                        "metric_name": item["metric_name"],
                        "observed_value": item["value"],
                        "source_artifact": item["source_artifact"],
                    }
                    for item in summary_metrics
                ],
                "notes": (
                    "MultiQC aggregated the persisted FastQC outputs and copied the key normalized summary "
                    "metrics into a durable machine-readable artifact for workflow gating and inspection."
                ),
            },
            "notes": [
                "Aggregated QC completed with MultiQC using the upstream FastQC report directory instead of rerunning raw QC.",
                "The normalized MultiQC metrics artifact retains the gating metrics plus report-level module and sample metadata when the generated report data exposes it.",
            ],
        }
        ,
        "multiqc_run": run_artifact,
        "multiqc_metrics": metrics_artifact,
    }


def plan_quantification(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    if manifest.sample_sheet_path is None:
        raise ValueError("RNA-seq quantification stage requires dataset_manifest.sample_sheet_path.")

    condition_field = str(inputs["condition_field"]).strip()
    baseline_condition = str(inputs["baseline_condition"]).strip()
    comparison_condition = str(inputs["comparison_condition"]).strip()
    _, sample_rows = _load_sample_sheet_records(context, manifest.sample_sheet_path)
    multiqc_run_ref = _require_artifact_ref(
        inputs["aggregated_qc_bundle"].get("multiqc_run_artifact"),
        artifact_type="multiqc_run",
        field_name="aggregated_qc_bundle.multiqc_run_artifact",
    )
    multiqc_metrics_ref = _require_artifact_ref(
        inputs["aggregated_qc_bundle"].get("multiqc_metrics_artifact"),
        artifact_type="multiqc_metrics",
        field_name="aggregated_qc_bundle.multiqc_metrics_artifact",
    )

    count_matrix_rows = _simulate_count_matrix_rows(
        sample_rows,
        condition_field=condition_field,
        baseline_condition=baseline_condition,
        comparison_condition=comparison_condition,
        batch_fields=manifest.design.batch_fields or [],
    )
    sample_ids = [str(row["sample_id"]).strip() for row in sample_rows]
    gene_ids = [str(row["gene_id"]) for row in count_matrix_rows]
    library_sizes = _compute_library_sizes(count_matrix_rows, sample_ids)
    count_matrix_relpath = _write_count_matrix_tsv(
        context,
        sample_ids=sample_ids,
        rows=count_matrix_rows,
        filename="gene_counts.tsv",
    )

    count_matrix_ref = _artifact_ref(
        "count_matrix",
        _generated_output_path(context, "count_matrix.json", step="quantification"),
        run_id=context.run_id,
    )
    generated_artifacts = _dedupe_artifacts(
        [
            count_matrix_ref,
            _artifact_ref("count_matrix_tsv", count_matrix_relpath, run_id=context.run_id),
            multiqc_run_ref,
            multiqc_metrics_ref,
        ]
    )
    summary_metrics = [
        {
            "stage": "quantification",
            "metric_name": "sample_count",
            "value": len(sample_ids),
            "source_artifact": count_matrix_ref,
        },
        {
            "stage": "quantification",
            "metric_name": "gene_count",
            "value": len(gene_ids),
            "source_artifact": count_matrix_ref,
        },
    ]

    return {
        "quantification_bundle": {
            "stage": "quantification",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "condition_field": condition_field,
            "baseline_condition": baseline_condition,
            "comparison_condition": comparison_condition,
            "count_matrix_artifact": count_matrix_ref,
            "count_matrix_path": count_matrix_relpath,
            "sample_ids": sample_ids,
            "gene_ids": gene_ids,
            "library_sizes": library_sizes,
            "generated_artifacts": generated_artifacts,
            "summary_metrics": summary_metrics,
            "notes": [
                "This stage now materializes a deterministic count matrix so downstream DE integration can consume a concrete file-first input.",
                "The generated counts are synthetic and contrast-aware; the run artifacts record the exact engine and assumptions used.",
            ],
        },
        "count_matrix": {
            "engine_name": _QUANTIFICATION_ENGINE,
            "engine_version": _ENGINE_VERSION,
            "matrix_path": count_matrix_relpath,
            "matrix_format": "tsv",
            "sample_sheet_path": manifest.sample_sheet_path,
            "condition_field": condition_field,
            "batch_fields": list(manifest.design.batch_fields or []),
            "sample_ids": sample_ids,
            "gene_ids": gene_ids,
            "library_sizes": library_sizes,
            "upstream_multiqc_run": multiqc_run_ref,
            "upstream_multiqc_metrics": multiqc_metrics_ref,
            "related_artifacts": [multiqc_run_ref, multiqc_metrics_ref],
        },
    }


def plan_differential_expression(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    baseline_condition = str(inputs["baseline_condition"]).strip()
    comparison_condition = str(inputs["comparison_condition"]).strip()
    if manifest.sample_sheet_path is None:
        raise ValueError("RNA-seq differential expression stage requires dataset_manifest.sample_sheet_path.")

    condition_field = str(inputs["condition_field"]).strip()
    quantification_bundle = inputs["quantification_bundle"] if isinstance(inputs["quantification_bundle"], Mapping) else {}
    count_matrix_ref = _require_artifact_ref(
        quantification_bundle.get("count_matrix_artifact"),
        artifact_type="count_matrix",
        field_name="quantification_bundle.count_matrix_artifact",
    )
    count_matrix = _load_count_matrix_document(context, count_matrix_ref["path"])
    _, sample_rows = _load_sample_sheet_records(context, manifest.sample_sheet_path)
    design = _build_differential_expression_design(
        manifest,
        sample_rows,
        condition_field=condition_field,
        baseline_condition=baseline_condition,
        comparison_condition=comparison_condition,
    )
    contrast = {
        "contrast_label": _contrast_slug(comparison_condition, baseline_condition),
        "condition_field": condition_field,
        "baseline_condition": baseline_condition,
        "comparison_condition": comparison_condition,
    }
    count_rows = _load_count_matrix_rows(context, count_matrix)
    sample_index = _sample_rows_by_id(sample_rows)
    selected_samples = [
        sample_id
        for sample_id in count_matrix.sample_ids
        if sample_index.get(sample_id, {}).get(condition_field) in {baseline_condition, comparison_condition}
    ]
    if not selected_samples:
        raise ValueError(
            "Differential expression stage did not find any samples matching the requested baseline/comparison conditions."
        )

    size_factors = _library_size_factors(count_matrix.library_sizes, selected_samples)
    normalized_rows = _normalize_count_matrix(count_rows, selected_samples, size_factors)
    adjusted_rows = _apply_batch_mean_centering(
        normalized_rows,
        sample_index,
        batch_fields=design["batch_fields_modeled"],
    )
    result_rows = _summarize_differential_expression(
        adjusted_rows,
        sample_index,
        condition_field=condition_field,
        baseline_condition=baseline_condition,
        comparison_condition=comparison_condition,
    )
    if not result_rows:
        raise ValueError("Differential expression stage did not produce any gene-level results.")

    adjusted_p_values = _benjamini_hochberg([float(item["p_value"]) for item in result_rows])
    for row, adjusted_p_value in zip(result_rows, adjusted_p_values, strict=True):
        row["adjusted_p_value"] = adjusted_p_value
        row["is_significant"] = (
            adjusted_p_value <= _DE_SIGNIFICANCE_THRESHOLD
            and abs(float(row["log2_fold_change"])) >= _DE_LOG2_EFFECT_FLOOR
        )

    result_rows.sort(key=lambda item: (float(item["adjusted_p_value"]), -abs(float(item["log2_fold_change"]))))
    contrast_slug = contrast["contrast_label"]
    normalized_counts_relpath = _write_normalized_count_matrix_tsv(
        context,
        sample_ids=selected_samples,
        rows=normalized_rows,
        filename=f"{contrast_slug}.normalized_counts.tsv",
    )
    results_relpath = _write_differential_expression_results_tsv(
        context,
        rows=result_rows,
        filename=f"{contrast_slug}.tsv",
    )
    volcano_plot_relpath = _write_generated_text(
        context,
        step="differential_expression",
        filename=f"{contrast_slug}.volcano.svg",
        content=_render_volcano_plot_svg(result_rows),
    )
    ma_plot_relpath = _write_generated_text(
        context,
        step="differential_expression",
        filename=f"{contrast_slug}.mean-difference.svg",
        content=_render_mean_difference_plot_svg(result_rows),
    )

    normalized_count_matrix_ref = _artifact_ref(
        "normalized_count_matrix",
        _generated_output_path(context, "normalized_count_matrix.json", step="differential_expression"),
        run_id=context.run_id,
    )
    results_artifact_ref = _artifact_ref(
        "differential_expression_results",
        _generated_output_path(context, "differential_expression_results.json", step="differential_expression"),
        run_id=context.run_id,
    )
    run_artifact_ref = _artifact_ref(
        "differential_expression_run",
        _generated_output_path(context, "differential_expression_run.json", step="differential_expression"),
        run_id=context.run_id,
    )
    volcano_plot_ref = _artifact_ref("volcano_plot", volcano_plot_relpath, run_id=context.run_id)
    ma_plot_ref = _artifact_ref("mean_difference_plot", ma_plot_relpath, run_id=context.run_id)
    warnings = _differential_expression_warnings(design)
    summary = _differential_expression_summary(result_rows)
    generated_artifacts = _dedupe_artifacts(
        [
            normalized_count_matrix_ref,
            results_artifact_ref,
            run_artifact_ref,
            _artifact_ref("normalized_count_matrix_tsv", normalized_counts_relpath, run_id=context.run_id),
            _artifact_ref("differential_expression_results_tsv", results_relpath, run_id=context.run_id),
            volcano_plot_ref,
            ma_plot_ref,
            count_matrix_ref,
        ]
    )
    results_source = {
        "artifact_type": "differential_expression_results",
        "path": results_artifact_ref["path"],
        "run_id": context.run_id,
    }
    run_source = {
        "artifact_type": "differential_expression_run",
        "path": run_artifact_ref["path"],
        "run_id": context.run_id,
    }
    summary_metrics = [
        {
            "stage": "differential_expression",
            "metric_name": "tested_gene_count",
            "value": summary["tested_gene_count"],
            "source_artifact": results_source,
        },
        {
            "stage": "differential_expression",
            "metric_name": "significant_gene_count",
            "value": summary["significant_gene_count"],
            "source_artifact": results_source,
        },
        {
            "stage": "differential_expression",
            "metric_name": "minimum_condition_replicates",
            "value": design["minimum_condition_replicates"],
            "source_artifact": run_source,
        },
        {
            "stage": "differential_expression",
            "metric_name": "missing_expected_batch_fields",
            "value": len(design["missing_batch_fields"]),
            "source_artifact": run_source,
        },
    ]

    return {
        "differential_expression_bundle": {
            "stage": "differential_expression",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "engine": {
                "engine_name": _DIFFERENTIAL_EXPRESSION_ENGINE,
                "engine_version": _ENGINE_VERSION,
                "parameters": {
                    "significance_threshold": _DE_SIGNIFICANCE_THRESHOLD,
                    "log2_effect_floor": _DE_LOG2_EFFECT_FLOOR,
                    "normalization_method": "median_library_size",
                    "batch_adjustment_method": (
                        "mean_center_by_batch" if design["batch_fields_modeled"] else "none"
                    ),
                },
            },
            "contrast": contrast,
            "design": design,
            "count_matrix_artifact": count_matrix_ref,
            "normalized_count_matrix_artifact": normalized_count_matrix_ref,
            "differential_expression_results_artifact": results_artifact_ref,
            "differential_expression_run_artifact": run_artifact_ref,
            "results_path": results_relpath,
            "normalized_counts_path": normalized_counts_relpath,
            "diagnostic_plots": [volcano_plot_ref, ma_plot_ref],
            "summary": summary,
            "warnings": warnings,
            "generated_artifacts": generated_artifacts,
            "summary_metrics": summary_metrics,
            "qc_evidence": {
                "upstream_tools": [_QUANTIFICATION_ENGINE, _DIFFERENTIAL_EXPRESSION_ENGINE],
                "metrics": [
                    {
                        "metric_name": item["metric_name"],
                        "observed_value": item["value"],
                        "source_artifact": item["source_artifact"],
                    }
                    for item in summary_metrics
                ],
                "notes": (
                    "Differential expression used a deterministic mean-centered t-test over the materialized "
                    "count matrix. Batch expectations, replicate counts, and engine parameters are recorded "
                    "explicitly so design concerns do not look like opaque tool failures."
                ),
            },
            "notes": [
                "This stage materializes normalized counts, a DE results table, and diagnostic plots instead of returning a placeholder bundle.",
                "The engine is intentionally transparent and deterministic; it is not presented as DESeq2.",
            ],
        },
        "normalized_count_matrix": {
            "engine_name": _DIFFERENTIAL_EXPRESSION_ENGINE,
            "engine_version": _ENGINE_VERSION,
            "normalization_method": "median_library_size",
            "matrix_path": normalized_counts_relpath,
            "matrix_format": "tsv",
            "sample_ids": selected_samples,
            "gene_count": len(normalized_rows),
            "library_size_factors": size_factors,
            "source_count_matrix": count_matrix_ref,
            "related_artifacts": [count_matrix_ref],
        },
        "differential_expression_results": {
            "engine_name": _DIFFERENTIAL_EXPRESSION_ENGINE,
            "engine_version": _ENGINE_VERSION,
            "design": design,
            "contrast": contrast,
            "source_count_matrix": count_matrix_ref,
            "normalized_count_matrix": normalized_count_matrix_ref,
            "results_path": results_relpath,
            "result_format": "tsv",
            "tested_gene_count": summary["tested_gene_count"],
            "significant_gene_count": summary["significant_gene_count"],
            "significance_threshold": _DE_SIGNIFICANCE_THRESHOLD,
            "diagnostic_plots": [volcano_plot_ref, ma_plot_ref],
            "warnings": warnings,
            "related_artifacts": [count_matrix_ref, normalized_count_matrix_ref, volcano_plot_ref, ma_plot_ref],
        },
        "differential_expression_run": {
            "engine_name": _DIFFERENTIAL_EXPRESSION_ENGINE,
            "engine_version": _ENGINE_VERSION,
            "design": design,
            "contrast": contrast,
            "parameters": {
                "significance_threshold": _DE_SIGNIFICANCE_THRESHOLD,
                "log2_effect_floor": _DE_LOG2_EFFECT_FLOOR,
                "normalization_method": "median_library_size",
            },
            "batch_adjustment_method": "mean_center_by_batch" if design["batch_fields_modeled"] else "none",
            "source_count_matrix": count_matrix_ref,
            "normalized_count_matrix": normalized_count_matrix_ref,
            "results_artifact": results_artifact_ref,
            "diagnostic_plots": [volcano_plot_ref, ma_plot_ref],
            "summary": summary,
            "warnings": warnings,
            "related_artifacts": [count_matrix_ref, normalized_count_matrix_ref, results_artifact_ref, volcano_plot_ref, ma_plot_ref],
        },
    }


def build_report_bundle(inputs, context):
    manifest_path = str(inputs["dataset_manifest"])
    manifest = _load_manifest(context, manifest_path)
    workflow_run = _load_workflow_run_document(context)
    return _build_rnaseq_report_bundle_outputs(
        context=context,
        manifest_path=manifest_path,
        manifest=manifest,
        workflow_run=workflow_run,
        raw_qc_bundle=_mapping_or_empty(inputs.get("raw_qc_bundle")),
        aggregated_qc_bundle=_mapping_or_empty(inputs.get("aggregated_qc_bundle")),
        quantification_bundle=_mapping_or_empty(inputs.get("quantification_bundle")),
        differential_expression_bundle=_mapping_or_empty(inputs.get("differential_expression_bundle")),
        condition_field=str(inputs["condition_field"]).strip(),
        baseline_condition=str(inputs["baseline_condition"]).strip(),
        comparison_condition=str(inputs["comparison_condition"]).strip(),
        report_lifecycle_status="completed",
    )


def materialize_terminal_report_bundle(inputs, context):
    workflow_run = _load_workflow_run_document(context)
    manifest_path = inputs.get("dataset_manifest")
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        manifest_path = ""

    manifest: DatasetManifest | None
    manifest_load_error: str | None = None
    if manifest_path:
        try:
            manifest = _load_manifest(context, manifest_path)
        except Exception as exc:
            manifest = None
            manifest_load_error = str(exc) or exc.__class__.__name__
    else:
        manifest = None
        manifest_load_error = "dataset_manifest input was unavailable during terminal report-bundle materialization."

    return _build_rnaseq_report_bundle_outputs(
        context=context,
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_load_error=manifest_load_error,
        workflow_run=workflow_run,
        raw_qc_bundle=_mapping_or_empty(inputs.get("raw_qc_bundle")),
        aggregated_qc_bundle=_mapping_or_empty(inputs.get("aggregated_qc_bundle")),
        quantification_bundle=_mapping_or_empty(inputs.get("quantification_bundle")),
        differential_expression_bundle=_mapping_or_empty(inputs.get("differential_expression_bundle")),
        condition_field=_optional_string(inputs.get("condition_field")),
        baseline_condition=_optional_string(inputs.get("baseline_condition")),
        comparison_condition=_optional_string(inputs.get("comparison_condition")),
        report_lifecycle_status=workflow_run.lifecycle_status,
    )


def _load_sample_sheet_records(context, sample_sheet_path: str) -> tuple[list[str], list[dict[str, str]]]:
    sample_sheet_abs = context.resolve_path(sample_sheet_path)
    if not sample_sheet_abs.exists():
        raise ValueError(f"RNA-seq sample sheet {sample_sheet_path!r} does not exist.")

    delimiter = "\t" if sample_sheet_abs.suffix.lower() in {".tsv", ".txt"} else ","
    with sample_sheet_abs.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fieldnames = [_normalize_sample_sheet_header(item) for item in (reader.fieldnames or [])]
        normalized_rows = [
            {
                _normalize_sample_sheet_header(key): (value.strip() if isinstance(value, str) else "")
                for key, value in row.items()
            }
            for row in reader
        ]

    rows = [row for row in normalized_rows if not _row_is_empty(row)]
    if not rows:
        raise ValueError("RNA-seq sample sheet must contain at least one non-empty data row.")
    return fieldnames, rows


def _normalize_sample_sheet_header(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _row_is_empty(row: Mapping[str, Any]) -> bool:
    return all(not str(value).strip() for value in row.values())


def _simulate_count_matrix_rows(
    sample_rows: Sequence[Mapping[str, str]],
    *,
    condition_field: str,
    baseline_condition: str,
    comparison_condition: str,
    batch_fields: Sequence[str],
) -> list[dict[str, Any]]:
    primary_batch_field = batch_fields[0] if batch_fields else None
    rows: list[dict[str, Any]] = []
    for gene_index, gene in enumerate(_DE_GENE_PANEL):
        counts: dict[str, int] = {}
        for sample_index, sample in enumerate(sample_rows):
            sample_id = str(sample.get("sample_id", "")).strip()
            if not sample_id:
                raise ValueError("RNA-seq sample sheet requires non-empty sample_id values.")
            condition_value = str(sample.get(condition_field, "")).strip()
            if not condition_value:
                raise ValueError(
                    f"RNA-seq sample sheet requires non-empty values for condition field {condition_field!r}."
                )

            if condition_value == baseline_condition:
                condition_weight = 0.0
            elif condition_value == comparison_condition:
                condition_weight = 1.0
            else:
                condition_weight = 0.5

            batch_value = (
                str(sample.get(primary_batch_field, "")).strip() if primary_batch_field is not None else ""
            )
            batch_offset = _string_weight(batch_value) * int(gene["batch_weight"])
            sample_offset = ((sample_index % 3) - 1) * 55 + (gene_index % 4) * 12
            simulated = int(
                round(
                    int(gene["baseline_count"])
                    + condition_weight * int(gene["contrast_delta"])
                    + batch_offset
                    + sample_offset
                )
            )
            counts[sample_id] = max(simulated, 20)

        rows.append(
            {
                "gene_id": gene["gene_id"],
                "gene_symbol": gene["gene_symbol"],
                "counts": counts,
            }
        )
    return rows


def _string_weight(value: str) -> int:
    if not value:
        return 0
    return (sum(ord(char) for char in value) % 3) - 1


def _compute_library_sizes(
    count_rows: Sequence[Mapping[str, Any]],
    sample_ids: Sequence[str],
) -> dict[str, int]:
    library_sizes = {sample_id: 0 for sample_id in sample_ids}
    for row in count_rows:
        counts = row.get("counts")
        if not isinstance(counts, Mapping):
            continue
        for sample_id in sample_ids:
            library_sizes[sample_id] += int(counts.get(sample_id, 0))
    return library_sizes


def _write_count_matrix_tsv(
    context,
    *,
    sample_ids: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    filename: str,
) -> str:
    headers = ["gene_id", "gene_symbol", *sample_ids]
    lines = ["\t".join(headers)]
    for row in rows:
        counts = row.get("counts")
        if not isinstance(counts, Mapping):
            raise ValueError("Count matrix rows must include a counts mapping.")
        values = [str(row["gene_id"]), str(row["gene_symbol"])]
        values.extend(str(int(counts.get(sample_id, 0))) for sample_id in sample_ids)
        lines.append("\t".join(values))
    return _write_generated_text(context, step="quantification", filename=filename, content="\n".join(lines))


def _load_count_matrix_document(context, artifact_path: str) -> CountMatrix:
    document = load_artifact_document(context.base_dir / artifact_path)
    if not isinstance(document, CountMatrix):
        raise ValueError(f"Expected count_matrix artifact at {artifact_path!r}.")
    return document


def _load_count_matrix_rows(context, count_matrix: CountMatrix) -> list[dict[str, Any]]:
    matrix_path = context.base_dir / count_matrix.matrix_path
    if not matrix_path.exists():
        raise ValueError(f"Count matrix file {count_matrix.matrix_path!r} does not exist.")

    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows: list[dict[str, Any]] = []
        for raw_row in reader:
            counts = {
                sample_id: int(str(raw_row.get(sample_id, "0") or "0"))
                for sample_id in count_matrix.sample_ids
            }
            rows.append(
                {
                    "gene_id": str(raw_row.get("gene_id", "")).strip(),
                    "gene_symbol": str(raw_row.get("gene_symbol", "")).strip(),
                    "counts": counts,
                }
            )
    return rows


def _sample_rows_by_id(sample_rows: Sequence[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for row in sample_rows:
        sample_id = str(row.get("sample_id", "")).strip()
        if not sample_id:
            continue
        records[sample_id] = {str(key): str(value) for key, value in row.items()}
    return records


def _build_differential_expression_design(
    manifest: DatasetManifest,
    sample_rows: Sequence[Mapping[str, str]],
    *,
    condition_field: str,
    baseline_condition: str,
    comparison_condition: str,
) -> dict[str, Any]:
    sample_index = _sample_rows_by_id(sample_rows)
    if not sample_index:
        raise ValueError("Differential expression design requires at least one sample row.")

    available_fields = {key for row in sample_rows for key in row.keys()}
    if condition_field not in available_fields:
        raise ValueError(
            f"Differential expression design requires condition field {condition_field!r} in the sample sheet."
        )

    relevant_sample_ids = [
        sample_id
        for sample_id, row in sample_index.items()
        if row.get(condition_field) in {baseline_condition, comparison_condition}
    ]
    if not relevant_sample_ids:
        raise ValueError(
            "Differential expression design requires at least one sample for the requested contrast."
        )

    replicate_counts = {
        baseline_condition: sum(
            1 for sample_id in relevant_sample_ids if sample_index[sample_id].get(condition_field) == baseline_condition
        ),
        comparison_condition: sum(
            1
            for sample_id in relevant_sample_ids
            if sample_index[sample_id].get(condition_field) == comparison_condition
        ),
    }
    if 0 in replicate_counts.values():
        raise ValueError(
            "Differential expression design requires at least one sample in both the baseline and comparison conditions."
        )

    expected_batch_fields = list(manifest.design.batch_fields or [])
    missing_batch_fields = [
        field
        for field in expected_batch_fields
        if field not in available_fields
        or any(not str(sample_index[sample_id].get(field, "")).strip() for sample_id in relevant_sample_ids)
    ]
    batch_fields_modeled = [field for field in expected_batch_fields if field not in missing_batch_fields]
    modeled_factors = [*batch_fields_modeled, condition_field]
    design_formula = "~ " + " + ".join(modeled_factors)

    return {
        "design_formula": design_formula,
        "modeled_factors": modeled_factors,
        "batch_fields_expected": expected_batch_fields,
        "batch_fields_modeled": batch_fields_modeled,
        "missing_batch_fields": missing_batch_fields,
        "replicate_counts": replicate_counts,
        "minimum_condition_replicates": min(replicate_counts.values()),
    }


def _library_size_factors(
    library_sizes: Mapping[str, int],
    sample_ids: Sequence[str],
) -> dict[str, float]:
    selected_sizes = [int(library_sizes[sample_id]) for sample_id in sample_ids]
    median_size = _median(selected_sizes)
    if median_size <= 0:
        raise ValueError("Count matrix library sizes must be positive before normalization.")
    return {
        sample_id: round(int(library_sizes[sample_id]) / median_size, 6)
        for sample_id in sample_ids
    }


def _normalize_count_matrix(
    count_rows: Sequence[Mapping[str, Any]],
    sample_ids: Sequence[str],
    size_factors: Mapping[str, float],
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in count_rows:
        counts = row.get("counts")
        if not isinstance(counts, Mapping):
            raise ValueError("Count matrix rows must include a counts mapping.")
        normalized_counts = {
            sample_id: round(int(counts[sample_id]) / float(size_factors[sample_id]), 6)
            for sample_id in sample_ids
        }
        normalized_rows.append(
            {
                "gene_id": row["gene_id"],
                "gene_symbol": row["gene_symbol"],
                "normalized_counts": normalized_counts,
            }
        )
    return normalized_rows


def _apply_batch_mean_centering(
    normalized_rows: Sequence[Mapping[str, Any]],
    sample_index: Mapping[str, Mapping[str, str]],
    *,
    batch_fields: Sequence[str],
) -> list[dict[str, Any]]:
    if not batch_fields:
        return [
            {
                "gene_id": row["gene_id"],
                "gene_symbol": row["gene_symbol"],
                "normalized_counts": dict(row["normalized_counts"]),
                "adjusted_counts": dict(row["normalized_counts"]),
            }
            for row in normalized_rows
        ]

    adjusted_rows: list[dict[str, Any]] = []
    for row in normalized_rows:
        normalized_counts = row["normalized_counts"]
        global_mean = _mean(normalized_counts.values())
        batch_means: dict[tuple[str, ...], float] = {}
        batch_members: dict[tuple[str, ...], list[str]] = {}
        for sample_id in normalized_counts:
            batch_key = tuple(str(sample_index[sample_id].get(field, "")).strip() for field in batch_fields)
            batch_members.setdefault(batch_key, []).append(sample_id)
        for batch_key, sample_ids in batch_members.items():
            batch_means[batch_key] = _mean(normalized_counts[sample_id] for sample_id in sample_ids)

        adjusted_counts = {}
        for sample_id, value in normalized_counts.items():
            batch_key = tuple(str(sample_index[sample_id].get(field, "")).strip() for field in batch_fields)
            adjusted_counts[sample_id] = round(value - batch_means[batch_key] + global_mean, 6)

        adjusted_rows.append(
            {
                "gene_id": row["gene_id"],
                "gene_symbol": row["gene_symbol"],
                "normalized_counts": dict(normalized_counts),
                "adjusted_counts": adjusted_counts,
            }
        )
    return adjusted_rows


def _summarize_differential_expression(
    adjusted_rows: Sequence[Mapping[str, Any]],
    sample_index: Mapping[str, Mapping[str, str]],
    *,
    condition_field: str,
    baseline_condition: str,
    comparison_condition: str,
) -> list[dict[str, Any]]:
    result_rows: list[dict[str, Any]] = []
    for row in adjusted_rows:
        adjusted_counts = row["adjusted_counts"]
        normalized_counts = row["normalized_counts"]
        baseline_values = [
            float(adjusted_counts[sample_id])
            for sample_id in adjusted_counts
            if sample_index.get(sample_id, {}).get(condition_field) == baseline_condition
        ]
        comparison_values = [
            float(adjusted_counts[sample_id])
            for sample_id in adjusted_counts
            if sample_index.get(sample_id, {}).get(condition_field) == comparison_condition
        ]
        if not baseline_values or not comparison_values:
            continue

        baseline_mean = _mean(baseline_values)
        comparison_mean = _mean(comparison_values)
        log2_fold_change = math.log2((comparison_mean + 1.0) / (baseline_mean + 1.0))
        standard_error = math.sqrt(
            (_sample_variance(baseline_values) / max(len(baseline_values), 1))
            + (_sample_variance(comparison_values) / max(len(comparison_values), 1))
        )
        if standard_error <= 0:
            z_score = 0.0 if abs(comparison_mean - baseline_mean) < 1e-9 else 12.0
        else:
            z_score = abs(comparison_mean - baseline_mean) / standard_error
        p_value = min(max(math.erfc(z_score / math.sqrt(2.0)), 1e-12), 1.0)

        result_rows.append(
            {
                "gene_id": row["gene_id"],
                "gene_symbol": row["gene_symbol"],
                "baseline_mean": round(_mean(
                    normalized_counts[sample_id]
                    for sample_id in normalized_counts
                    if sample_index.get(sample_id, {}).get(condition_field) == baseline_condition
                ), 6),
                "comparison_mean": round(_mean(
                    normalized_counts[sample_id]
                    for sample_id in normalized_counts
                    if sample_index.get(sample_id, {}).get(condition_field) == comparison_condition
                ), 6),
                "log2_fold_change": round(log2_fold_change, 6),
                "p_value": round(p_value, 12),
                "baseline_replicates": len(baseline_values),
                "comparison_replicates": len(comparison_values),
            }
        )
    return result_rows


def _benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    if not p_values:
        return []
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running_min = 1.0
    total = len(p_values)
    for rank, (original_index, p_value) in enumerate(reversed(indexed), start=1):
        adjusted_value = min(1.0, p_value * total / (total - rank + 1))
        running_min = min(running_min, adjusted_value)
        adjusted[original_index] = round(running_min, 12)
    return adjusted


def _write_normalized_count_matrix_tsv(
    context,
    *,
    sample_ids: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    filename: str,
) -> str:
    headers = ["gene_id", "gene_symbol", *sample_ids]
    lines = ["\t".join(headers)]
    for row in rows:
        normalized_counts = row["normalized_counts"]
        values = [str(row["gene_id"]), str(row["gene_symbol"])]
        values.extend(f"{float(normalized_counts[sample_id]):.6f}" for sample_id in sample_ids)
        lines.append("\t".join(values))
    return _write_generated_text(
        context,
        step="differential_expression",
        filename=filename,
        content="\n".join(lines),
    )


def _write_differential_expression_results_tsv(
    context,
    *,
    rows: Sequence[Mapping[str, Any]],
    filename: str,
) -> str:
    headers = [
        "gene_id",
        "gene_symbol",
        "baseline_mean",
        "comparison_mean",
        "log2_fold_change",
        "p_value",
        "adjusted_p_value",
        "is_significant",
        "baseline_replicates",
        "comparison_replicates",
    ]
    lines = ["\t".join(headers)]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    str(row["gene_id"]),
                    str(row["gene_symbol"]),
                    f"{float(row['baseline_mean']):.6f}",
                    f"{float(row['comparison_mean']):.6f}",
                    f"{float(row['log2_fold_change']):.6f}",
                    f"{float(row['p_value']):.12f}",
                    f"{float(row['adjusted_p_value']):.12f}",
                    "true" if bool(row["is_significant"]) else "false",
                    str(int(row["baseline_replicates"])),
                    str(int(row["comparison_replicates"])),
                ]
            )
        )
    return _write_generated_text(
        context,
        step="differential_expression",
        filename=filename,
        content="\n".join(lines),
    )


def _differential_expression_warnings(design: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    missing_batch_fields = [str(item) for item in design.get("missing_batch_fields", [])]
    if missing_batch_fields:
        warnings.append(
            "Expected batch variables were missing for this contrast and could not be modeled: "
            + ", ".join(missing_batch_fields)
            + "."
        )
    minimum_condition_replicates = int(design.get("minimum_condition_replicates", 0))
    if minimum_condition_replicates < 3:
        warnings.append(
            "The requested contrast has fewer than three replicates in at least one condition; interpret DE results cautiously."
        )
    return warnings


def _differential_expression_summary(result_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    significant_rows = [row for row in result_rows if bool(row.get("is_significant"))]
    upregulated = [row for row in significant_rows if float(row["log2_fold_change"]) > 0]
    downregulated = [row for row in significant_rows if float(row["log2_fold_change"]) < 0]
    top_upregulated = upregulated[0]["gene_symbol"] if upregulated else None
    top_downregulated = downregulated[0]["gene_symbol"] if downregulated else None
    max_abs_log2fc = max((abs(float(row["log2_fold_change"])) for row in result_rows), default=0.0)
    return {
        "tested_gene_count": len(result_rows),
        "significant_gene_count": len(significant_rows),
        "upregulated_gene_count": len(upregulated),
        "downregulated_gene_count": len(downregulated),
        "maximum_absolute_log2_fold_change": round(max_abs_log2fc, 6),
        "top_upregulated_gene": top_upregulated,
        "top_downregulated_gene": top_downregulated,
    }


def _render_volcano_plot_svg(result_rows: Sequence[Mapping[str, Any]]) -> str:
    points = [
        {
            "label": row["gene_symbol"],
            "x": float(row["log2_fold_change"]),
            "y": -math.log10(max(float(row["adjusted_p_value"]), 1e-12)),
            "highlight": bool(row.get("is_significant")),
        }
        for row in result_rows
    ]
    return _render_scatter_svg(
        title="Volcano Plot",
        x_label="log2 fold change",
        y_label="-log10 adjusted p-value",
        points=points,
    )


def _render_mean_difference_plot_svg(result_rows: Sequence[Mapping[str, Any]]) -> str:
    points = [
        {
            "label": row["gene_symbol"],
            "x": math.log10(max((float(row["baseline_mean"]) + float(row["comparison_mean"])) / 2.0, 1e-6)),
            "y": float(row["log2_fold_change"]),
            "highlight": bool(row.get("is_significant")),
        }
        for row in result_rows
    ]
    return _render_scatter_svg(
        title="Mean-Difference Plot",
        x_label="log10 mean normalized count",
        y_label="log2 fold change",
        points=points,
    )


def _render_scatter_svg(
    *,
    title: str,
    x_label: str,
    y_label: str,
    points: Sequence[Mapping[str, Any]],
) -> str:
    width = 720
    height = 480
    left = 70
    right = 30
    top = 40
    bottom = 70
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_values = [float(point["x"]) for point in points] or [0.0]
    y_values = [float(point["y"]) for point in points] or [0.0]
    min_x = min(x_values)
    max_x = max(x_values)
    min_y = min(y_values)
    max_y = max(y_values)
    if math.isclose(min_x, max_x):
        min_x -= 1.0
        max_x += 1.0
    if math.isclose(min_y, max_y):
        min_y -= 1.0
        max_y += 1.0

    def scale_x(value: float) -> float:
        return left + ((value - min_x) / (max_x - min_x)) * plot_width

    def scale_y(value: float) -> float:
        return top + plot_height - ((value - min_y) / (max_y - min_y)) * plot_height

    circles = []
    labels = []
    for point in points:
        x_pos = scale_x(float(point["x"]))
        y_pos = scale_y(float(point["y"]))
        fill = "#c54122" if bool(point.get("highlight")) else "#225d84"
        circles.append(f'<circle cx="{x_pos:.1f}" cy="{y_pos:.1f}" r="5" fill="{fill}" opacity="0.82" />')
        if bool(point.get("highlight")):
            labels.append(
                f'<text x="{x_pos + 7:.1f}" y="{y_pos - 7:.1f}" font-size="11" fill="#1f2933">{_svg_escape(str(point["label"]))}</text>'
            )

    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="480" viewBox="0 0 720 480">',
            '<rect width="720" height="480" fill="#f8f4ea" />',
            f'<text x="{width / 2:.0f}" y="24" text-anchor="middle" font-size="20" fill="#1f2933">{_svg_escape(title)}</text>',
            f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#384860" stroke-width="2" />',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#384860" stroke-width="2" />',
            *circles,
            *labels,
            f'<text x="{width / 2:.0f}" y="{height - 22}" text-anchor="middle" font-size="13" fill="#384860">{_svg_escape(x_label)}</text>',
            (
                f'<text x="22" y="{height / 2:.0f}" text-anchor="middle" font-size="13" '
                'fill="#384860" transform="rotate(-90 22 240)">'
                f"{_svg_escape(y_label)}</text>"
            ),
            "</svg>",
        ]
    )


def _svg_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_rnaseq_report_bundle(
    *,
    manifest: DatasetManifest | None,
    manifest_path: str,
    manifest_load_error: str | None,
    workflow_run: WorkflowRun,
    raw_qc_bundle: Mapping[str, Any],
    aggregated_qc_bundle: Mapping[str, Any],
    quantification_bundle: Mapping[str, Any],
    differential_expression_bundle: Mapping[str, Any],
    condition_field: str,
    baseline_condition: str,
    comparison_condition: str,
    run_id: str,
    workflow_version: str,
    workflow_lifecycle_status: str,
    workflow_qc_status: str,
    workflow_warnings: Sequence[str],
    workflow_run_path: str,
    report_manifest_path: str,
    provenance_exports: Sequence[str],
    canonical_artifacts_by_type: Mapping[str, Mapping[str, Any]],
    evidence_review_artifacts: Sequence[Mapping[str, Any]],
    missing_artifacts: Sequence[Mapping[str, Any]],
    deviations: Sequence[Mapping[str, Any]],
    recommendations: Sequence[str],
) -> str:
    raw_metrics = raw_qc_bundle.get("aggregate_metrics", {}) if isinstance(raw_qc_bundle, Mapping) else {}
    aggregated_metrics = (
        aggregated_qc_bundle.get("aggregate_metrics", {}) if isinstance(aggregated_qc_bundle, Mapping) else {}
    )
    de_summary = (
        differential_expression_bundle.get("summary", {})
        if isinstance(differential_expression_bundle, Mapping)
        else {}
    )
    de_design = (
        differential_expression_bundle.get("design", {})
        if isinstance(differential_expression_bundle, Mapping)
        else {}
    )
    plot_refs = differential_expression_bundle.get("diagnostic_plots", []) if isinstance(
        differential_expression_bundle,
        Mapping,
    ) else []
    plot_paths = [
        str(item.get("path"))
        for item in plot_refs
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    ]
    completed_steps = [record.id for record in workflow_run.steps if record.status == "completed"]
    blocked_or_pending_steps = [
        record.id for record in workflow_run.steps if record.status != "completed"
    ]
    study_name = manifest.design.study_name if manifest is not None else "unknown-study"
    manifest_id = manifest.id if manifest is not None else "n/a"
    assay_type = manifest.assay_type if manifest is not None else "n/a"
    sample_sheet_path = manifest.sample_sheet_path if manifest is not None else None
    canonical_count_matrix_ref = canonical_artifacts_by_type.get("count_matrix", {})
    canonical_normalized_count_matrix_ref = canonical_artifacts_by_type.get("normalized_count_matrix", {})
    canonical_de_results_ref = canonical_artifacts_by_type.get("differential_expression_results", {})
    canonical_de_run_ref = canonical_artifacts_by_type.get("differential_expression_run", {})
    evidence_review_paths = [
        str(item.get("path"))
        for item in evidence_review_artifacts
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    ]
    lines = [
        f"# RNA-seq Report Bundle for {study_name}",
        "",
        "## Executive Summary",
        f"Run `{run_id}` reached workflow lifecycle status `{workflow_lifecycle_status}` in `rnaseq_qc_de`.",
        f"Contrast: `{comparison_condition}` vs `{baseline_condition}` using condition field `{condition_field}`.",
        f"Completed stages: `{', '.join(completed_steps) if completed_steps else 'none'}`.",
        f"Remaining or blocked stages: `{', '.join(blocked_or_pending_steps) if blocked_or_pending_steps else 'none'}`.",
        "",
        "## Inputs Used",
        f"- Dataset manifest: `{manifest_id}`",
        f"- Dataset manifest path: `{manifest_path or 'n/a'}`",
        f"- Assay type: `{assay_type}`",
        f"- Sample sheet: `{sample_sheet_path or 'n/a'}`",
        "",
        "## Workflow Version",
        f"- Workflow: `rnaseq_qc_de`",
        f"- Version: `{workflow_version}`",
        "",
        "## QC Summary",
        f"- Workflow lifecycle status: `{workflow_lifecycle_status}`",
        f"- Workflow QC status: `{workflow_qc_status}`",
        f"- Raw QC FastQC pass rate: `{raw_metrics.get('fastqc_pass_rate', 'n/a')}`",
        f"- Aggregated QC MultiQC pass rate: `{aggregated_metrics.get('fastqc_pass_rate', 'n/a')}`",
        f"- Aggregated QC sample count: `{aggregated_metrics.get('report_sample_count', 'n/a')}`",
        "",
        "## Key Outputs",
        f"- Count matrix artifact: `{canonical_count_matrix_ref.get('path', 'n/a')}`",
        f"- Count matrix TSV: `{quantification_bundle.get('count_matrix_path', 'n/a')}`",
        f"- Normalized count artifact: `{canonical_normalized_count_matrix_ref.get('path', 'n/a')}`",
        f"- Normalized counts TSV: `{differential_expression_bundle.get('normalized_counts_path', 'n/a')}`",
        f"- DE results artifact: `{canonical_de_results_ref.get('path', 'n/a')}`",
        f"- DE results TSV: `{differential_expression_bundle.get('results_path', 'n/a')}`",
        f"- DE run artifact: `{canonical_de_run_ref.get('path', 'n/a')}`",
        f"- Diagnostic plots: `{', '.join(plot_paths) if plot_paths else 'n/a'}`",
        f"- Evidence review artifacts: `{', '.join(evidence_review_paths) if evidence_review_paths else 'n/a'}`",
        "",
        "## Differential Expression Summary",
        f"- Tested genes: `{de_summary.get('tested_gene_count', 'n/a')}`",
        f"- Significant genes: `{de_summary.get('significant_gene_count', 'n/a')}`",
        f"- Top upregulated gene: `{de_summary.get('top_upregulated_gene', 'n/a')}`",
        f"- Top downregulated gene: `{de_summary.get('top_downregulated_gene', 'n/a')}`",
        f"- Design formula: `{de_design.get('design_formula', 'n/a')}`",
        "",
        "## Warnings and Failures",
    ]
    if workflow_warnings:
        lines.extend(f"- {warning}" for warning in workflow_warnings)
    else:
        lines.append("- No workflow warnings or failures were recorded for this run.")
    if manifest_load_error:
        lines.append(f"- Dataset manifest could not be loaded for terminal bundle rendering: `{manifest_load_error}`")
    if missing_artifacts:
        lines.extend(
            f"- Missing artifact: `{item.get('artifact_type', 'artifact')}` expected at `{item.get('expected_path', 'n/a')}`"
            for item in missing_artifacts
        )
    else:
        lines.append("- All expected canonical workflow outputs for this report bundle were available.")
    lines.extend(["", "## Deviations"])
    if deviations:
        for item in deviations:
            step_id = str(item.get("step_id", "unknown-step"))
            step_label = str(item.get("step_label", "")).strip()
            step_display = f"`{step_id}` ({step_label})" if step_label else f"`{step_id}`"
            lines.append(
                f"- [{item.get('severity', 'minor')}/{item.get('origin', 'automatic')}] step {step_display}: "
                f"expected {item.get('original_expected_behavior', 'n/a')} "
                f"Observed: {item.get('actual_behavior', 'n/a')} "
                f"Reason: {item.get('reason', 'n/a')} "
                f"Impact: {item.get('impact_assessment', 'n/a')}"
            )
    else:
        lines.append("- No structured workflow deviations were recorded for this run.")
    lines.extend(
        [
            "",
            "## Provenance Pointers",
            f"- Workflow run record: `{workflow_run_path}`",
            f"- Report manifest: `{report_manifest_path}`",
        ]
    )
    if provenance_exports:
        lines.extend(f"- Provenance export: `{path}`" for path in provenance_exports)
    else:
        lines.append("- No provenance exports were materialized for this run.")
    lines.extend(["", "## Next Recommended Actions"])
    lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines)


def _build_rnaseq_report_bundle_outputs(
    *,
    context,
    manifest_path: str,
    manifest: DatasetManifest | None,
    manifest_load_error: str | None = None,
    workflow_run: WorkflowRun,
    raw_qc_bundle: Mapping[str, Any],
    aggregated_qc_bundle: Mapping[str, Any],
    quantification_bundle: Mapping[str, Any],
    differential_expression_bundle: Mapping[str, Any],
    condition_field: str,
    baseline_condition: str,
    comparison_condition: str,
    report_lifecycle_status: str,
) -> dict[str, Any]:
    provenance_exports = _provenance_exports_for_workflow_run(context, workflow_run)
    generated_artifacts = _collect_declared_artifacts(
        raw_qc_bundle,
        aggregated_qc_bundle,
        quantification_bundle,
        differential_expression_bundle,
        field_name="generated_artifacts",
    )
    available_output_types = _available_report_bundle_output_artifact_types(
        workflow_run=workflow_run,
        raw_qc_bundle=raw_qc_bundle,
        aggregated_qc_bundle=aggregated_qc_bundle,
        quantification_bundle=quantification_bundle,
        differential_expression_bundle=differential_expression_bundle,
    )
    canonical_output_artifacts = _canonical_artifact_refs(
        context,
        artifact_types=[
            artifact_type
            for artifact_type in _REPORT_BUNDLE_WORKFLOW_OUTPUT_ARTIFACT_TYPES
            if artifact_type in available_output_types
        ],
    )
    canonical_artifacts_by_type = {
        artifact["artifact_type"]: artifact for artifact in canonical_output_artifacts
    }
    workflow_run_ref = _canonical_artifact_ref(context, "workflow_run")
    evidence_review_artifacts = _linked_workflow_artifacts(
        workflow_run,
        artifact_type="evidence_review",
    )
    deviations = _workflow_deviation_entries(workflow_run)
    deviation_summary = _workflow_deviation_summary(deviations)
    supplementary_generated_artifacts = _filter_artifacts_excluding_types(
        generated_artifacts,
        excluded_artifact_types=set(_REPORT_BUNDLE_WORKFLOW_OUTPUT_ARTIFACT_TYPES),
    )
    warnings = _dedupe_text_entries(
        [*workflow_run.warnings, *_workflow_deviation_warning_lines(deviations)]
    )
    if manifest_load_error:
        warnings.append(
            f"Terminal report bundle used degraded manifest metadata because dataset_manifest could not be loaded: {manifest_load_error}"
        )
    report_qc_status = _report_bundle_display_qc_status(
        lifecycle_status=report_lifecycle_status,
        qc_status=workflow_run.qc_status,
        warnings=warnings,
    )
    qa_report_path = _run_relative_path(context, "qa_report.json")
    report_manifest_path = _generated_output_path(context, "report_bundle_manifest.json", step=_REPORT_BUNDLE_STEP_ID)
    missing_artifacts = _missing_report_bundle_artifacts(
        context,
        available_artifact_types=available_output_types,
    )
    recommendations = _report_bundle_recommendations(
        lifecycle_status=report_lifecycle_status,
        warnings=warnings,
        missing_artifacts=missing_artifacts,
        deviations=deviations,
        differential_expression_bundle=differential_expression_bundle,
    )
    report_bundle_relpath = _write_generated_text(
        context,
        step=_REPORT_BUNDLE_STEP_ID,
        filename=_REPORT_BUNDLE_FILENAME,
        content=_render_rnaseq_report_bundle(
            manifest=manifest,
            manifest_path=manifest_path,
            manifest_load_error=manifest_load_error,
            workflow_run=workflow_run,
            raw_qc_bundle=raw_qc_bundle,
            aggregated_qc_bundle=aggregated_qc_bundle,
            quantification_bundle=quantification_bundle,
            differential_expression_bundle=differential_expression_bundle,
            condition_field=condition_field or "n/a",
            baseline_condition=baseline_condition or "n/a",
            comparison_condition=comparison_condition or "n/a",
            run_id=context.run_id,
            workflow_version=_RNASEQ_WORKFLOW_VERSION,
            workflow_lifecycle_status=report_lifecycle_status,
            workflow_qc_status=report_qc_status,
            workflow_warnings=warnings,
            workflow_run_path=workflow_run_ref["path"],
            report_manifest_path=report_manifest_path,
            provenance_exports=provenance_exports,
            canonical_artifacts_by_type=canonical_artifacts_by_type,
            evidence_review_artifacts=evidence_review_artifacts,
            missing_artifacts=missing_artifacts,
            deviations=deviations,
            recommendations=recommendations,
        ),
    )
    checklist_artifacts = _dedupe_artifacts(
        [
            {
                "artifact_type": "dataset_manifest",
                "path": context.relative_path(manifest_path) if manifest_path else "n/a",
                **({"id": manifest.id, "run_id": manifest.run_id} if manifest is not None else {}),
            },
            workflow_run_ref,
            *canonical_output_artifacts,
            *supplementary_generated_artifacts,
            *evidence_review_artifacts,
        ]
    )
    overall_status = _report_bundle_qa_status(
        lifecycle_status=report_lifecycle_status,
        qc_status=workflow_run.qc_status,
        warnings=warnings,
    )

    return {
        "report_bundle_manifest": {
            "bundle_version": "1.0.0",
            "stage": _REPORT_BUNDLE_STEP_ID,
            "workflow_id": context.workflow_id,
            "workflow_version": _RNASEQ_WORKFLOW_VERSION,
            "lifecycle_status": report_lifecycle_status,
            "qc_status": report_qc_status,
            "study_name": manifest.design.study_name if manifest is not None else "unknown-study",
            "contrast": {
                "condition_field": condition_field or "n/a",
                "baseline_condition": baseline_condition or "n/a",
                "comparison_condition": comparison_condition or "n/a",
            },
            "sections": list(_REPORT_BUNDLE_SECTIONS),
            "workflow_run_path": workflow_run_ref["path"],
            "report_markdown_path": report_bundle_relpath,
            "provenance_exports": provenance_exports,
            "evidence_review_artifacts": evidence_review_artifacts,
            "expected_artifacts": [
                workflow_run_ref,
                *canonical_output_artifacts,
                *supplementary_generated_artifacts,
                *evidence_review_artifacts,
                {
                    "artifact_type": "report_bundle",
                    "path": report_bundle_relpath,
                    "description": "Human-readable RNA-seq report bundle linking the canonical QC, quantification, and DE outputs.",
                },
                {
                    "artifact_type": "qa_report",
                    "path": qa_report_path,
                    "description": "Structured QA report copied to the stable root artifact location.",
                },
            ],
            "missing_artifacts": missing_artifacts,
            "deviations": deviations,
            "deviation_summary": deviation_summary,
            "next_actions": recommendations,
            "notes": [
                "The report bundle links the canonical workflow run record and any stable workflow outputs that were actually materialized for this run.",
                "Linked evidence-review artifacts are carried forward when available so downstream QA and report consumers can inspect literature-grounded claim support directly from the bundle.",
                "Structured workflow deviations are copied into the bundle so reviewers can inspect what changed, why it changed, and the likely downstream impact without reopening the raw run record.",
                "Blocked or failed runs still emit a partial report bundle so users can inspect available artifacts and missing downstream outputs without reading the raw run record.",
            ],
        },
        "qa_report": {
            "overall_status": overall_status,
            "failed_checks": _report_bundle_failed_checks(
                lifecycle_status=report_lifecycle_status,
                missing_artifacts=missing_artifacts,
                deviations=deviations,
            ),
            "warnings": warnings,
            "missing_artifacts": missing_artifacts,
            "recommended_remediation": recommendations,
            "checklist_artifacts": checklist_artifacts,
            "related_artifacts": evidence_review_artifacts,
        },
    }


def _provenance_exports_for_workflow_run(context, workflow_run: WorkflowRun) -> list[str]:
    if workflow_run.provenance_exports:
        return list(workflow_run.provenance_exports)
    return [
        _run_relative_path(context, "prov.json"),
        _run_relative_path(context, "ro-crate", "ro-crate-metadata.json"),
    ]


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _optional_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_text_entries(values: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        candidate = str(item).strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(candidate)
    return cleaned


def _workflow_deviation_entries(workflow_run: WorkflowRun) -> list[dict[str, Any]]:
    step_labels = {record.id: record.name for record in workflow_run.steps}
    entries: list[dict[str, Any]] = []
    for deviation in workflow_run.deviations:
        payload = deviation.model_dump(mode="json")
        step_label = step_labels.get(deviation.step_id)
        if step_label:
            payload["step_label"] = step_label
        entries.append(payload)
    return entries


def _workflow_deviation_summary(deviations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_severity = {"minor": 0, "major": 0, "critical": 0}
    by_origin = {"manual": 0, "automatic": 0}
    severity_rank = {"minor": 1, "major": 2, "critical": 3}
    highest_severity: str | None = None
    highest_rank = 0

    for item in deviations:
        severity = item.get("severity")
        if isinstance(severity, str) and severity in by_severity:
            by_severity[severity] += 1
            rank = severity_rank[severity]
            if rank > highest_rank:
                highest_rank = rank
                highest_severity = severity
        origin = item.get("origin")
        if isinstance(origin, str) and origin in by_origin:
            by_origin[origin] += 1

    return {
        "count": len(deviations),
        "by_severity": by_severity,
        "by_origin": by_origin,
        "highest_severity": highest_severity,
    }


def _workflow_deviation_warning_lines(deviations: Sequence[Mapping[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for item in deviations:
        step_id = str(item.get("step_id", "unknown-step"))
        step_label = str(item.get("step_label", "")).strip()
        actual_behavior = str(item.get("actual_behavior", "Deviation details were not provided.")).strip()
        severity = str(item.get("severity", "minor")).strip() or "minor"
        if severity not in {"major", "critical"}:
            continue
        label = f" ({step_label})" if step_label else ""
        warnings.append(
            f"{severity.capitalize()} workflow deviation at {step_id}{label}: {actual_behavior}"
        )
    return warnings


def _workflow_deviation_failed_checks(deviations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    failed_checks: list[dict[str, Any]] = []
    for index, item in enumerate(deviations, start=1):
        severity = item.get("severity")
        if severity not in {"major", "critical"}:
            continue
        step_id = str(item.get("step_id", "unknown-step"))
        step_label = str(item.get("step_label", "")).strip()
        label = f" ({step_label})" if step_label else ""
        actual_behavior = str(item.get("actual_behavior", "Deviation details were not provided.")).strip()
        impact_assessment = str(
            item.get("impact_assessment", "Review the logged workflow deviation before publication or export.")
        ).strip()
        failed_checks.append(
            {
                "id": f"workflow-deviation-{step_id}-{index}",
                "description": f"Structured workflow deviation at {step_id}{label}: {actual_behavior}",
                "severity": "critical" if severity == "critical" else "error",
                "artifact_type": "workflow_run",
                "remediation": impact_assessment,
            }
        )
    return failed_checks


def _available_report_bundle_output_artifact_types(
    *,
    workflow_run: WorkflowRun,
    raw_qc_bundle: Mapping[str, Any],
    aggregated_qc_bundle: Mapping[str, Any],
    quantification_bundle: Mapping[str, Any],
    differential_expression_bundle: Mapping[str, Any],
) -> set[str]:
    artifact_types = {
        ref.artifact_type
        for ref in workflow_run.outputs
        if ref.artifact_type in _REPORT_BUNDLE_WORKFLOW_OUTPUT_ARTIFACT_TYPES
    }
    if raw_qc_bundle:
        artifact_types.update({"fastqc_run", "fastqc_metrics"})
    if aggregated_qc_bundle:
        artifact_types.update({"multiqc_run", "multiqc_metrics"})
    if quantification_bundle:
        artifact_types.add("count_matrix")
    if differential_expression_bundle:
        artifact_types.update(
            {
                "normalized_count_matrix",
                "differential_expression_results",
                "differential_expression_run",
            }
        )
    return artifact_types


def _missing_report_bundle_artifacts(
    context,
    *,
    available_artifact_types: set[str],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for artifact_type in _REPORT_BUNDLE_WORKFLOW_OUTPUT_ARTIFACT_TYPES:
        if artifact_type in available_artifact_types:
            continue
        missing.append(
            {
                "artifact_type": artifact_type,
                "expected_path": _run_relative_path(context, stable_artifact_name(artifact_type)),
                "rationale": f"The workflow did not materialize {artifact_type} before reaching a terminal state.",
            }
        )
    return missing


def _report_bundle_recommendations(
    *,
    lifecycle_status: str,
    warnings: Sequence[str],
    missing_artifacts: Sequence[Mapping[str, Any]],
    deviations: Sequence[Mapping[str, Any]],
    differential_expression_bundle: Mapping[str, Any],
) -> list[str]:
    recommendations: list[str] = []
    if lifecycle_status == "blocked":
        recommendations.append(
            "Resolve the blocking QC or execution issue, then rerun the workflow before using absent downstream outputs."
        )
    elif lifecycle_status == "failed":
        recommendations.append(
            "Inspect the failed workflow step and rerun once the execution error has been corrected."
        )
    elif warnings:
        recommendations.append(
            "Resolve or explicitly document the workflow warnings before publication or wet-lab follow-up."
        )

    if missing_artifacts:
        recommendations.append(
            "Review the available QC artifacts and the workflow run record to confirm which downstream outputs were never materialized."
        )
    if deviations:
        recommendations.append(
            "Review the structured workflow deviations and document whether each impact assessment is acceptable before publication, export, or wet-lab follow-up."
        )
    if differential_expression_bundle:
        recommendations.append(
            "Review the top DE genes and diagnostic plots in the bundle before moving to biological interpretation."
        )
        recommendations.append(
            "Use the durable count and normalized-count matrices for downstream reproducibility checks."
        )
    if not recommendations:
        recommendations.append(
            "Archive the report bundle alongside the workflow run record as the primary human-readable handoff artifact."
        )
    return recommendations


def _report_bundle_qa_status(
    *,
    lifecycle_status: str,
    qc_status: str,
    warnings: Sequence[str],
) -> str:
    if lifecycle_status == "blocked":
        return "blocked"
    if lifecycle_status == "failed":
        return "failed"
    return _qa_overall_status_from_workflow_qc(qc_status, warnings=warnings)


def _report_bundle_display_qc_status(
    *,
    lifecycle_status: str,
    qc_status: str,
    warnings: Sequence[str],
) -> str:
    if lifecycle_status in {"blocked", "failed"}:
        return "failed"
    if qc_status in {"passed", "warning", "failed"}:
        return qc_status
    return "warning" if warnings else "passed"


def _report_bundle_failed_checks(
    *,
    lifecycle_status: str,
    missing_artifacts: Sequence[Mapping[str, Any]],
    deviations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    failed_checks = _workflow_deviation_failed_checks(deviations)
    if lifecycle_status not in {"blocked", "failed"}:
        return failed_checks
    severity = "error" if lifecycle_status == "blocked" else "critical"
    description = (
        "Workflow execution was blocked before the final report-bundle stage completed."
        if lifecycle_status == "blocked"
        else "Workflow execution failed before the final report-bundle stage completed."
    )
    remediation = (
        "Review the workflow warnings, missing artifacts, and upstream stage outputs before rerunning the workflow."
        if missing_artifacts
        else "Review the workflow warnings and upstream stage outputs before rerunning the workflow."
    )
    return [
        *failed_checks,
        {
            "id": f"workflow-{lifecycle_status}",
            "description": description,
            "severity": severity,
            "artifact_type": "workflow_run",
            "remediation": remediation,
        },
    ]


def _contrast_slug(comparison_condition: str, baseline_condition: str) -> str:
    comparison_slug = comparison_condition.strip().lower().replace(" ", "-")
    baseline_slug = baseline_condition.strip().lower().replace(" ", "-")
    return f"{comparison_slug}-vs-{baseline_slug}"


def _mean(values: Sequence[float] | Any) -> float:
    value_list = [float(item) for item in values]
    if not value_list:
        raise ValueError("Mean requires at least one value.")
    return sum(value_list) / len(value_list)


def _median(values: Sequence[int]) -> float:
    ordered = sorted(int(item) for item in values)
    if not ordered:
        raise ValueError("Median requires at least one value.")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean_value = _mean(values)
    return sum((float(item) - mean_value) ** 2 for item in values) / (len(values) - 1)


def _load_manifest(context, manifest_path: str) -> DatasetManifest:
    document = load_artifact_document(context.resolve_path(manifest_path))
    if not isinstance(document, DatasetManifest):
        raise ValueError(f"Expected dataset_manifest artifact at {manifest_path!r}.")
    return document


def _load_fastqc_run_document(context, artifact_path: str) -> FastQCRun:
    document = load_artifact_document(context.base_dir / artifact_path)
    if not isinstance(document, FastQCRun):
        raise ValueError(f"Expected fastqc_run artifact at {artifact_path!r}.")
    return document


def _load_fastqc_metrics_document(context, artifact_path: str) -> FastQCMetrics:
    document = load_artifact_document(context.base_dir / artifact_path)
    if not isinstance(document, FastQCMetrics):
        raise ValueError(f"Expected fastqc_metrics artifact at {artifact_path!r}.")
    return document


def _load_workflow_run_document(context) -> WorkflowRun:
    document = load_artifact_document(context.run_dir / RUN_RECORD_FILENAME)
    if not isinstance(document, WorkflowRun):
        raise ValueError(f"Expected workflow_run artifact at {RUN_RECORD_FILENAME!r}.")
    return document


def _fastqc_config(manifest: DatasetManifest) -> tuple[str, list[str]]:
    raw_config = manifest.assay_extensions.get("fastqc")
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, Mapping):
        raise ValueError("dataset_manifest.assay_extensions.fastqc must be a mapping when provided.")

    executable = raw_config.get("executable")
    if executable is None:
        executable = os.environ.get("BIOAPEX_FASTQC_BIN", "fastqc")
    executable_text = str(executable).strip()
    if not executable_text:
        raise ValueError("FastQC executable must not be empty.")

    raw_extra_args = raw_config.get("extra_args", [])
    if raw_extra_args is None:
        raw_extra_args = []
    if not isinstance(raw_extra_args, Sequence) or isinstance(raw_extra_args, (str, bytes)):
        raise ValueError("dataset_manifest.assay_extensions.fastqc.extra_args must be a list of strings.")
    extra_args = [str(item).strip() for item in raw_extra_args]
    if any(not item for item in extra_args):
        raise ValueError("FastQC extra_args entries must not be empty.")

    return executable_text, extra_args


def _multiqc_config(manifest: DatasetManifest) -> tuple[str, list[str]]:
    raw_config = manifest.assay_extensions.get("multiqc")
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, Mapping):
        raise ValueError("dataset_manifest.assay_extensions.multiqc must be a mapping when provided.")

    executable = raw_config.get("executable")
    if executable is None:
        executable = os.environ.get("BIOAPEX_MULTIQC_BIN", "multiqc")
    executable_text = str(executable).strip()
    if not executable_text:
        raise ValueError("MultiQC executable must not be empty.")

    raw_extra_args = raw_config.get("extra_args", [])
    if raw_extra_args is None:
        raw_extra_args = []
    if not isinstance(raw_extra_args, Sequence) or isinstance(raw_extra_args, (str, bytes)):
        raise ValueError("dataset_manifest.assay_extensions.multiqc.extra_args must be a list of strings.")
    extra_args = [str(item).strip() for item in raw_extra_args]
    if any(not item for item in extra_args):
        raise ValueError("MultiQC extra_args entries must not be empty.")

    return executable_text, extra_args


def _stage_stub_config(manifest: DatasetManifest, stage_name: str) -> Mapping[str, Any]:
    workflow_stub = manifest.assay_extensions.get("workflow_stub")
    if not isinstance(workflow_stub, Mapping):
        return {}
    stage_stub = workflow_stub.get(stage_name)
    if not isinstance(stage_stub, Mapping):
        return {}
    return stage_stub


def _aggregate_fastqc_reports(parsed_reports: Sequence[FastQCParsedReport]) -> dict[str, Any]:
    if not parsed_reports:
        raise ValueError("FastQC aggregation requires at least one parsed report.")

    total_reads = 0
    min_per_base_quality_values: list[float] = []
    module_status_counts: dict[str, dict[str, Any]] = {}
    sample_statuses: dict[str, str] = {}

    for report in parsed_reports:
        if report.total_sequences is not None:
            total_reads += report.total_sequences
        if report.min_per_base_quality is not None:
            min_per_base_quality_values.append(report.min_per_base_quality)

        sample_statuses[report.sample_id] = _worst_status(
            [sample_statuses.get(report.sample_id, "pass"), report.overall_status]
        )
        for module in report.module_results:
            counts = module_status_counts.setdefault(
                module.module_id,
                {
                    "module_id": module.module_id,
                    "module_name": module.module_name,
                    "pass_count": 0,
                    "warn_count": 0,
                    "fail_count": 0,
                },
            )
            counts[f"{module.status}_count"] += 1

    sample_count = len(sample_statuses)
    passed_samples = sum(1 for status in sample_statuses.values() if status == "pass")
    return {
        "sequencing_layout": _reports_sequencing_layout(parsed_reports),
        "sample_count": sample_count,
        "input_file_count": len(parsed_reports),
        "total_reads": total_reads,
        "total_reads_millions": round(total_reads / 1_000_000, 4),
        "min_per_base_quality": min(min_per_base_quality_values) if min_per_base_quality_values else None,
        "fastqc_pass_rate": round((passed_samples / sample_count) if sample_count else 0.0, 4),
        "module_status_counts": list(module_status_counts.values()),
    }


def _reports_sequencing_layout(parsed_reports: Sequence[FastQCParsedReport]) -> str:
    read_labels = {report.read_label for report in parsed_reports}
    return "paired_end" if "read2" in read_labels else "single_end"


def _build_multiqc_sample_metrics(
    fastqc_metrics: FastQCMetrics,
    report_sample_names: Sequence[str],
) -> list[dict[str, Any]]:
    samples: dict[str, dict[str, Any]] = {}
    for sample_metric in fastqc_metrics.sample_metrics:
        entry = samples.setdefault(
            sample_metric.sample_id,
            {
                "sample_id": sample_metric.sample_id,
                "input_file_count": 0,
                "total_reads": 0,
                "min_per_base_quality_values": [],
                "statuses": [],
            },
        )
        entry["input_file_count"] += 1
        if sample_metric.total_sequences is not None:
            entry["total_reads"] += sample_metric.total_sequences
        if sample_metric.min_per_base_quality is not None:
            entry["min_per_base_quality_values"].append(sample_metric.min_per_base_quality)
        entry["statuses"].append(sample_metric.overall_status)

    selected_sample_ids = sorted(samples)
    if report_sample_names:
        report_sample_set = {item.strip() for item in report_sample_names if str(item).strip()}
        missing_sample_ids = sorted(report_sample_set - set(samples))
        if missing_sample_ids:
            raise ValueError(
                "MultiQC reported sample names that were not present in upstream FastQC metrics: "
                + ", ".join(missing_sample_ids)
            )
        selected_sample_ids = [sample_id for sample_id in selected_sample_ids if sample_id in report_sample_set]

    sample_summaries: list[dict[str, Any]] = []
    for sample_id in selected_sample_ids:
        entry = samples[sample_id]
        total_reads = int(entry["total_reads"])
        min_per_base_quality_values = entry["min_per_base_quality_values"]
        statuses = entry["statuses"]
        sample_summaries.append(
            {
                "sample_id": sample_id,
                "input_file_count": int(entry["input_file_count"]),
                "total_reads": total_reads,
                "total_reads_millions": round(total_reads / 1_000_000, 4),
                "min_per_base_quality": (
                    min(min_per_base_quality_values) if min_per_base_quality_values else None
                ),
                "fastqc_status": _worst_status(statuses),
            }
        )
    return sample_summaries


def _build_multiqc_aggregate_metrics(
    fastqc_metrics: FastQCMetrics,
    report_summary,
    sample_metrics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    report_modules = list(report_summary.module_names)
    if not report_modules:
        report_modules = [
            item.module_name
            for item in fastqc_metrics.aggregate_metrics.module_status_counts
        ]
    report_modules = list(dict.fromkeys(report_modules))
    report_sample_count = len(report_summary.sample_names) if report_summary.sample_names else len(sample_metrics)

    sample_count = len(sample_metrics)
    input_file_count = sum(int(item.get("input_file_count", 0)) for item in sample_metrics)
    total_reads = sum(int(item.get("total_reads", 0)) for item in sample_metrics)
    min_per_base_quality_values = [
        float(value)
        for value in (item.get("min_per_base_quality") for item in sample_metrics)
        if value is not None
    ]
    passed_samples = sum(1 for item in sample_metrics if item.get("fastqc_status") == "pass")

    return {
        "sample_count": sample_count,
        "input_file_count": input_file_count,
        "total_reads": total_reads,
        "total_reads_millions": round(total_reads / 1_000_000, 4),
        "min_per_base_quality": min(min_per_base_quality_values) if min_per_base_quality_values else None,
        "fastqc_pass_rate": round((passed_samples / sample_count) if sample_count else 0.0, 4),
        "report_sample_count": report_sample_count,
        "report_module_count": len(report_modules),
        "report_modules": report_modules,
    }


def _write_generated_text(
    context,
    *,
    step: str,
    filename: str,
    content: str,
) -> str:
    relative_under_run = build_generated_output_relpath(filename, step=step)
    absolute_path = context.run_dir / relative_under_run
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_text(content if content.endswith("\n") or not content else f"{content}\n", encoding="utf-8")
    return _join_run_relative(context, relative_under_run)


def _generated_subdir_relative_path(context, *, step: str, name: str) -> PurePosixPath:
    generated_step_dir = build_generated_output_relpath("__placeholder__", step=step).parent
    return PurePosixPath(generated_step_dir) / name


def _join_run_relative(context, *parts: str | PurePosixPath) -> str:
    normalized_parts = [str(part).strip("/") for part in parts if str(part)]
    if not normalized_parts:
        return str(context.relative_run_dir)
    return str(PurePosixPath(context.relative_run_dir).joinpath(*normalized_parts))


def _run_relative_path(context, *parts: str) -> str:
    return str(PurePosixPath(context.relative_run_dir).joinpath(*parts))


def _generated_output_path(context, filename: str, *, step: str) -> str:
    return str(PurePosixPath(context.relative_run_dir) / build_generated_output_relpath(filename, step=step))


def _artifact_ref(
    artifact_type: str,
    path: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_type": artifact_type,
        "path": path,
    }
    if run_id is not None:
        payload["run_id"] = run_id
    return payload


def _canonical_artifact_ref(context, artifact_type: str) -> dict[str, Any]:
    return _artifact_ref(
        artifact_type,
        _run_relative_path(context, stable_artifact_name(artifact_type)),
        run_id=context.run_id,
    )


def _canonical_artifact_refs(
    context,
    *,
    artifact_types: Sequence[str],
) -> list[dict[str, Any]]:
    return [_canonical_artifact_ref(context, artifact_type) for artifact_type in artifact_types]


def _require_artifact_ref(
    value: Any,
    *,
    artifact_type: str,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping artifact reference.")
    resolved_artifact_type = value.get("artifact_type")
    path = value.get("path")
    if resolved_artifact_type != artifact_type or not isinstance(path, str) or not path.strip():
        raise ValueError(f"{field_name} must reference a {artifact_type} artifact with a valid path.")
    payload = {"artifact_type": artifact_type, "path": path}
    run_id = value.get("run_id")
    if isinstance(run_id, str) and run_id.strip():
        payload["run_id"] = run_id.strip()
    return payload


def _dedupe_artifacts(artifacts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        artifact_type = artifact.get("artifact_type")
        path = artifact.get("path")
        if not isinstance(artifact_type, str) or not isinstance(path, str):
            continue
        key = (artifact_type, path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(artifact))
    return deduped


def _linked_workflow_artifacts(
    workflow_run: WorkflowRun,
    *,
    artifact_type: str,
) -> list[dict[str, Any]]:
    return _dedupe_artifacts(
        [
            ref.model_dump(mode="json")
            for ref in [*workflow_run.inputs, *workflow_run.outputs, *workflow_run.related_artifacts]
            if ref.artifact_type == artifact_type
        ]
    )


def _filter_artifacts_excluding_types(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    excluded_artifact_types: set[str],
) -> list[dict[str, Any]]:
    return [
        dict(artifact)
        for artifact in artifacts
        if isinstance(artifact.get("artifact_type"), str)
        and artifact["artifact_type"] not in excluded_artifact_types
    ]


def _collect_declared_artifacts(
    *bundles: Mapping[str, Any],
    field_name: str,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bundle in bundles:
        raw_items = bundle.get(field_name)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            artifact_type = item.get("artifact_type")
            path = item.get("path")
            if not isinstance(artifact_type, str) or not isinstance(path, str):
                continue
            key = (artifact_type, path)
            if key in seen:
                continue
            seen.add(key)
            artifact_payload = {"artifact_type": artifact_type, "path": path}
            description = item.get("description")
            if isinstance(description, str) and description.strip():
                artifact_payload["description"] = description.strip()
            artifacts.append(artifact_payload)
    return artifacts


def _qa_overall_status_from_workflow_qc(qc_status: str, *, warnings: Sequence[str]) -> str:
    if qc_status == "failed":
        return "failed"
    if qc_status == "warning" or warnings:
        return "warning"
    return "passed"


def _as_float(value: Any, *, default: float) -> float:
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return default


def _worst_status(statuses: Sequence[str]) -> str:
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"
