---
name: gene_list_annotation_table
description: Build a compact annotation table for a gene list using canonical identifiers, species, function, and caveats.
category: bio/literature
version: 1.0
requires_tools: [uniprot_api, ensembl_api, python_repl]
requires_network: true
user_invocable: true
tags: [gene-list, annotation, summary, table]
aliases: [annotate_gene_list]
species: any
modality: literature
stage: analysis
stability: stable
safety_level: low
---

# Gene List Annotation Table

## Purpose

Turn a raw gene list into a structured table that is easier to interpret and use in downstream analysis or discussion.

## When to use

Use this skill when the user has a list of genes from DE, marker selection, screen hits, or literature curation and wants a first-pass annotation.

## Required inputs

- **genes**: A gene list
- **species** (optional but recommended)
- **focus** (optional): for example function, localization, or whether the genes are secreted, transcription factors, or receptors

## Steps

1. Clean and deduplicate the gene list.
2. Normalize symbols if needed.
3. Use `uniprot_api` and `ensembl_api` to collect concise annotations such as:
   - canonical symbol
   - species
   - biotype or protein status
   - one-line function
4. Use `python_repl` to assemble a clean table and preserve input order when useful.
5. Highlight genes that are ambiguous, unmapped, or likely aliases.

## Output format

- **Annotation table**: Input | Canonical symbol | Species | Type | Short function | Notes
- **Summary**: 2 to 4 sentences on broad patterns in the list

## Failure modes

- Too many genes for manual detail: provide a compact table and say deeper review may need batching.
- Unmapped genes: list them separately.
- Mixed species list: flag this clearly.

## Examples

- "Annotate this gene list: IFNG, GZMB, PDCD1, TOX, CXCL13."
- "Build a concise annotation table for these perturbation hits."
