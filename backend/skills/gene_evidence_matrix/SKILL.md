---
name: gene_evidence_matrix
description: Build an evidence matrix linking a gene list to a phenotype, pathway, or biological question using literature and local knowledge.
category: bio/literature
version: 1.0
requires_tools: [ncbi_eutils, uniprot_api, search_knowledge_base, python_repl]
requires_network: true
user_invocable: true
tags: [evidence, gene-list, phenotype, matrix, literature]
aliases: [evidence_table_builder]
species: any
modality: literature
stage: interpretation
stability: evolving
safety_level: medium
---

# Gene Evidence Matrix

## Purpose

Summarize how strongly each gene in a list is supported by literature or local knowledge for a specific phenotype, pathway, or mechanism.

## When to use

Use this skill when the user wants to compare several candidate genes against one biological question, such as exhaustion, apoptosis, interferon response, or cytokine signaling.

## Required inputs

- **genes**: Candidate genes
- **question**: The phenotype, pathway, or mechanism of interest
- **species** (optional)

## Steps

1. Normalize the gene list if needed.
2. Use `search_knowledge_base` for any local protocol, note, or playbook relevant to the question.
3. For each gene, use `ncbi_eutils` to search the gene plus the question.
4. Use `uniprot_api` for a concise function check when needed.
5. Use `python_repl` to assemble an evidence matrix with fields such as:
   - gene
   - evidence strength
   - mechanism hint
   - representative PMID or source
   - main caveat
6. Rank genes cautiously. Distinguish strong evidence from plausible speculation.

## Output format

- **Evidence matrix**: Gene | Evidence strength | Mechanism hint | Source | Caveat
- **Top supported genes**
- **Low-confidence or conflicting genes**

## Failure modes

- Sparse literature: say the matrix is preliminary.
- Conflicting evidence: keep both sides visible instead of forcing a consensus.
- Very large gene lists: summarize the top subset and suggest batching.

## Examples

- "Build an evidence matrix for TOX, PDCD1, TIGIT, IFNG against T-cell exhaustion."
- "Which of these genes have evidence for interferon response activation?"
