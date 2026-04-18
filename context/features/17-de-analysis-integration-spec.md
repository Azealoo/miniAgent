# Differential Expression Analysis Integration Spec

## Overview

Add the explicit differential expression stage to the RNA-seq workflow. This phase should make design metadata, contrasts, and batch handling first-class inputs, and it should emit structured results plus interpretation-ready artifacts without hiding assumptions.

## Requirements

- Require design metadata before this step can execute.
- Require explicit contrast definitions and design formula or equivalent structured model.
- Record the exact analysis engine, version, and parameters used.
- Produce canonical outputs:
  - differential expression results table
  - normalized counts or supporting matrix if needed
  - diagnostic plots
  - step-level summary artifact
- Ensure the run record includes the source count matrix and the contrast metadata used.
- Add warnings or blocks when batch variables are missing in datasets where they are expected.
- Distinguish technical step failure from biologically questionable design.
- Define expected downstream links into report bundles and QA review.

## Authored Contract

- Keep the workflow ID as `rnaseq_qc_de` and preserve the explicit `quantification` and `differential_expression` stage boundaries.
- Materialize a durable `count_matrix` artifact plus gene-count TSV in `quantification` so DE consumes a concrete source matrix instead of a placeholder path.
- Materialize durable `normalized_count_matrix`, `differential_expression_results`, and `differential_expression_run` artifacts in `differential_expression`, alongside concrete diagnostic plot files and the existing DE bundle value output.
- Record the exact internal engines and parameters used:
  - `bioapex_deterministic_quantification@1.0.0` for synthetic count-matrix generation
  - `bioapex_mean_centered_t_test@1.0.0` for transparent normalized-count generation and DE scoring
- Derive the explicit DE design model from the dataset manifest design metadata, sample-sheet columns, and requested contrast:
  - persisted `design_formula`
  - modeled factors
  - expected/modeled/missing batch fields
  - replicate counts per condition
- Surface design-quality concerns through a post-DE QC gate instead of collapsing them into generic step failures:
  - warn when one expected batch field is missing
  - block when multiple expected batch fields are missing
  - warn/block on low replicate counts according to the authored QC thresholds
- Wire the report bundle stage to link the canonical count matrix, normalized counts, DE results table, DE run summary, and diagnostic plots, and keep QA review focused on remaining design warnings rather than placeholder missing artifacts.

## References

- @backend/knowledge/pseudobulk-and-replicate-design.md
- @backend/skills/differential_expression_helper/SKILL.md
- @backend/skills/pseudobulk_design_helper/SKILL.md
- @backend/skills/batch_integration_advisor/SKILL.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
- @context/features/18-report-bundle-v1-spec.md
- DESeq2 documentation
