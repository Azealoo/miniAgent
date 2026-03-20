"""Python executors for the RNA-seq workflow skeleton."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from artifacts import DatasetManifest, build_generated_output_relpath, load_artifact_document
from dataset_intake import ensure_valid_dataset_intake_manifest


def validate_inputs(inputs, context):
    result = ensure_valid_dataset_intake_manifest(context.base_dir, inputs["dataset_manifest"])
    manifest = _load_manifest(context, result.manifest_path)
    condition_field = str(inputs["condition_field"]).strip()
    baseline_condition = str(inputs["baseline_condition"]).strip()
    comparison_condition = str(inputs["comparison_condition"]).strip()

    if manifest.assay_type != "bulk_rna_seq":
        raise ValueError(
            "RNA-seq workflow skeleton requires dataset_manifest.assay_type 'bulk_rna_seq'."
        )
    if manifest.design.analysis_kind != "comparative":
        raise ValueError(
            "RNA-seq workflow skeleton requires dataset_manifest.design.analysis_kind 'comparative'."
        )
    if condition_field not in (manifest.design.condition_fields or []):
        raise ValueError(
            f"RNA-seq workflow skeleton requires condition_field {condition_field!r} to appear in dataset_manifest.design.condition_fields."
        )
    if baseline_condition == comparison_condition:
        raise ValueError("baseline_condition and comparison_condition must differ.")

    return {"validated_manifest": result.manifest_path}


def run_raw_qc(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    raw_qc_stub = _stage_stub_config(manifest, "raw_qc")
    fastqc_summary_path = _generated_output_path(context, "fastqc_summary.json", step="raw_qc")
    fastqc_bundle_path = _generated_output_path(context, "fastqc_bundle.zip", step="raw_qc")

    min_per_base_quality = _as_float(raw_qc_stub.get("min_per_base_quality"), default=32.0)
    total_reads_millions = _as_float(raw_qc_stub.get("total_reads_millions"), default=38.0)

    return {
        "raw_qc_bundle": {
            "stage": "raw_qc",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "assay_type": manifest.assay_type,
            "expected_artifacts": [
                {
                    "artifact_type": "fastqc_summary",
                    "path": fastqc_summary_path,
                    "description": "Placeholder summary output for future FastQC integration.",
                },
                {
                    "artifact_type": "fastqc_bundle",
                    "path": fastqc_bundle_path,
                    "description": "Placeholder archive for per-sample FastQC artifacts.",
                },
            ],
            "qc_evidence": {
                "upstream_tools": ["fastqc"],
                "metrics": [
                    {
                        "metric_name": "min_per_base_quality",
                        "observed_value": min_per_base_quality,
                        "source_artifact": {
                            "artifact_type": "fastqc_summary",
                            "path": fastqc_summary_path,
                        },
                    },
                    {
                        "metric_name": "total_reads_millions",
                        "observed_value": total_reads_millions,
                        "source_artifact": {
                            "artifact_type": "fastqc_summary",
                            "path": fastqc_summary_path,
                        },
                    },
                ],
                "notes": "Stub raw QC metrics mirror the normalized FastQC-style contract until concrete FastQC integration lands.",
            },
        }
    }


def aggregate_qc(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    aggregated_qc_stub = _stage_stub_config(manifest, "aggregated_qc")
    multiqc_summary_path = _generated_output_path(context, "multiqc_summary.json", step="aggregated_qc")
    multiqc_report_path = _generated_output_path(context, "multiqc_report.html", step="aggregated_qc")

    fastqc_pass_rate = _as_float(aggregated_qc_stub.get("fastqc_pass_rate"), default=1.0)
    libraries_aggregated = _as_float(aggregated_qc_stub.get("libraries_aggregated"), default=6.0)

    return {
        "aggregated_qc_bundle": {
            "stage": "aggregated_qc",
            "workflow_id": context.workflow_id,
            "study_name": manifest.design.study_name,
            "assay_type": manifest.assay_type,
            "upstream_stage": "raw_qc",
            "expected_artifacts": [
                {
                    "artifact_type": "multiqc_summary",
                    "path": multiqc_summary_path,
                    "description": "Placeholder JSON summary for future MultiQC integration.",
                },
                {
                    "artifact_type": "multiqc_report",
                    "path": multiqc_report_path,
                    "description": "Placeholder rendered MultiQC report artifact.",
                },
            ],
            "qc_evidence": {
                "upstream_tools": ["fastqc", "multiqc"],
                "metrics": [
                    {
                        "metric_name": "fastqc_pass_rate",
                        "observed_value": fastqc_pass_rate,
                        "source_artifact": {
                            "artifact_type": "multiqc_summary",
                            "path": multiqc_summary_path,
                        },
                    },
                    {
                        "metric_name": "libraries_aggregated",
                        "observed_value": libraries_aggregated,
                        "source_artifact": {
                            "artifact_type": "multiqc_summary",
                            "path": multiqc_summary_path,
                        },
                    },
                ],
                "notes": "Stub aggregated QC metrics mirror the normalized MultiQC-style contract until concrete MultiQC integration lands.",
            },
        }
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
                "This skeleton reserves the quantification stage boundary without invoking a concrete aligner or quantifier yet.",
                "Later FastQC, MultiQC, and DE integrations can consume these declared bundle paths without reshaping the workflow graph.",
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
                "The workflow skeleton preserves the DE contract and comparison metadata without executing a real statistical model yet.",
            ],
        }
    }


def build_report_bundle(inputs, context):
    manifest = _load_manifest(context, inputs["dataset_manifest"])
    expected_artifacts = _collect_expected_artifacts(
        inputs["raw_qc_bundle"],
        inputs["aggregated_qc_bundle"],
        inputs["quantification_bundle"],
        inputs["differential_expression_bundle"],
    )
    report_bundle_path = _generated_output_path(context, "rnaseq_report_bundle.md", step="report_bundle")
    qa_report_path = _run_relative_path(context, "qa_report.json")

    warnings = [
        "RNA-seq workflow skeleton executed with stubbed raw QC, aggregated QC, quantification, and differential expression stages.",
        "Expected downstream artifacts are declared for future integrations but are not materialized by this skeleton workflow yet.",
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
                *expected_artifacts,
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
                "This manifest is the durable contract for later report-template and provenance integrations.",
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
                    "rationale": "Declared by the workflow skeleton for later integration, but not materialized by the current stub executor.",
                }
                for artifact in [
                    *expected_artifacts,
                    {
                        "artifact_type": "report_bundle",
                        "path": report_bundle_path,
                    },
                ]
            ],
            "recommended_remediation": [
                "Replace stub stage executors with real FastQC, MultiQC, quantification, and differential expression integrations.",
                "Materialize the declared report bundle and provenance exports before publication.",
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


def _stage_stub_config(manifest: DatasetManifest, stage_name: str) -> Mapping[str, Any]:
    workflow_stub = manifest.assay_extensions.get("workflow_stub")
    if not isinstance(workflow_stub, Mapping):
        return {}
    stage_stub = workflow_stub.get(stage_name)
    if not isinstance(stage_stub, Mapping):
        return {}
    return stage_stub


def _run_relative_path(context, *parts: str) -> str:
    return str(PurePosixPath(context.relative_run_dir).joinpath(*parts))


def _generated_output_path(context, filename: str, *, step: str) -> str:
    return str(PurePosixPath(context.relative_run_dir) / build_generated_output_relpath(filename, step=step))


def _as_float(value: Any, *, default: float) -> float:
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return default


def _collect_expected_artifacts(*bundles: Mapping[str, Any]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for bundle in bundles:
        raw_items = bundle.get("expected_artifacts")
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
