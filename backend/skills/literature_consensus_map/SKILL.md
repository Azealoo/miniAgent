---
name: literature_consensus_map
description: Summarize the current literature consensus, disagreements, and evidence strength for a biological question.
category: bio/literature
version: 1.0
requires_tools: [search_knowledge_base, evidence_retrieval, evidence_review, python_repl]
requires_network: true
user_invocable: true
tags: [literature, consensus, controversy, evidence-synthesis]
aliases: [consensus_builder, literature_synthesis]
species: any
modality: literature
stage: interpretation
stability: stable
safety_level: medium
---

# Literature Consensus Map

## Purpose

Build a concise map of what the literature broadly agrees on, where disagreement remains, and how strong the evidence appears to be.

## When to use

Use this skill when the user asks for the current state of the field on a question, such as whether a pathway drives a phenotype or whether a target is well supported.

## Required inputs

- **question**: the biological claim, mechanism, or target of interest
- **context** (optional): species, tissue, disease, or experimental system

## Steps

1. Restate the biological question and the key scope assumptions such as species, tissue, disease, and perturbation context.
2. Search `knowledge/` with `search_knowledge_base` for local notes, prior evidence syntheses, or project-specific framing.
3. Use `evidence_retrieval` to gather a bounded set of relevant PubMed-backed evidence cards for the question.
4. Use `evidence_review` to separate supported conclusions, unresolved conflicts, and explicit unsupported claims when the evidence is thin.
5. Use `python_repl` if helpful to organize the included studies into a small comparison table.
6. Keep citations attached to claims and do not overstate consensus when the literature is sparse or context-dependent.

## Output format

- **Biological context or assumptions**: species, system, disease, and scope used to judge consensus.
- **Evidence or source basis**: which `search_knowledge_base`, `evidence_retrieval`, and `evidence_review` artifacts supported the summary.
- **Consensus map**: strong recurring claims, context-dependent findings, and disagreement or uncertainty.
- **Caveats or ambiguity**: weak evidence base, unresolved conflicts, or questions that remain unsupported.
- **Recommended next step**: what evidence gap to resolve, experiment to prioritize, or narrower follow-up question to ask.

## Failure modes

- Too broad a question: ask the user to narrow the scope.
- Sparse literature: say the consensus is weak or preliminary.
- Mixed systems: separate conclusions by species or model rather than collapsing them.

## Examples

- "What is the literature consensus on TOX in T-cell exhaustion?"
- "Summarize the evidence for interferon signaling in melanoma resistance."
