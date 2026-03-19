# External Workflow Adapter V1 Spec

## Overview

Connect the internal orchestration layer to an external workflow engine without surrendering artifact control, provenance, or safety checks. This phase should let the backend launch standardized pipelines while continuing to own metadata, run records, and compliance behavior.

## Requirements

- Define the adapter interface between internal workflow runs and external engines.
- Support at least one external engine in v1, with the design open to both Nextflow and Snakemake.
- Require the adapter to map:
  - dataset manifest inputs
  - workflow parameters
  - execution profile
  - output artifact locations
  - job records
- Ensure the backend remains the system of record for run status and generated artifacts.
- Make external engine invocation reproducible by recording exact command, version, profile, and environment references.
- Prevent the adapter from bypassing dataset intake, QC policy, or compliance gates.
- Define how failures from the external engine are normalized into workflow step failures.

## References

- @backend/tools/slurm_tool.py
- @backend/skills/analysis_to_slurm_runner/SKILL.md
- @backend/skills/run_pipeline_safely/SKILL.md
- @context/features/09-workflow-spec-format-spec.md
- @context/features/10-internal-dag-runner-mvp-spec.md
- @context/features/29-slurm-run-manager-upgrade-spec.md
- Nextflow documentation
- Snakemake documentation
