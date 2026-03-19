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

## References

- @backend/knowledge/pseudobulk-and-replicate-design.md
- @backend/skills/differential_expression_helper/SKILL.md
- @backend/skills/pseudobulk_design_helper/SKILL.md
- @backend/skills/batch_integration_advisor/SKILL.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
- @context/features/18-report-bundle-v1-spec.md
- DESeq2 documentation
