---
name: scRNA_qc_checklist
description: Given dataset summary (cells, genes, UMIs, mito%), produce a QC report and recommended thresholds.
category: bio/scRNA
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# scRNA QC Checklist

## When to use
User describes or pastes summary stats (n_cells, n_genes, UMIs per cell, mitochondrial %) and wants QC guidance.

## Inputs
- **n_cells**, **n_genes**, **median_umis** (or range), **mito_pct** (or range), **dataset_name** (optional)

## Steps

1. **Gather**: Extract or ask for: number of cells, number of genes, UMI counts per cell (median/range), mitochondrial percentage (median/range).

2. **Assess**: Compare to typical expectations:
   - Low UMI/cell: possible cell damage or empty droplets.
   - High mito%: often >10–20% suggests stressed/dying cells.
   - Very low n_genes/cell: possible empty or debris.

3. **Recommend**: Suggest:
   - UMI min/max (e.g. 500–50,000) if not given.
   - Mito% ceiling (e.g. 10–20%).
   - Whether to filter doublets (mention tools if relevant).

4. **Output**: Short QC report: metrics received, red flags, recommended thresholds, and optional Scanpy/Seurat-style filter suggestions.

## Output format
- **Metrics summary**: As provided.
- **Red flags**: List if any.
- **Recommended thresholds**: UMI, genes, mito%.
- **Optional**: One-line filter command suggestion.
