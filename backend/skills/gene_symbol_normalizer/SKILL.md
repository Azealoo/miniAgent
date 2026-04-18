---
name: gene_symbol_normalizer
description: Normalize gene symbols, aliases, and species context before downstream lookup or analysis.
category: bio/literature
version: 1.0
requires_tools: [ensembl_api, uniprot_api, python_repl]
requires_network: true
user_invocable: true
tags: [gene-symbol, alias, identifier, normalization]
aliases: [normalize_gene_symbol, gene_name_cleaner]
species: any
modality: literature
stage: utilities
stability: stable
safety_level: low
---

# Gene Symbol Normalizer

## Purpose

Resolve gene aliases, outdated symbols, species ambiguity, and mixed capitalization before any downstream biological interpretation.

## When to use

Use this skill when the user provides one or more gene names that may be aliases, old symbols, or mixed-species identifiers.

## Required inputs

- **genes**: one or more gene symbols, aliases, or identifiers
- **species** (optional): human, mouse, or another organism if the user already knows it

## Steps

1. Parse the input into a clean list of candidate gene names and restate any stated or inferred species assumptions.
2. Use `ensembl_api` as the primary source for canonical symbols, aliases, and organism mapping.
3. Use `uniprot_api` as a cross-check when alias families, protein naming, or species assignments remain unclear.
4. Use `python_repl` to assemble a compact normalization table with input term, canonical symbol, species, matched source, and ambiguity or confidence note.
5. Separate exact matches, likely alias matches, and unresolved collisions; do not silently choose between equally plausible species or symbols.
6. Return the normalized mapping together with the source basis, uncertainty, and the most useful downstream next step.

## Output format

- **Biological context or assumptions**: stated or inferred species, identifier type, and any naming assumptions.
- **Evidence or source basis**: which `ensembl_api` and `uniprot_api` results supported each normalization.
- **Normalized mapping**: Input | Canonical symbol | Species | Match type | Note
- **Caveats or ambiguity**: unresolved aliases, multi-species collisions, or low-confidence mappings.
- **Recommended next step**: suggest the next skill or lookup if helpful.

## Failure modes

- No confident match: report that the symbol could not be normalized and say which sources were checked.
- Multiple species match equally well: ask the user to specify species before choosing a canonical symbol.
- Alias collision: return all plausible mappings instead of choosing one blindly.

## Examples

- "Normalize these genes: P53, Trp53, Cdkn1a."
- "Are PD1 and PDCD1 the same gene?"
