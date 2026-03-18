---
name: pseudobulk_design_helper
description: Recommend a replicate-aware pseudobulk strategy for single-cell differential expression and explain the design choices.
category: bio/single_cell_rna
version: 1.0
requires_tools: [search_knowledge_base, python_repl]
requires_network: false
user_invocable: true
tags: [pseudobulk, differential-expression, replicates, design]
aliases: [replicate_aware_de_helper]
species: any
modality: single_cell_rna
stage: analysis
stability: stable
safety_level: low
---

# Pseudobulk Design Helper

## Purpose

Help the user decide when and how to use pseudobulk for replicate-aware differential expression from single-cell data.

## When to use

Use this skill when the user asks about differential expression across conditions, donors, mice, or samples and needs guidance on the right unit of replication.

## Required inputs

- **comparison**: The intended contrast, such as condition A vs condition B
- **replication unit**: donor, mouse, sample, culture, or unknown
- **cell grouping**: cell type, cluster, or state if relevant

## Steps

1. Search `knowledge/pseudobulk-and-replicate-design.md` with `search_knowledge_base`.
2. Identify the true biological replicate and the grouping level for aggregation.
3. Explain whether pseudobulk is preferred, optional, or not well supported by the design.
4. Use `python_repl` if you need to organize a small design table or compare aggregation options.
5. Recommend sensible outputs such as sample-by-cell-type counts, minimum cell thresholds, and key covariates.

## Output format

- **Recommended aggregation unit**
- **Recommended design formula or covariates**
- **Cell-count cautions**
- **Interpretation note**

## Failure modes

- No replicate information: say that formal replicate-aware inference is limited.
- Unclear comparison: ask the user what groups they want to compare.
- Too few cells per sample-group combination: warn that results may be unstable.

## Examples

- "Should I use pseudobulk for DE across donors in my scRNA-seq data?"
- "How should I design DE for condition A vs B within CD8 T cells?"
