# Memory Migration: MEMORY.md to Typed Scoped Notes

## Summary

`backend/memory/MEMORY.md` used to be the single durable memory document:
the prompt builder read the whole file and blind-injected it into every
non-RAG system prompt. Durable narrative (user preferences, project facts,
workflow heuristics, scientific references) accumulated in that single file
and steadily bloated the prompt.

As of the issue #26 change, `MEMORY.md` is a curated index, not a body of
facts. Durable content now lives in typed scoped notes under the three
scope directories, each with YAML frontmatter carrying `type`, `name`, and
`description`.

## What Moved Where

| Original narrative in MEMORY.md                | New home                                      | Type                 |
|------------------------------------------------|-----------------------------------------------|----------------------|
| Johnny's collaboration style and lab focus     | `memory/user/johnny-preferences.md`           | `user_preference`    |
| Shared filesystem paths and runtime defaults   | `memory/project/shared-paths.md`              | `project_fact`       |
| Glycine-limited running-buffer scaling rule    | `memory/project/western-blot-buffer-scaling.md` | `workflow_heuristic` |

Longer-form protocol notes and read-once review artifacts also live under
`memory/project/` (`CHO_TAB2_*`, `rnaseq-de-readiness-*`) and are retrieved
on demand rather than always injected.

## Prompt Builder Behavior

`backend/graph/prompt_builder.build_system_prompt` no longer blind-injects
the full MEMORY.md body:

- In RAG mode, the file is skipped entirely in favor of the RAG guidance
  block (unchanged).
- In non-RAG mode, `MEMORY.md` is loaded under a tight `MAX_MEMORY_INDEX_CHARS`
  budget (2 KB). The scoped-memory listing continues to surface the paths,
  names, and one-line descriptions of fresh or pinned scoped notes, without
  inlining their bodies.

This keeps the hot prompt path small while preserving the previous
compatibility contract: readers and indexers that already follow the typed
frontmatter schema (see `backend/graph/memory_indexer.py` and
`backend/graph/memory_types.py`) need no changes.

## Adding New Durable Content

1. Pick the right scope:
   - `memory/project/` for facts that belong to the current repo or codebase.
   - `memory/user/` for facts about the person working with the agent.
   - `memory/agent/` for runtime-produced summaries and handoff notes.
2. Write a new markdown file with YAML frontmatter (`type`, `name`,
   `description`; optional `pinned`, `updated_at`).
3. Do not add narrative content to `MEMORY.md`. If you add a new scope
   directory or new `type` value, update the contract section of
   `MEMORY.md` to reflect it.
