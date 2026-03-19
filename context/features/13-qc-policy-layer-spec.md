# QC Policy Layer Spec

## Overview

Define reusable quality-control policies that workflows must satisfy before they are allowed to continue into interpretation or inference. This phase should make QC rules explicit, configurable, and auditable. The focus is not on implementing every assay-specific metric immediately. The focus is establishing the rule layer that later workflow steps must obey.

## Requirements

- Define a QC policy object that can be attached to a workflow run or dataset manifest.
- Support pass, warn, and fail states for individual QC checks.
- Allow policies to declare required upstream QC tools and expected metrics.
- Define how policies attach to workflow steps and how failures stop downstream steps.
- Require each QC result to capture:
  - metric name
  - observed value
  - threshold
  - status
  - source artifact
- Support an assay-specific override mechanism without changing the runner core.
- Ensure QC outcomes are reflected in both the run record and a human-readable summary.
- Define how batch-effect warnings or experimental design warnings are surfaced distinctly from technical QC failures.
- Add at least one concrete policy example suitable for transcriptomics or single-cell analysis.

## References

- @backend/knowledge/scRNA-QC-SOP.md
- @backend/knowledge/analysis-playbook-scanpy-seurat.md
- @backend/knowledge/batch-integration-playbook.md
- @backend/knowledge/pseudobulk-and-replicate-design.md
- @backend/skills/scRNA_qc_checklist/SKILL.md
- @backend/skills/batch_integration_advisor/SKILL.md
- @context/features/12-dataset-intake-gate-spec.md
- @context/features/15-fastqc-integration-spec.md
- @context/features/16-multiqc-integration-spec.md
