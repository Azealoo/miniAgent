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

## References

- @context/features/13-qc-policy-layer-spec.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
- @context/features/18-report-bundle-v1-spec.md
- FastQC documentation
