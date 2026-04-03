# Long-term Memory

This file is the top-level memory index and compatibility entrypoint.
Use scoped files under `memory/project/`, `memory/user/`, and `memory/agent/`
for durable notes that should not all live in one document.

## Directory Index
- `memory/MEMORY.md`: concise summary and compatibility entrypoint
- `memory/project/`: typed project facts, paths, heuristics, and active work context
- `memory/user/`: typed user preferences and recurring environment context
- `memory/agent/`: runtime-maintained summaries and handoff notes

## Typed Memory Contract

For new markdown notes under `memory/project/`, `memory/user/`, and `memory/agent/`,
prefer frontmatter with:
- `type`
- `name`
- `description`

Allowed `type` values in this phase:
- `user_preference`
- `project_fact`
- `workflow_heuristic`
- `scientific_reference`

Legacy freeform notes remain readable during migration, but `MEMORY.md` should stay short
and point readers toward scoped files instead of carrying the full durable body itself.

## Current Scoped Notes
- `memory/user/johnny-preferences.md` — typed user preference summary for collaboration style and lab context
- `memory/project/shared-paths.md` — typed project fact note for shared filesystem and runtime paths
- `memory/project/western-blot-buffer-scaling.md` — typed workflow heuristic for the glycine-limited running buffer recipe

## Automatic Distillation
- Verified runtime summaries are appended under `memory/agent/session-<session_id>.md` when the turn did not already write under `memory/` directly.
- `memory/MEMORY.md` stays a curated index and compatibility entrypoint; automatic distillation does not rewrite this file.

## Compatibility Summary
- User works on AI and biology projects with a perturbation-screen focus.
- Shared paths and local runtime defaults live in the scoped notes above.
- Practical, round-number operating heuristics should stay in typed project notes rather than growing this file.
