---
name: ortholog_mapper
description: Map genes across species and explain confidence, ambiguity, and biological caveats.
category: bio/literature
version: 1.0
requires_tools: [ensembl_api, uniprot_api, python_repl]
requires_network: true
user_invocable: true
tags: [ortholog, human, mouse, species-mapping]
aliases: [cross_species_mapper]
species: any
modality: literature
stage: utilities
stability: stable
safety_level: low
---

# Ortholog Mapper

## Purpose

Map a gene or gene list between species, typically human and mouse, while warning about one-to-many mappings or missing orthologs.

## When to use

Use this skill when the user wants to translate markers, targets, or candidate genes between species.

## Required inputs

- **genes**: One or more genes in the source species.
- **source species**
- **target species**

## Steps

1. Normalize the input genes first if aliases are likely.
2. Use `ensembl_api` as the primary source for ortholog information.
3. Use `uniprot_api` when you need an additional check on gene or protein naming.
4. Use `python_repl` to format a mapping table:
   - source gene
   - target ortholog
   - mapping type or confidence
   - caveat
5. If a one-to-many or many-to-many relationship appears, say so explicitly.

## Output format

- **Mapping table**: Source gene | Target ortholog | Confidence | Caveat
- **Unmapped genes**: list if any
- **Interpretation note**: one short paragraph on how cautious the user should be

## Failure modes

- No ortholog found: report it explicitly.
- Ambiguous mapping: show all plausible mappings.
- Species missing: ask the user to specify source and target species.

## Examples

- "Map these human genes to mouse orthologs: PDCD1, TIGIT, LAG3."
- "What is the mouse ortholog of CXCL8?"
