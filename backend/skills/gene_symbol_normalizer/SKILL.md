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

- **genes**: One or more gene symbols, aliases, or identifiers.
- **species** (optional): Human, mouse, or another organism if the user already knows it.

## Steps

1. Parse the input into a clean list of candidate gene names.
2. If species is unclear, infer it cautiously from context and say when the species remains ambiguous.
3. Use `ensembl_api` and `uniprot_api` to confirm canonical symbols, known aliases, and organism.
4. Use `python_repl` to assemble a clean table with:
   - input term
   - normalized symbol
   - species
   - matched source
   - confidence or ambiguity note
5. If multiple plausible mappings exist, do not guess. Return the ambiguous options clearly.

## Output format

- **Normalized table**: Input | Canonical symbol | Species | Notes
- **Ambiguities**: List any symbols that need user confirmation
- **Recommended next step**: Suggest the next skill if helpful

## Failure modes

- No confident match: report that the symbol could not be normalized.
- Multiple species match equally well: ask the user to specify species.
- Alias collision: return all plausible mappings instead of choosing one blindly.

## Examples

- "Normalize these genes: P53, Trp53, Cdkn1a."
- "Are PD1 and PDCD1 the same gene?"
