"""Python executors for the authored RNA-seq workflow."""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from artifacts import (
    DatasetManifest,
    FastQCMetrics,
    FastQCRun,
    build_generated_output_relpath,
    load_artifact_document,
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
    counts_path = _generated_output_path(context, "gene_counts.tsv", step="quantification")
    transcript_tpm_path = _generated_output_path(context, "transcript_tpm.tsv", step="quantification")

    return {
        "quantification_bundle": {
            "stage": "quantification",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "condition_field": str(inputs["condition_field"]),
            "expected_artifacts": [
                {
                    "artifact_type": "count_matrix",
                    "path": counts_path,
                    "description": "Placeholder gene-level count matrix for future quantification integration.",
                },
                {
                    "artifact_type": "transcript_tpm_matrix",
                    "path": transcript_tpm_path,
                    "description": "Placeholder transcript-abundance matrix for future quantification integration.",
                },
            ],
            "notes": [
                "This workflow preserves the quantification stage boundary without invoking a concrete aligner or quantifier yet.",
                "Upstream FastQC and MultiQC artifacts now land concretely, and later DE integrations can consume the declared bundle paths without reshaping the workflow graph.",
            ],
        }
    }


def plan_differential_expression(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    baseline_condition = str(inputs["baseline_condition"]).strip()
    comparison_condition = str(inputs["comparison_condition"]).strip()
    contrast_slug = f"{comparison_condition}-vs-{baseline_condition}".replace(" ", "-").lower()
    results_path = _generated_output_path(context, f"{contrast_slug}.tsv", step="differential_expression")
    volcano_plot_path = _generated_output_path(context, f"{contrast_slug}.png", step="differential_expression")

    return {
        "differential_expression_bundle": {
            "stage": "differential_expression",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "contrast": {
                "condition_field": str(inputs["condition_field"]),
                "baseline_condition": baseline_condition,
                "comparison_condition": comparison_condition,
            },
            "planned_method": "stubbed_deseq2_contract",
            "expected_artifacts": [
                {
                    "artifact_type": "differential_expression_results",
                    "path": results_path,
                    "description": "Placeholder differential-expression results table for future DE integration.",
                },
                {
                    "artifact_type": "volcano_plot",
                    "path": volcano_plot_path,
                    "description": "Placeholder visualization artifact for future DE integration.",
                },
            ],
            "notes": [
                "The workflow preserves the DE contract and comparison metadata without executing a real statistical model yet.",
            ],
        }
    }


def build_report_bundle(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    generated_artifacts = _collect_declared_artifacts(
        inputs["raw_qc_bundle"],
        inputs["aggregated_qc_bundle"],
        field_name="generated_artifacts",
    )
    pending_artifacts = _collect_declared_artifacts(
        inputs["quantification_bundle"],
        inputs["differential_expression_bundle"],
        field_name="expected_artifacts",
    )
    report_bundle_path = _generated_output_path(context, "rnaseq_report_bundle.md", step="report_bundle")
    qa_report_path = _run_relative_path(context, "qa_report.json")

    warnings = [
        "RNA-seq workflow executed with concrete FastQC raw QC and MultiQC aggregated QC, while quantification and differential expression remain placeholder stages.",
        "Downstream analysis artifacts remain declared for future integrations and are not materialized by the current workflow stage set.",
    ]

    return {
        "report_bundle_manifest": {
            "stage": "report_bundle",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "contrast": {
                "condition_field": str(inputs["condition_field"]),
                "baseline_condition": str(inputs["baseline_condition"]).strip(),
                "comparison_condition": str(inputs["comparison_condition"]).strip(),
            },
            "sections": [
                "dataset_intake",
                "compliance_preflight",
                "raw_qc",
                "aggregated_qc",
                "quantification",
                "differential_expression",
                "report_bundle",
            ],
            "expected_artifacts": [
                *generated_artifacts,
                *pending_artifacts,
                {
                    "artifact_type": "report_bundle",
                    "path": report_bundle_path,
                    "description": "Placeholder human-readable RNA-seq report bundle.",
                },
                {
                    "artifact_type": "qa_report",
                    "path": qa_report_path,
                    "description": "Structured QA report copied to the stable root artifact location.",
                },
            ],
            "notes": [
                "This manifest now includes materialized FastQC and MultiQC outputs alongside planned downstream bundle paths.",
                "It remains the durable contract for later report-template and provenance integrations.",
            ],
        },
        "qa_report": {
            "overall_status": "warning",
            "failed_checks": [],
            "warnings": warnings,
            "missing_artifacts": [
                {
                    "artifact_type": artifact["artifact_type"],
                    "expected_path": artifact["path"],
                    "rationale": "Declared for a later workflow integration, but not materialized by the current stage implementation.",
                }
                for artifact in [
                    *pending_artifacts,
                    {
                        "artifact_type": "report_bundle",
                        "path": report_bundle_path,
                    },
                ]
            ],
            "recommended_remediation": [
                "Materialize the declared quantification, differential expression, report bundle, and provenance exports before publication.",
            ],
            "checklist_artifacts": [
                {
                    "artifact_type": "dataset_manifest",
                    "path": context.relative_path(inputs["dataset_manifest"]),
                    "id": manifest.id,
                    "run_id": manifest.run_id,
                }
            ],
        },
    }


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
