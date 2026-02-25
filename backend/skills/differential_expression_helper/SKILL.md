---
name: differential_expression_helper
description: Interpret a differential expression table; flag batch confounders and suggest covariates.
category: bio/scRNA
version: 1.0
requires_tools: [read_file, python_repl]
requires_network: false
user_invocable: true
---

# Differential Expression Helper

## When to use
User shares a DE table (or path), or describes DE results, and wants interpretation or design advice.

## Inputs
- **table_path** (optional): Path to DE results file (CSV/TSV) under project.
- Or user pastes summary: condition, n_genes, top genes, method.

## Steps

1. **Load**: If path given, use `read_file` to read the file (or first N lines). Otherwise use user summary.

2. **Interpret**: Identify columns (gene, log2FC, p-value, FDR, condition). Note method (e.g. Wilcoxon, MAST, DESeq2).

3. **Confounders**: Ask or infer: Was batch/capture/sex included? Suggest adding batch as covariate if not mentioned.

4. **Summarize**: Top up/down genes, direction, and one sentence on biological interpretation. If table is large, summarize distribution (how many DE at FDR<0.05).

5. **Covariates**: Recommend covariates for future analysis if relevant (batch, cell cycle, n_genes).

## Output format
- Method and condition comparison
- Top DE genes (table or list)
- Batch/covariate recommendation
- Brief biological takeaway
