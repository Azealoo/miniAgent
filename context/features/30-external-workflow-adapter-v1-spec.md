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

## Implementation Notes

- The v1 adapter contract should stay inside the existing `external_engine` executor surface rather than introducing a parallel orchestration layer.
- Structured Nextflow and Snakemake adapters should declare:
  - `engine_name`
  - `entrypoint`
  - `execution_profile`
  - `parameter_bindings`
  - `environment_references`
  - `output_locations`
  - `engine_version` or `version_command`
- BioAPEX should persist launch metadata on the corresponding `workflow_run` step record so the workflow artifact remains the system of record even when the external engine is the one performing the computation.
- When the execution profile delegates to Slurm, the adapter should reuse the structured `slurm_job` path instead of falling back to opaque shell submission.

## References

- @backend/tools/slurm_tool.py
- @backend/skills/analysis_to_slurm_runner/SKILL.md
- @backend/skills/run_pipeline_safely/SKILL.md
- @context/features/09-workflow-spec-format-spec.md
- @context/features/10-internal-dag-runner-mvp-spec.md
- @context/features/29-slurm-run-manager-upgrade-spec.md
- Nextflow documentation
- Snakemake documentation
