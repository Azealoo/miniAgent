# Long-term Memory Index

This file is a concise, curated TOC — not a body of durable facts. Durable
notes live in typed scoped files under `memory/project/`, `memory/user/`,
and `memory/agent/`. The prompt builder auto-injects a listing of fresh or
pinned scoped notes on each turn, so this index does not need to enumerate
them.

## Scopes

- `memory/project/` — typed project facts, workflow heuristics, and
  scientific references tied to the current work.
- `memory/user/` — typed user preferences and recurring environment context.
- `memory/agent/` — runtime-maintained session summaries and handoff notes.

## Typed Note Contract

Every note under the three scope directories should begin with YAML
frontmatter:

- `type` — one of `user_preference`, `project_fact`, `workflow_heuristic`,
  `scientific_reference`.
- `name` — short human label.
- `description` — one-line summary used by the scoped-memory listing.

Optional fields:

- `pinned: true` — always surface the entry in the scoped listing, even when
  stale.
- `updated_at: <ISO-8601>` — override the file mtime for staleness decisions.

## Automatic Distillation

Verified runtime summaries are appended under
`memory/agent/session-<session_id>.md` when the turn did not already write
directly under `memory/`. Automatic distillation does not rewrite this file.

## Migration

Durable narrative that previously lived in this file was split into typed
artifacts under `memory/project/` and `memory/user/`. See
`context/memory-migration.md` for the history and the rationale.
