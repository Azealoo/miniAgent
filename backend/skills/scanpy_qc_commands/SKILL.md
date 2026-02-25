---
name: scanpy_qc_commands
description: Suggest Scanpy/Python commands for basic scRNA QC (filtering, mito, UMI).
category: bio/scRNA
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# Scanpy QC Commands

## When to use
User wants ready-to-run Scanpy (or AnnData) code for QC: calculate_QC_metrics, filter cells/genes, normalize.

## Inputs
- **thresholds**: Optional mito_pct_max, min_genes, min_cells, etc.

## Steps

1. **Default thresholds**: If not given, use common defaults (e.g. mito < 20%, min_genes 200, min_cells 2).

2. **Code**: Use `python_repl` or output a code block with:
   - sc.pp.calculate_qc_metrics, filter_cells, filter_genes
   - Optional: sc.pp.normalize_total, log1p
   - Brief comments per step.

3. **Present**: Copy-pastable code and one-line note on adjusting thresholds.

## Output format
- Python code block (Scanpy)
- Short note on parameters
