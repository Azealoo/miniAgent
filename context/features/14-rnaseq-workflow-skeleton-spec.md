# RNA-seq Workflow Skeleton Spec

## Overview

Create the first explicit biology workflow that proves the new workflow layer can represent a common end-to-end analysis task. This phase is about structure, contracts, and orchestration. It should not assume every downstream tool integration is finished yet.

## Requirements

- Define a workflow named something like `rnaseq_qc_de`.
- Require the workflow to declare these logical stages:
  - dataset intake
  - compliance preflight
  - raw QC
  - aggregated QC
  - quantification or count generation
  - differential expression
  - report bundle creation
- Define the required user-supplied inputs and their schema references.
- Define the expected output artifacts even if some steps are stubbed initially.
- Require step boundaries to be explicit so later FastQC, MultiQC, DE, and provenance integrations can plug in cleanly.
- Ensure the workflow can fail early if intake, QC, or compliance gates do not pass.
- Add one example manifest and one example workflow plan to the spec.

## References

- @backend/knowledge/data-and-pipeline-conventions.md
- @backend/skills/run_pipeline_safely/SKILL.md
- @backend/skills/analysis_to_slurm_runner/SKILL.md
- @context/features/09-workflow-spec-format-spec.md
- @context/features/10-internal-dag-runner-mvp-spec.md
- @context/features/15-fastqc-integration-spec.md
- @context/features/16-multiqc-integration-spec.md
- @context/features/17-de-analysis-integration-spec.md
- nf-core/rnaseq documentation
