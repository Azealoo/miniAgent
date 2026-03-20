"""Sample Python executors for the perturb-seq workflow."""

from __future__ import annotations

from dataset_intake import ensure_valid_dataset_intake_manifest


def validate_inputs(inputs, context):
    result = ensure_valid_dataset_intake_manifest(
        context.base_dir,
        inputs["dataset_manifest"],
        expected_reference_build=inputs["reference_build"],
    )
    return {"validated_manifest": result.manifest_path}


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
