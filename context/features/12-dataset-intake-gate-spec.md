# Dataset Intake Gate Spec

## Overview

Require structured dataset intake before analysis workflows are allowed to run. Biology pipelines fail or mislead when samples, references, contrasts, privacy flags, or batch variables are implicit. This phase makes those prerequisites explicit and blocks downstream analysis when essential metadata is missing.

## Requirements

- Define the minimum required fields for a valid analysis-ready dataset manifest.
- Require at least:
  - dataset ID
  - assay type
  - organism
  - reference build or reference resource
  - input file locations
  - sample sheet path
  - privacy classification
- For comparative analyses, require explicit design information such as condition fields and batch fields.
- Add validation that sample sheet references and input files actually exist before a workflow starts.
- Make missing critical metadata a hard block rather than a warning.
- Add a normalized error structure so the agent can tell the user exactly what is missing.
- Support future assay-specific extensions without changing the core gate contract.
- Ensure intake validation can run as a standalone preflight step before any heavy compute begins.

## References

- @backend/knowledge/data-and-pipeline-conventions.md
- @backend/skills/data_location_help/SKILL.md
- @backend/skills/run_pipeline_safely/SKILL.md
- @backend/skills/pseudobulk_design_helper/SKILL.md
- @backend/skills/batch_integration_advisor/SKILL.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/09-workflow-spec-format-spec.md
- @context/features/13-qc-policy-layer-spec.md
