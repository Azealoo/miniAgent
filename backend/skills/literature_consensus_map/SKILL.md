---
name: literature_consensus_map
description: Summarize the current literature consensus, disagreements, and evidence strength for a biological question.
category: bio/literature
version: 1.0
requires_tools: [ncbi_eutils, search_knowledge_base, python_repl]
requires_network: true
user_invocable: true
tags: [literature, consensus, controversy, evidence-synthesis]
aliases: [consensus_builder, literature_synthesis]
species: any
modality: literature
stage: interpretation
stability: evolving
safety_level: medium
---

# Literature Consensus Map

## Purpose

Build a concise map of what the literature broadly agrees on, where disagreement remains, and how strong the evidence appears to be.

## When to use

Use this skill when the user asks for the current state of the field on a question, such as whether a pathway drives a phenotype or whether a target is well supported.

## Required inputs

- **question**: The biological claim, mechanism, or target of interest
- **context** (optional): species, tissue, disease, or experimental system

## Steps

1. Search `knowledge/` with `search_knowledge_base` for any local playbooks or prior notes on the topic.
2. Use `ncbi_eutils` to search PubMed with a focused query combining the main question and context.
3. Group findings into:
   - strong recurring claims
   - partial support or context-dependent findings
   - disagreement or uncertainty
4. Use `python_repl` if helpful to organize papers into a small evidence table.
5. Keep citations attached to the claims. Do not overstate consensus when evidence is sparse.

## Output format

- **Consensus summary**
- **Evidence table**: Claim | Support level | Example PMID(s) | Caveat
- **Open questions**

## Failure modes

- Too broad a question: ask the user to narrow the scope.
- Sparse literature: say the consensus is weak or preliminary.
- Mixed systems: separate conclusions by species or model rather than collapsing them.

## Examples

- "What is the literature consensus on TOX in T-cell exhaustion?"
- "Summarize the evidence for interferon signaling in melanoma resistance."
