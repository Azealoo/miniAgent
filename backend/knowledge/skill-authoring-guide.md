# Biology Skill Authoring Guide

Use this guide when creating or revising `skills/<skill_name>/SKILL.md`.

## Goal

Write skills that are easy for an LLM agent to discover, read, and execute reliably.

## Required frontmatter

Every production skill should define:

```yaml
---
name: example_skill
description: One-sentence summary of what the skill does.
category: bio/literature
version: 1.0
requires_tools: [read_file, python_repl]
requires_network: false
user_invocable: true
---
```

## Recommended frontmatter for biology skills

Add these when they improve retrieval or routing:

```yaml
tags: [genes, evidence, annotation]
aliases: [alternate_name, short_name]
species: human
modality: single_cell_rna
stage: analysis
stability: stable
safety_level: low
```

Field guidance:
- `category`: broad domain, such as `bio/literature`, `bio/single_cell_rna`, `bio/perturb_seq`, `bio/molecular_lab`, `bio/compute`
- `stage`: workflow step such as `design`, `qc`, `analysis`, `interpretation`, `validation`, `reporting`, `utilities`
- `stability`: `stable`, `evolving`, or `experimental`
- `safety_level`: `low`, `medium`, or `high`

## Preferred body template

```md
# Skill Title

## Purpose
One paragraph describing the job of the skill.

## When to use
Bullet points or a short paragraph describing the right user intents.

## Required inputs
- Input 1
- Input 2

## Steps
1. Read or gather the required inputs.
2. Use the expected tools in the right order.
3. Explain how to synthesize and present the result.

## Output format
- What the answer must contain

## Failure modes
- Missing inputs
- Network failure
- Ambiguous identifiers

## Examples
- Example user request 1
- Example user request 2
```

## Writing rules

- Write all skill content in English.
- Prefer explicit instructions over vague hints.
- Name the tools the agent should call.
- Tell the agent what to do when information is missing.
- If the skill can produce a file, say where to save it.
- If the skill uses literature or external databases, require evidence-backed output.

## Good biology skill patterns

- Start from the user intent, not from a database endpoint.
- Prefer list-level or workflow-level tasks over single primitive lookups.
- Distinguish known evidence from speculation.
- Encourage structured outputs such as tables, ranked lists, or checklist-style plans.

## Anti-patterns

- A skill that only repeats a tool description.
- A skill with no failure handling.
- A skill that assumes data not provided by the user.
- A skill that mixes multiple unrelated jobs into one long document.
