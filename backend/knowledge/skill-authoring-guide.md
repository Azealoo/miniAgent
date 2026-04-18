# Biology Skill Authoring Guide

Use this guide when creating or revising `skills/<skill_name>/SKILL.md`.

## Goal

Write skills that are easy for an LLM agent to discover, read, and execute reliably.

## Runtime truth

The runtime skill registry is the source of truth for discovery and selection.
Do not edit `SKILLS_SNAPSHOT.md` by hand; it is a generated compatibility artifact derived from the selected registry entries. `/api/skills` exposes the active selected summary, while `/api/skills/registry` exposes the full registry state for inspection surfaces.

## P7 Compatibility Surfaces

- `/api/skills` is the compact active-skill summary for compatibility clients. Keep it limited to the selected entries and their core identity fields.
- `/api/skills/registry` is the full runtime registry surface. This is where `paths`, `effort`, enabled state, selection state, and other richer metadata belong.
- `SKILLS_SNAPSHOT.md` remains a readable derived artifact generated from the runtime-selected registry view. Treat it as compatibility output, not authoring input.

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

User-facing biology skills should define these explicitly:

```yaml
tags: [genes, evidence, annotation]
aliases: [alternate_name, short_name]
species: human
modality: single_cell_rna
stage: analysis
stability: stable
safety_level: low
```

## Supported optional runtime hints

`P7` adds a deliberately small extension set beyond the `P6` contract:

```yaml
paths:
  - backend/runtime/
  - memory/project/**
effort: medium
```

Field guidance:
- `paths`: repo-relative path hints or glob-like patterns that make the skill relevant when nearby files are in play. Use forward slashes, keep them relative to the project root, and do not use absolute paths or `..`.
- `effort`: optional execution hint for future routing and runtime policy. Supported values are `low`, `medium`, and `high`.

Explicit non-goals for this phase:
- hooks metadata
- shell execution declared inside skill bodies
- plugin-only or MCP-only loading semantics

Field guidance:
- `category`: broad domain, such as `bio/literature`, `bio/single_cell_rna`, `bio/perturb_seq`, `bio/molecular_lab`, `bio/compute`
- `stage`: workflow step such as `design`, `qc`, `analysis`, `interpretation`, `validation`, `reporting`, `utilities`
- `stability`: `stable`, `evolving`, or `experimental`
- `safety_level`: `low`, `medium`, or `high`
- `requires_tools`: must only name tools that exist in the active runtime catalog

For stable biology skills, do not omit the routing fields above. Stable skills should be tool-backed, domain-specific, and ready to survive strict metadata validation.

## Stable biology output contract

When a biology skill is promoted to `stability: stable`, its body should make two things obvious:

- which runtime tools the agent is expected to call
- what a biologist will reliably receive back

Stable biology skills should therefore name the declared tools directly in `## Steps` and keep the output contract explicit:

- `Biological context or assumptions`
- `Evidence or source basis`
- a task-specific core result such as a table, checklist, or recommendation
- `Caveats or ambiguity`
- `Recommended next step`

If the skill depends on literature, protocols, or external databases, the output should preserve provenance rather than presenting unsupported synthesis as fact.

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
- For stable skills, make the output contract easy to scan and preserve source attribution.

## Anti-patterns

- A skill that only repeats a tool description.
- A skill with no failure handling.
- A skill that assumes data not provided by the user.
- A skill that mixes multiple unrelated jobs into one long document.
