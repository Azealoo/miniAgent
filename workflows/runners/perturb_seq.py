"""Sample Python executors for the perturb-seq workflow."""

from __future__ import annotations

from artifacts import load_artifact_document


def validate_inputs(inputs, context):
    manifest_path = context.resolve_path(inputs["dataset_manifest"])
    manifest = load_artifact_document(manifest_path)
    if manifest.artifact_type != "dataset_manifest":
        raise ValueError("Perturb-seq preflight requires a dataset_manifest artifact.")
    return {"validated_manifest": context.relative_path(manifest_path)}


def summarize_outputs(inputs, _context):
    external_outputs = inputs["external_outputs_bundle"]
    stdout_text = str(external_outputs.get("stdout", "")).strip()
    warnings = [] if stdout_text else ["External engine completed without stdout output."]
    remediation = [] if stdout_text else ["Inspect the external engine logs before publication."]
    return {
        "qa_report": {
            "overall_status": "warning" if warnings else "passed",
            "failed_checks": [],
            "warnings": warnings,
            "missing_artifacts": [],
            "recommended_remediation": remediation,
            "checklist_artifacts": [],
        }
    }
