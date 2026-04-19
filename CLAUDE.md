# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## What This Repo Is

**BioAPEX** — a transparent, file-first biologist-assistant system. It is no
longer the early miniOpenClaw chat prototype: the current codebase ships a
typed SSE chat runtime with plan/verification helper-agents, policy-wrapped
tools, multi-file memory with on-disk indexing, authored workflow specs, and
a three-panel Next.js workspace. Authoritative orientation lives in
`README.md` and `AGENTS.md`. Deeper product context lives under `context/`
(`project-overview.md`, `coding-standards.md`, `ai-interaction.md`,
`current-feature.md`) and durable planning state under `.omx/`.

Runtime root: the backend treats `backend/` as its project root, so tool
results and API payloads reference paths like `artifacts/...`, `memory/...`,
`skills/...`, `storage/...` that resolve under `backend/`.

## Commands

- Conda env: `miniAgent`
- Backend: `./start-backend.sh` (or `cd backend && uvicorn app:app --port 8002 --host 0.0.0.0 --reload`)
- Frontend: `./start-frontend.sh` (or `cd frontend && npm run dev`)
- Backend tests: `cd backend && python -m pytest`
- Frontend checks: `cd frontend && npm run typecheck && npm test && npm run lint`
- E2E: `cd frontend && npm run test:e2e`
- Env file: `backend/.env` (see README "Configuration"). Role overrides follow
  `BIOAPEX_<EXECUTOR|PLANNER|VERIFIER|TITLE>_*`. Repo-local runtime knobs
  live in `backend/config.json`.

## Working Principles

### 1. Think Before Coding

Before editing, read the piece of the system you are about to touch:

- Chat turn flow: `backend/api/chat.py` → `backend/runtime/chat_runtime.py`
  → `backend/runtime/query_engine.py` → `backend/graph/agent.py`.
- Prompt assembly: `backend/graph/prompt_builder.py` pulls from
  `backend/SKILLS_SNAPSHOT.md`, `backend/workspace/{SOUL,IDENTITY,USER,AGENTS}.md`,
  ancestor `AGENTS.md`, optional git context, and either direct `memory/`
  content or RAG guidance depending on `rag_mode`.
- Session persistence and continuity:
  `backend/graph/session_manager.py`, `backend/graph/session_summary.py`,
  archives under `backend/sessions/archive/`.
- Tool surface: `backend/tools/registry.py` and the 15 tools listed in
  `README.md` ("Tools"), each wrapped via `backend/tools/policy_wrappers.py`
  with access scope, read-only/destructive flags, and planner/verifier
  exposure. When two tools in the registry could serve the same step, use
  [`docs/tool-selection.md`](docs/tool-selection.md) to pick the preferred
  default per family (URL retrieval, execution, biology DBs, evidence
  surface, file I/O, knowledge lookup, helper agents).
- Prompt cache: the system prompt is split into a *stable prefix* and a
  *volatile suffix* by `backend/graph/prompt_builder.py::build_system_prompt_blocks`.
  The prefix is frozen per-session via `SessionManager.freeze_session_prefix`
  on the first turn and reused verbatim by sub-agents through
  `runtime.subagent.resolve_session_stable_prefix`. **Adding a tool, skill,
  or workspace edit mid-session breaks the cache** (a `session_prefix_drift`
  warning fires on every drifting turn so repeated degradation stays
  visible). Per-run cache stats land on the subagent
  artifact under `cache_stats`; aggregates land on the `bioapex_prompt_cache_*`
  Prometheus metrics.
- Frontend state: `frontend/src/lib/store.tsx`, `api.ts`,
  `chat-stream-reducer.ts`, `message-blocks.ts`, `types.ts`.

For anything non-trivial, also skim the matching spec in `context/features/`
or task state in `.omx/` before writing code — these are the source of truth
for intended behavior, not chat memory.

### 2. Simplicity First

This project is deliberately file-first and framework-light. Keep it that way:

