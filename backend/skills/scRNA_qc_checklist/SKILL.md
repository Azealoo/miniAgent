---
name: scRNA_qc_checklist
description: Turn single-cell RNA-seq summary metrics into a practical QC checklist with explicit assumptions and threshold recommendations.
category: bio/single_cell_rna
version: 1.0
requires_tools: [search_knowledge_base, python_repl]
requires_network: false
user_invocable: true
tags: [scrna, qc, mitochondrial, thresholds]
aliases: [single_cell_qc_checklist, scrna_threshold_helper]
species: any
modality: single_cell_rna
stage: qc
stability: stable
safety_level: low
---

# scRNA QC Checklist

## Purpose

Translate a dataset summary into a practical QC recommendation that is explicit about assumptions, red flags, and threshold tradeoffs.

## When to use

Use this skill when the user provides summary metrics such as cell counts, gene counts, UMI depth, and mitochondrial fraction and wants concrete QC guidance for scRNA-seq.

## Required inputs

- **n_cells**, **n_genes**, **median_umis** (or range), **mito_pct** (or range), **dataset_name** (optional)
- **platform or chemistry** (optional): 10x, plate-based, nuclei, or other context that affects threshold expectations

## Steps

1. Gather the provided metrics and restate any missing values or assumptions about platform, nuclei versus whole-cell prep, or expected cell states.
2. Use `search_knowledge_base` to look for local QC defaults or prior lab guidance when the project already has assay-specific thresholds.
3. Use `python_repl` to organize the supplied metrics, compare them against rough expected ranges, and compute any simple summaries that help justify thresholds.
4. Identify likely failure modes such as low complexity, high mitochondrial fraction, strong doublet risk, or over-aggressive filtering.
5. Recommend threshold ranges as starting points, not universal truths, and explain which metrics most strongly drive the recommendation.

## Output format

- **Biological context or assumptions**: platform, sample state, nuclei versus whole-cell, and any inferred QC baseline.
- **Evidence or source basis**: which `search_knowledge_base` defaults and `python_repl` metric checks supported the recommendation.
- **QC assessment**: metrics summary, red flags, and recommended thresholds for genes, UMIs, mitochondrial fraction, and doublet follow-up.
- **Caveats or ambiguity**: missing metrics, unusual assay design, or reasons the thresholds may need manual tuning.
- **Recommended next step**: what filter sweep, visualization, or replicate check to run next.

## Failure modes

- Too few metrics: ask for the missing counts rather than inventing a precise threshold.
- Unusual assay type: say when generic whole-cell defaults may not transfer to nuclei or plate-based data.
- Strong outlier structure: recommend visual QC review before hard filtering.

## Examples

- "Given 18,000 cells, median 1,400 genes, median 4,800 UMIs, and 14% mito, what QC cutoffs would you start with?"
- "Help me build a QC checklist for a nuclei RNA-seq pilot."
