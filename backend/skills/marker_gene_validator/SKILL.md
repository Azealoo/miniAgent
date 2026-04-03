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

- **markers**: a list of marker genes
- **proposed label**: cell type or state
- **context** (optional): species, tissue, disease, stimulation, or assay context

## Steps

1. Restate the proposed label, species, tissue, and disease or stimulation context because the same markers can mean different things across systems.
2. Search local guidance such as marker panel notes with `search_knowledge_base` before leaning on generic marker heuristics.
3. Use `ncbi_eutils` and `uniprot_api` to confirm unclear, surprising, or multifunctional markers when necessary.
4. Use `python_repl` to organize markers into strongly supportive, weakly supportive, and conflicting groups if the list is long.
5. Return a confidence judgment that clearly separates well-supported markers from context-dependent or contradictory ones.

## Output format

- **Biological context or assumptions**: proposed label, species, tissue, and any inferred activation or disease context.
- **Evidence or source basis**: which `search_knowledge_base`, `ncbi_eutils`, `uniprot_api`, and `python_repl` checks support the call.
- **Marker assessment**: supportive markers, conflicting markers, and confidence in the proposed label.
- **Caveats or ambiguity**: lineage overlap, activation-state confounding, or insufficient marker coverage.
- **Recommended next step**: what marker, modality, or follow-up validation would most reduce uncertainty.

## Failure modes

- Too few markers: say confidence is limited.
- Conflicting markers: return alternative labels or mixed-state possibilities.
- Broad label: ask for more context if the claim is underspecified.

## Examples

- "Do PDCD1, TOX, TIGIT, LAG3 support an exhausted CD8 T-cell label?"
- "Are these markers enough to call this cluster macrophages?"