- Memory is Markdown + JSON on disk (`backend/memory/{project,user,agent}/`,
  `backend/memory/MEMORY.md`). There is no database — do not introduce one.
- Skills are Markdown instruction files at `backend/skills/<name>/SKILL.md`
  with YAML frontmatter. A new skill is a new Markdown file, not a Python
  module.
- Sessions are plain JSON under `backend/sessions/` with typed content
  blocks; archives are JSON under `backend/sessions/archive/`.
- Frontend state is a single React Context (`frontend/src/lib/store.tsx`) —
  no Redux, no extra state library.
- SSE is hand-parsed in `frontend/src/lib/api.ts` over `POST /api/chat`
  because `EventSource` is GET-only. Prefer extending that parser over
  swapping in a library.

If a framework-free edit works, ship it. Prefer small edits to existing
files over new abstractions.

### 3. Surgical Changes

- Touch only what the task requires. Do not rename, reformat, or reorganize
  files you are not otherwise changing.
- Respect the file-read/-write whitelist enforced by `backend/api/files.py`
  (workspace, memory, skills, knowledge, `SKILLS_SNAPSHOT.md`).
- Respect tool policy metadata in `backend/tools/registry.py` and
  `backend/tools/policy.py` — changing access scope, destructiveness, or
  planner/verifier exposure has runtime consequences; do not flip those
  flags casually.
- Writes under `backend/memory/` trigger memory index rebuilds
  (`backend/graph/memory_indexer.py`); writes under `backend/skills/`
  regenerate `backend/SKILLS_SNAPSHOT.md` on next startup
  (`backend/tools/skills_scanner.py`). Account for both when editing those
  trees.
- Authored workflow specs live at the repo root under `workflows/`
  (`rna-seq-qc.yaml`, `rnaseq_qc_de.yaml`, `perturb-seq-nextflow.yaml`),
  with runners under `workflows/runners/` and templates under
  `workflows/report_templates/`. Artifact plumbing lives under
  `backend/artifacts/` — keep schema, registry, and provenance changes
  together rather than scattered.
- Rejected approaches — regex-only permissions, single-phase
  compaction, and `bash`/`python_repl` as default execution — are
  documented in [`docs/anti-patterns.md`](docs/anti-patterns.md).
  Skim it before reshaping the policy, compaction, or tool-execution
  surfaces.

### 4. Goal-Driven Execution

- Every change is reviewed before merge. Write for reviewability: small
  diffs, clear commit messages, and tests where the runner already exists
  (`backend/tests/` for pytest, `frontend/src/test/` and `frontend/e2e/`
  for Vitest/Playwright).
- Preserve the transparency guarantees the product is built on:
  - process-first chat rendering (`frontend/src/components/chat/*` —
    `ChatMessage.tsx`, `TurnActivityFeed.tsx`, `SessionHistorySummary.tsx`,
    `TurnDetailsPanel.tsx`)
  - typed SSE events emitted from the backend: `retrieval`, `token`,
    `tool_start`, `tool_end`, `plan_created`, `plan_updated`,
    `verification_result`, `new_response`, `done`, `error`
  - provenance and audit under `backend/storage/{artifact_registry,audit,compliance_audit,memory_index}/`
- Align UI, API, and storage changes together. A new SSE event type needs a
  producer in `backend/runtime/` or `backend/graph/`, a reducer branch in
  `frontend/src/lib/chat-stream-reducer.ts`, and a persisted shape if it
  ends up in session history.
- When a feature spec exists in `context/features/` or a task exists in
  `.omx/`, keep it updated as the implementation lands — these files are
  how the next session recovers the goal.

## When You Are Unsure

1. Re-read the relevant section of `README.md` and `AGENTS.md`.
2. Check `context/` for the feature spec or interaction contract.
3. Check `.omx/` for in-flight plans or reviews.
4. Prefer the behavior the code actually exhibits over any older narrative
   in this file or in `README.md` — if they disagree, the code wins and
   the docs should be corrected in the same PR.
