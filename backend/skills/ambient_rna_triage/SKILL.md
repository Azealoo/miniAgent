---
name: ambient_rna_triage
description: Triage whether ambient RNA contamination is a plausible explanation for suspicious single-cell expression patterns.
category: bio/single_cell_rna
version: 1.0
requires_tools: [search_knowledge_base, python_repl]
requires_network: false
user_invocable: true
tags: [ambient-rna, soup, contamination, triage]
aliases: [ambient_contamination_check]
species: any
modality: single_cell_rna
stage: qc
stability: stable
safety_level: low
---

# Ambient RNA Triage

## Purpose

Assess whether ambient RNA contamination is a likely contributor to unexpected marker expression or noisy cluster interpretation.

## When to use

Use this skill when the user reports improbable marker expression, broad low-level contamination, or suspicious signals in droplet-based single-cell data.

## Required inputs

- **observed problem**: for example unexpected markers across many clusters
- **data context**: droplet-based or not, sample quality, and any known QC issues
- **suspect genes** (optional)

## Steps

1. Search `knowledge/ambient-rna-troubleshooting.md` with `search_knowledge_base`.
2. Compare the reported symptoms against common ambient RNA patterns.
3. Distinguish ambient RNA from related explanations such as doublets or real activation states.
4. Use `python_repl` only if you need to organize a checklist or risk table.
5. Recommend next checks such as low-count cell review, marker sanity checks, or SoupX/CellBender.

## Output format

- **Assessment**: suspected, plausible, or not strongly supported
- **Why**
- **Most informative next checks**
- **Main interpretation risk**

## Failure modes

- Too little context: ask whether the data are droplet-based and which genes look suspicious.
- Strong alternative explanation: say ambient RNA is not the main hypothesis.
- No suspect genes given: keep the answer high-level and diagnostic.

## Examples

- "Could ambient RNA explain albumin expression across unrelated cell types?"
- "I see low-level hemoglobin genes in many cells. Is this ambient contamination?"
