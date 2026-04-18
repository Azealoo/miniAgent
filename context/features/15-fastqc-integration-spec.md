# FastQC Integration Spec

## Overview

Integrate FastQC as the first concrete QC tool in the workflow system. This phase should make raw-read quality assessment mandatory and structured, not an optional side report. The goal is to produce both the original FastQC outputs and normalized QC artifacts that later gates and reports can consume.

## Requirements

- Add a workflow step definition for running FastQC on declared FASTQ inputs.
- Support single-end and paired-end inputs if the dataset manifest distinguishes them.
- Capture FastQC invocation parameters, tool version, input file hashes, and output paths.
- Store original FastQC outputs and a normalized extracted metrics artifact.
- Define which FastQC findings map to pass, warn, or fail in the QC policy layer.
- Ensure failed FastQC execution is distinct from poor QC results.
- Make the run record point to all generated FastQC artifacts.
- Add at least one parser or adapter that converts FastQC outputs into machine-readable QC metrics.

## Authored Contract

- The RNA-seq workflow should resolve FastQC inputs from `dataset_manifest.sample_sheet_path` using explicit `sample_id`, `fastq_r1`, and optional `fastq_r2` columns.
- The authored sample-sheet contract currently requires one row per `sample_id`; duplicate `sample_id` rows should fail validation instead of being merged implicitly.
- A missing or malformed FastQC sample-sheet contract should block the `raw_qc` step before downstream stages continue.
- The `raw_qc` step should emit:
  - a structured `raw_qc_bundle` value used for QC gating
  - a durable `fastqc_run` artifact with command provenance, tool version, input hashes, and raw report paths
  - a durable `fastqc_metrics` artifact with normalized parsed metrics extracted from FastQC archives
- Workflow-level outputs should surface `fastqc_run` and `fastqc_metrics` so the persisted `workflow_run` record points directly to the FastQC artifacts.
- FastQC execution failures should surface as workflow step failures or blocks, while poor-quality but successfully parsed FastQC results should complete the step and fail later through QC policy evaluation.
- The normalized metrics artifact should provide at least:
  - `min_per_base_quality`
  - `total_reads_millions`
  - `fastqc_pass_rate`
  - per-report module pass/warn/fail states parsed from FastQC output

## References

- @context/features/13-qc-policy-layer-spec.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
- @context/features/18-report-bundle-v1-spec.md
- FastQC documentation
