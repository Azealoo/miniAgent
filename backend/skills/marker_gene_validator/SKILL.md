---
name: marker_gene_validator
description: Validate whether a marker set supports a proposed cell type or cell state and explain the main caveats.
category: bio/single_cell_rna
version: 1.0
requires_tools: [search_knowledge_base, ncbi_eutils, uniprot_api, python_repl]
requires_network: true
user_invocable: true
tags: [markers, validation, annotation, cell-state]
aliases: [marker_panel_validator]
species: any
modality: single_cell_rna
stage: annotation
stability: stable
safety_level: low
---

# Marker Gene Validator

## Purpose

Check whether a proposed marker set really supports the claimed cell identity or state.

## When to use

Use this skill when the user already has a marker panel or top DE genes and wants to know whether the label is convincing.

## Required inputs

- **markers**: A list of marker genes
- **proposed label**: Cell type or state
- **context** (optional): species, tissue, disease, stimulation

## Steps

1. Search local guidance such as `marker-panel-guidelines.md` with `search_knowledge_base`.
2. Use `ncbi_eutils` and `uniprot_api` to confirm unclear or surprising markers when necessary.
3. Separate markers into:
   - strongly supportive
   - weakly supportive
   - conflicting or suspicious
4. Use `python_repl` if useful to organize the marker evidence table.
5. Return a confidence judgment with explicit caveats.

## Output format

- **Proposed label**
- **Supportive markers**
- **Conflicting markers**
- **Confidence**
- **Alternative interpretations**

## Failure modes

- Too few markers: say confidence is limited.
- Conflicting markers: return alternative labels or mixed-state possibilities.
- Broad label: ask for more context if the claim is underspecified.

## Examples

- "Do PDCD1, TOX, TIGIT, LAG3 support an exhausted CD8 T-cell label?"
- "Are these markers enough to call this cluster macrophages?"
