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

## References

- @context/features/13-qc-policy-layer-spec.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
- @context/features/15-fastqc-integration-spec.md
- @context/features/18-report-bundle-v1-spec.md
- MultiQC documentation
