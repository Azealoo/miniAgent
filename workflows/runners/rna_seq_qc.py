"""Sample Python executors for the RNA-seq QC workflow."""

from __future__ import annotations

from artifacts import load_artifact_document


def validate_manifest(inputs, context):
    manifest_path = context.resolve_path(inputs["dataset_manifest"])
    manifest = load_artifact_document(manifest_path)
    if manifest.artifact_type != "dataset_manifest":
        raise ValueError("RNA-seq QC preflight requires a dataset_manifest artifact.")
    return {"validated_manifest": context.relative_path(manifest_path)}


def summarize_qc(inputs, context):
    manifest_path = context.relative_path(inputs["dataset_manifest"])
    min_genes = int(inputs.get("min_genes", 200))
    overall_status = "passed" if min_genes >= 200 else "warning"
    warnings = []
    remediation = []
    if overall_status == "warning":
        warnings.append(
            f"Configured min_genes threshold {min_genes} is below the default RNA-seq QC baseline."
        )
        remediation.append("Review the QC threshold before publishing downstream summaries.")

    return {
        "qa_report": {
            "overall_status": overall_status,
            "failed_checks": [],
            "warnings": warnings,
            "missing_artifacts": [],
            "recommended_remediation": remediation,
            "checklist_artifacts": [
                {
                    "artifact_type": "dataset_manifest",
                    "path": manifest_path,
                }
            ],
        }
    }
