# MultiQC Integration Spec

## Overview

Integrate MultiQC as the standard aggregation layer for QC outputs. This phase should turn per-sample QC results into a single report and a normalized metrics summary that downstream workflow logic, QA, and users can review quickly.

## Requirements

- Add a workflow step definition for MultiQC after one or more QC-producing steps.
- Ensure the step can discover the relevant upstream QC outputs from the workflow run context.
- Store the original `multiqc_report.html` and a machine-readable extracted metrics artifact.
- Define which summary metrics should be copied into the workflow run record for quick inspection.
- Require the report bundle phase to link to the MultiQC report.
- Ensure MultiQC failures do not silently pass; the workflow must record whether aggregation failed or QC itself failed.
- Support re-running MultiQC without rerunning expensive upstream steps when artifacts already exist.

## Authored Contract

- The RNA-seq workflow should keep `aggregated_qc` as a distinct stage in `workflows/rnaseq_qc_de.yaml`, but that stage should now execute MultiQC concretely rather than return placeholder artifact paths.
- `aggregated_qc` should discover its upstream inputs from the persisted FastQC stage outputs, using the durable `fastqc_run` artifact to locate the generated FastQC report directory and the durable `fastqc_metrics` artifact to populate normalized summary metrics.
- The `aggregated_qc` step should emit:
  - a structured `aggregated_qc_bundle` value used for QC gating and downstream report assembly
  - a durable `multiqc_run` artifact with command provenance, tool version, input directories, report paths, and links back to the upstream FastQC artifacts
  - a durable `multiqc_metrics` artifact with normalized summary metrics and extracted report metadata
- Workflow-level outputs should surface `multiqc_run` and `multiqc_metrics` so the persisted `workflow_run` record points directly to the MultiQC artifacts at stable run-root paths.
- The normalized MultiQC metrics artifact should provide at least:
  - `fastqc_pass_rate`
  - `total_reads_millions`
  - `min_per_base_quality`
  - `report_sample_count`
  - the discovered MultiQC report modules and sample names when those can be extracted from the generated report data
- MultiQC execution or parsing failures should block as stage failures, while poor-but-successful aggregated QC results should complete the step and then fail through the existing `aggregated-qc-floor` QC policy gate.
- The report bundle stage should link to the generated `multiqc_report.html` instead of treating MultiQC output as a future placeholder.

## References

- @context/features/13-qc-policy-layer-spec.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
- @context/features/15-fastqc-integration-spec.md
- @context/features/18-report-bundle-v1-spec.md
- MultiQC documentation
