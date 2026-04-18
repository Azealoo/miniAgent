---
name: differential_expression_helper
description: Interpret a differential expression result with replicate-aware context, likely confounders, and the next analysis decision.
category: bio/single_cell_rna
version: 1.0
requires_tools: [read_file, search_knowledge_base, python_repl]
requires_network: false
user_invocable: true
tags: [differential-expression, covariates, scrna, confounders]
aliases: [de_result_helper, de_table_interpreter]
species: any
modality: single_cell_rna
stage: analysis
stability: stable
safety_level: low
---

# Differential Expression Helper

## Purpose

Interpret a DE result in biological context, call out common design pitfalls, and recommend the next validation or modeling step.

## When to use

Use this skill when the user shares a DE table or a summary of DE results and wants interpretation, covariate guidance, or help deciding whether the comparison is trustworthy.

## Required inputs

- **table_path** (optional): path to DE results under the project workspace
- or a pasted summary including condition, top genes, direction, and method
- **design context** (optional): replicate structure, batch variables, cell grouping, and method used

## Steps

1. Load the DE table with `read_file` when a file path is available, otherwise structure the user-provided summary explicitly.
2. Identify the comparison, method, and critical columns, then use `python_repl` to summarize top hits, effect-size spread, and how many genes pass the stated cutoff.
3. Use `search_knowledge_base` for local design guidance such as pseudobulk, replicate handling, or covariate expectations when that context exists in the project.
4. Call out likely confounders such as batch, donor, cell cycle, capture lane, or imbalanced library complexity.
5. Return the biological interpretation together with limits of the current model and a clear next analysis recommendation.

## Output format

- **Biological context or assumptions**: comparison, replicate unit, modeling method, and any assumed covariates.
- **Evidence or source basis**: which `read_file`, `search_knowledge_base`, and `python_repl` checks the interpretation relied on.
- **DE interpretation**: top genes, directionality, and what the pattern likely means biologically.
- **Caveats or ambiguity**: missing covariates, poor replication, or design features that weaken the conclusion.
- **Recommended next step**: what model refinement, validation, or follow-up analysis to run next.

## Failure modes

- No readable DE table: say which file or columns were missing.
- Missing replicate or batch context: label the interpretation as provisional.
- Overly broad result table: summarize the main signal and ask for the target comparison if needed.

## Examples

- "Interpret this DE table for exhausted versus effector-like CD8 T cells."
- "What covariates should I add before trusting these pseudobulk DE results?"
