---
name: marker_panel_builder
description: Build positive and negative marker panels for a cell type or state and explain the confidence of the proposed panel.
category: bio/single_cell_rna
version: 1.0
requires_tools: [search_knowledge_base, ncbi_eutils, uniprot_api, python_repl]
requires_network: true
user_invocable: true
tags: [markers, annotation, panel, cell-type]
aliases: [build_marker_panel]
species: any
modality: single_cell_rna
stage: annotation
stability: evolving
safety_level: low
---

# Marker Panel Builder

## Purpose

Construct a marker panel that supports cell type or cell state annotation using both positive and negative markers.

## When to use

Use this skill when the user wants marker suggestions for cluster annotation, validation assays, or a shortlist of distinguishing genes.

## Required inputs

- **target label**: Cell type, state, or activation program
- **species** (recommended)
- **context** (optional): tissue, disease, stimulation, modality

## Steps

1. Search `knowledge/marker-panel-guidelines.md` and any relevant local references with `search_knowledge_base`.
2. Use `ncbi_eutils` and `uniprot_api` to confirm representative markers when needed.
3. Build a panel with:
   - positive markers
   - negative markers
   - context-sensitive or optional markers
4. Use `python_repl` if a structured table helps organize the panel.
5. Explain caveats such as overlapping markers, activation effects, or species dependence.

## Output format

- **Proposed label**
- **Positive markers**
- **Negative markers**
- **Confidence**
- **Main caveats**

## Failure modes

- Broad target label: ask for tissue or lineage context if needed.
- Conflicting literature: return the uncertainty explicitly.
- Very niche state: provide a provisional panel and say validation is needed.

## Examples

- "Build a marker panel for exhausted CD8 T cells."
- "What markers should I use to distinguish monocytes from macrophages?"
