---
name: protocol_from_knowledge
description: Retrieve a lab protocol or SOP from the local knowledge base and summarize the parts that matter for the current experiment.
category: bio/literature
version: 1.0
requires_tools: [search_knowledge_base, read_file]
requires_network: false
user_invocable: true
tags: [protocol, sop, wet-lab, knowledge-base]
aliases: [sop_lookup, procedure_finder]
species: any
modality: literature
stage: utilities
stability: stable
safety_level: low
---

# Protocol from Knowledge

## Purpose

Find the most relevant local protocol, pull the authoritative sections, and summarize the procedure without losing provenance.

## When to use

Use this skill when the user asks for a protocol, SOP, or "how we do X" and expects the answer to come from lab documentation rather than general web knowledge.

## Required inputs

- **query**: protocol name, assay, or topic
- **context** (optional): species, sample type, instrument, or kit if the lab uses multiple variants

## Steps

1. Restate the protocol intent and any important experimental assumptions such as assay type, sample, or kit version.
2. Use `search_knowledge_base` to locate the most relevant SOPs, playbooks, or method notes in `knowledge/`.
3. Use `read_file` on the top-matching document sections before summarizing any procedural detail.
4. Preserve the structure that matters to execution: materials, steps, checkpoints, warnings, and decision points.
5. If multiple protocol variants appear, explain the difference instead of merging them into one synthetic procedure.
6. Return the concise protocol with explicit source attribution, caveats, and the next action the biologist should take.

## Output format

- **Biological context or assumptions**: assay, sample type, platform, or other context used to pick the protocol variant.
- **Evidence or source basis**: which `search_knowledge_base` hit(s) and `read_file` sections the answer came from.
- **Protocol or checklist**: the relevant steps, materials, checkpoints, and decision notes.
- **Caveats or ambiguity**: conflicting SOP versions, missing reagent details, or context the user still needs to provide.
- **Recommended next step**: what to confirm, prepare, or run next.

## Failure modes

- No matching protocol: say that the knowledge base did not contain a confident SOP match.
- Multiple near-duplicate protocols: list the variants and the key distinction instead of picking one silently.
- Missing experiment context: ask for the assay, sample type, or platform before narrowing to one protocol.

## Examples

- "Find the Perturb-seq library prep SOP we use locally."
- "What is our RNA extraction protocol for frozen PBMC samples?"
