# BioAPEX

BioAPEX is a transparent, file-first biologist-assistant system for scientific workflows, evidence synthesis, protocol support, compliance gating, and reproducible computational biology.

This repository is no longer just a lightweight chat-agent prototype. The current codebase includes:

- a typed SSE chat runtime with plan and verification helper-agent events
- process-first turn rendering that stays consistent across live chat, reopened history, and turn inspection
- policy-wrapped execution and inspection tools
- multi-file memory with on-disk indexing
- durable artifact schemas, registry, provenance, and audit layers
- authored workflow specs and workflow runners
- session token accounting plus a live usage inspector with tracked and in-flight estimates
- a three-panel Next.js workspace for chat, files, sources, memory, skills, usage, and turn inspection
- OMX v2 durable planning and execution state under `.omx/`

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Path Conventions](#path-conventions)
- [Repository Map](#repository-map)
- [Backend Architecture](#backend-architecture)
- [Frontend Architecture](#frontend-architecture)
- [Workflows Artifacts And Specs](#workflows-artifacts-and-specs)
- [API Surface](#api-surface)
- [Verification](#verification)

## Quick Start

### Recommended helper scripts

The repo includes helper scripts that activate the `miniAgent` conda environment and start each app:

```bash
./start-backend.sh
./start-frontend.sh
```

### Manual startup

```bash
conda activate miniAgent

# Backend
cd backend
pip install -r requirements.txt
# The uvicorn --host value is driven by the active production-hardening
# posture: dev/hosted-strict → 127.0.0.1, trusted-lab → 0.0.0.0.
uvicorn app:app --port 8002 \
    --host "$(python -c 'import config; print(config.get_production_hardening_policy().host_binding)')" \
    --reload

# Frontend
cd frontend
npm install
npm run dev
```

Frontend: `http://localhost:3000`

Backend health check: `http://localhost:8002/`

## Configuration

### Environment variables

Create `backend/.env` and provide the model credentials you want to use.

The default runtime model split is:

- executor: DeepSeek chat model
- planner: OpenAI model
- verifier: OpenAI model
- title generation: OpenAI model
- embeddings: OpenAI-compatible embedding endpoint

Minimal example:

```env
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

Role-specific overrides follow the pattern:

```text
BIOAPEX_<ROLE>_PROVIDER
BIOAPEX_<ROLE>_MODEL
BIOAPEX_<ROLE>_API_KEY
BIOAPEX_<ROLE>_BASE_URL
BIOAPEX_<ROLE>_TEMPERATURE
BIOAPEX_<ROLE>_STREAMING
```

Where `<ROLE>` is one of `EXECUTOR`, `PLANNER`, `VERIFIER`, or `TITLE`.

### Runtime config

`backend/config.json` controls repo-local runtime behavior such as:

- `rag_mode`
- prompt-context options such as optional git-context injection
- tool policy settings
- skill enablement and extra skill directories
- read-file extra roots
- per-role execution backend settings
- production hardening and access defaults

## Path Conventions

Important: the running backend treats `backend/` as its project root.

That means relative paths emitted in tool results and API payloads such as:

- `artifacts/...`
- `memory/...`
- `skills/...`
- `knowledge/...`
- `storage/...`

resolve on disk under `backend/`, for example:

- `artifacts/...` -> `backend/artifacts/...`
- `storage/...` -> `backend/storage/...`

This is why artifact references inside session history and tool payloads look backend-relative even though the repo itself has a higher-level root.

## Repository Map

```text
.
├── backend/                 FastAPI app, runtime, tools, memory, artifacts, tests
├── frontend/                Next.js app, React state, inspector and chat UI
├── workflows/               Authored workflow specs and workflow runners
├── context/                 Product context, feature specs, roadmaps, checklists
├── .omx/                    OMX v2 plans, research, session, task, and review state
├── start-backend.sh         Backend helper launcher
├── start-frontend.sh        Frontend helper launcher
└── AGENTS.md                Repo operating instructions
```

### Notable backend directories

- `backend/api/`: HTTP routes for chat, access probing, sessions, files, token usage, and skill registry access
- `backend/graph/`: agent manager, prompt building, session management, skill routing, memory indexing
- `backend/runtime/`: query engine, turn ledger, model factory, session continuity and runtime helpers
- `backend/tools/`: policy-wrapped tool implementations and tool registry metadata
- `backend/skills/`: Markdown skill directories consumed by the runtime skill registry
- `backend/memory/`: project, user, and agent memory files indexed for retrieval
- `backend/knowledge/`: local knowledge base, caches, and authored scientific guidance
- `backend/artifacts/`: artifact schemas, registry helpers, provenance/export logic, examples, and runtime outputs
- `backend/storage/`: persisted indexes, audit logs, compliance logs, and artifact registry snapshots
- `backend/tests/`: backend pytest coverage across runtime, artifacts, workflows, tools, and compliance
- `backend/workspace/`: prompt-building documents such as `SOUL.md`, `IDENTITY.md`, `USER.md`, and `AGENTS.md`

### Notable frontend directories

- `frontend/src/app/`: Next.js app entrypoints
- `frontend/src/components/chat/`: chat transcript, input, and process rail UI
- `frontend/src/components/layout/`: app shell, navbar, sidebar, workspace panel, resize handles
- `frontend/src/components/editor/`: inspector panel and turn details
- `frontend/src/components/session/`: archived-turn and continuity summary UI
- `frontend/src/components/preview/`: raw and structured file preview surfaces
- `frontend/src/lib/`: API client, SSE parsing, reducers, shared types, store, and utilities
- `frontend/src/test/`: contract and state-level tests
- `frontend/e2e/`: Playwright end-to-end tests

## Backend Architecture

### Startup flow

`backend/app.py` does four important things on startup:

1. loads `.env`
2. configures the LlamaIndex embedding model
3. scans skills and regenerates `backend/SKILLS_SNAPSHOT.md`
4. initializes the agent manager and rebuilds the memory index

### Core runtime layers

#### `backend/graph/agent.py`

`AgentManager` owns the role-based chat models, runtime tools, session manager, and memory indexer.

Key current behavior:

- builds separate models for executor, planner, verifier, and title generation
- rebuilds the LangChain agent on every request so prompt context and skill state stay fresh
- injects retrieved memory in RAG mode
- routes skill selection through the skill registry before building the system prompt
- normalizes structured tool results before they enter the stream or session history

#### `backend/runtime/query_engine.py`

`QueryEngine` is the turn-level runtime boundary between HTTP transport and model execution.

It is responsible for:

- persisting the user message at the start of the turn
- turning raw helper-tool completions into typed `plan_created`, `plan_updated`, and `verification_result` events
- performing a single runtime-managed repair retry when verification asks for repair and config allows it
- producing a finalized turn ledger for persistence

#### `backend/runtime/chat_runtime.py`

`ChatRuntime` wraps the query engine for the SSE route.

It currently:

- auto-compresses long sessions before the turn runs
- loads LLM-optimized session history
- assigns `request_id` and monotonic `event_index`
- streams typed SSE payloads
- persists assistant segments with typed blocks when the turn completes

### Prompt assembly

`backend/graph/prompt_builder.py` builds the system prompt from disk, not hidden in code.

It pulls from:

- the generated skills snapshot
- `workspace/SOUL.md`
- `workspace/IDENTITY.md`
- `workspace/USER.md`
- `workspace/AGENTS.md`
- project-level instruction files such as repo `AGENTS.md` and referenced context files
- optional git status context
- either direct memory content or RAG memory guidance, depending on `rag_mode`

Important limits and behavior:

- prompt components are truncated to bounded sizes
- project instruction context is additive and discovered from ancestor instruction files
- retrieved memory is injected as background context rather than as verified current state

#### Prompt-cache stable prefix and sub-agent reuse

The assembled prompt is split into a *stable prefix* (workspace files, skills
snapshot, harness guidance, tool-result contract) and a *volatile suffix*
(memory index, scoped-memory listing, git status). The split lives in
`backend/graph/prompt_builder.py::build_system_prompt_blocks` and matches the
`SECTIONS_IN_STABLE_PREFIX` set.

The stable prefix is captured per session on the first turn via
`SessionManager.freeze_session_prefix`. Helper sub-agents (`plan_agent`,
`verification_agent`) read it back through `resolve_session_stable_prefix` and
prepend it verbatim to their own helper-specific system prompt, so the
provider's prefix cache matches the parent agent's leading bytes:

- DeepSeek and OpenAI hit prefix caching automatically when the leading
  tokens are byte-identical to a recent request from the same key.
- Anthropic clients can feed the split through
  `build_anthropic_system_blocks` to attach a `cache_control: ephemeral`
  breakpoint at the end of the stable prefix.

Per-call cache hit / miss / creation token counts come from LangChain's
normalized `AIMessage.usage_metadata` (`input_token_details.cache_read` and
`cache_creation`) and are surfaced two ways:

- Process-wide: the Prometheus gauges
  `bioapex_prompt_cache_read_tokens_total`,
  `bioapex_prompt_cache_creation_tokens_total`,
  `bioapex_prompt_cache_uncached_tokens_total`, and the rolling
  `bioapex_prompt_cache_hit_rate` ratio (see
  `backend/runtime/metrics_collector.py`).
- Per sub-agent run: the artifact at
  `artifacts/subagent/<date>/<run_id>/subagent_run.json` includes a
  `cache_stats` block with `llm_calls`, `input_tokens`,
  `cache_read_tokens`, `cache_creation_tokens`, `uncached_tokens`, and the
  per-run `cache_hit_rate`.

**Adding a tool, skill, or workspace edit mid-session breaks the cache.**
The frozen prefix is sticky for the lifetime of the session; if the prompt
assembly changes after the first turn (a skill is enabled, a workspace file
is edited, the runtime is reconfigured) the new prefix no longer matches the
frozen one and provider prefix caching falls through. The runtime logs a
single `session_prefix_drift` warning the first time it sees a divergent
prefix for a given session id so the loss of cache eligibility is visible.
To recover the cache hit rate, start a new chat session.

### Tools

The current default runtime toolset contains 15 tools:

- `terminal`
- `python_repl`
- `fetch_url`
- `http_json`
- `ncbi_eutils`
- `evidence_retrieval`
- `evidence_review`
- `entity_grounding`
- `plan_agent`
- `verification_agent`
- `uniprot_api`
- `ensembl_api`
- `read_file`
- `write_file`
- `search_knowledge_base`

The tool registry tracks structured policy metadata such as:

- access scope: `inspection`, `execution`, or `admin`
- read-only vs destructive behavior
- planner and verifier exposure
- concurrency and interrupt behavior
- output contract version
- evidence expectations and activity/result summary hints

### Skills

Skills are Markdown-first and live under `backend/skills/<skill>/SKILL.md`.

The runtime supports:

- an active skill summary at `/api/skills`
- a richer registry with metadata at `/api/skills/registry`
- config-driven skill enablement
- optional extra skill directories
- category and stage metadata in the registry

#### Skill frontmatter schema

Every `SKILL.md` starts with a YAML frontmatter block. The scanner
(`backend/tools/skills_scanner.py`) normalizes, validates, and surfaces
the following fields in `SKILLS_SNAPSHOT.md`; fields marked "enforced"
are also checked at tool dispatch time by `backend/tools/policy.py`.

Identity and routing:

- `name` (string) — unique skill identifier.
- `description` (string) — one-line summary shown to the model.
- `category` (string) — e.g. `bio/literature`, `bio/compute`.
- `tags`, `aliases` (list[str]) — free-form routing hints.
- `paths` (list[str]) — path globs that activate the skill when matched
  against the current query or recent turn artifacts.
- `effort` (enum: `low` | `medium` | `high`).
- `version` (string).

Biology metadata (required for `bio/*` user-invocable skills):

- `species`, `modality`, `stage`.
- `stability` (enum: `stable` | `evolving` | `experimental`).
- `safety_level` (enum: `low` | `medium` | `high`).

Tool surface:

- `requires_tools` (list[str]) — *declared* tools the skill uses. Used
  for documentation, routing, and to assert the skill doesn't depend on
  tools that don't exist in this build.
- `tools_allowed` (list[str], **enforced**) — allowlist that restricts
  the tool surface for the duration a skill is active. When at least
  one active skill declares a non-empty `tools_allowed`, tool dispatch
  is confined to the union of declarations across active skills; calls
  outside that union are blocked with
  `block_reason="skill_tools_allowed_violation"`. Skills that omit
  `tools_allowed` contribute nothing to the union and impose no
  restriction on their own.

Exposure (advisory, surfaced in `SKILLS_SNAPSHOT.md`):

- `planner_visible` (bool, default `true`) — set `false` to hide the
  skill from the planner helper.
- `verifier_visible` (bool, default `true`) — set `false` to hide the
  skill from the verifier helper.
- `user_invocable` (bool, default `true`).

Runtime gating:

- `required_env` (list[str]) — environment variable names whose
  presence (non-empty) is a precondition for routing. If any are
  missing the skill is dropped from selection at turn time; the skill
  never becomes active and its `tools_allowed` contract is not
  consulted. Provide names only, not `NAME=value` pairs.
- `requires_network` (bool).
- `min_posture` (enum: `inspection` | `execution` | `admin`) —
  declarative metadata describing the minimum runtime posture a skill
  expects. Currently advisory and surfaced in the snapshot.
- `risk_tier` (enum: `low` | `medium` | `high`) — declarative blast
  radius hint for review tooling; surfaced in the snapshot.

### Memory and knowledge

The memory layer is now multi-file rather than a single `MEMORY.md` only.

Important pieces:

- `backend/memory/project/`
- `backend/memory/user/`
- `backend/memory/agent/`
- `backend/memory/MEMORY.md` as a compatibility and shared-memory surface

Any write under `memory/` triggers a rebuild of the memory index.

The knowledge layer lives under `backend/knowledge/` and includes local scientific guidance plus cached retrieval content such as PubMed and UniProt material.

### Sessions and continuity

Sessions are stored as JSON under `backend/sessions/`.

Current session behavior:

- raw history is persisted with additive typed content blocks
- consecutive assistant messages are merged before prompt assembly
- saved history is normalized with the same process-first helper-text cleanup used for live turns
- verification-retry assistant clusters collapse into one visible final response while preserving process artifacts
- older history is auto-compressed when the session reaches 40 messages
- compressed history is summarized into a structured scientific continuity block
- archived raw message batches are stored under `backend/sessions/archive/`
- archived summaries can be reopened later through the UI and session APIs
- the first completed turn in a default-titled session can trigger background title generation

This replaces the older README story about a manual `/compress` endpoint. The current app uses auto-compression plus continuity and archive inspection endpoints.

### Access control

The backend now has explicit route access scopes.

When production hardening is configured, routes may require:

- loopback access
- inspection bearer token
- execution bearer token
- admin bearer token

The frontend probes access modes through `/api/access/probe`.

## Frontend Architecture

The frontend is a Next.js 14 App Router application with React Context for runtime state.

### Main UI shell

`frontend/src/components/layout/AppShell.tsx` renders a three-panel workspace:

- left sidebar: sessions and workspace navigation
- center workspace: live chat and session history
- right inspector: files, sources, memory, skills, usage, and turn details

The sidebar and inspector widths are draggable.

### State and API client

The main frontend runtime lives in:

- `frontend/src/lib/store.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/chat-stream-reducer.ts`
- `frontend/src/lib/message-blocks.ts`

Current responsibilities include:

- access-scope bootstrapping and bearer-token handling
- session list, session history, and continuity-summary loading
- abortable custom POST-based SSE parsing for `/api/chat`
- optimistic live assistant messages
- typed stream-event reduction into process-first UI state
- live session-usage summary fetching and tracked-plus-estimated aggregation
- file preview and inspector path state

### Chat UX

The current chat surface is process-first rather than terminal-log style.

The composer can stop an in-flight response, and saved or retried assistant turns are normalized so planning and verification activity stays visible without duplicating final answers.

Important surfaces:

- `ChatMessage.tsx`: markdown answer rendering plus normalized process rail handling
- `TurnActivityFeed.tsx`: live tool, retrieval, plan, verification, and helper-trace activity
- `SessionHistorySummary.tsx`: compacted older turns plus reopenable archived summaries with the same process-first normalization as live chat
- `TurnDetailsPanel.tsx`: request-scoped deep inspection with a single normalized response view per assistant turn

### Inspector UX

`InspectorPanel.tsx` now exposes dedicated tabs for:

- Files
- Sources
- Memory
- Skills
- Usage
- Turns

This panel handles:

- raw file reads and saves through `/api/files`
- structured file previews
- source and compliance inspection
- memory editing
- skill registry inspection
- live token totals, input/output/tool breakdowns, context-window pressure, and tokenizer provenance
- transcript export

## Workflows Artifacts And Specs

### Workflow specs

Authored workflow specs live under the repo-root `workflows/` directory.

Current examples include:

- `workflows/rna-seq-qc.yaml`
- `workflows/rnaseq_qc_de.yaml`
- `workflows/perturb-seq-nextflow.yaml`

Supporting runners and templates live under:

- `workflows/runners/`
- `workflows/report_templates/`

### Artifact and storage model

BioAPEX is intentionally file-first.

The artifact layer covers:

- canonical run-directory naming
- artifact registry updates
- provenance export
- BioCompute export
- ELN export
- schema-backed artifact documents

Operationally, live outputs and registries are stored under backend-relative paths such as:

- `backend/artifacts/...`
- `backend/storage/artifact_registry/...`
- `backend/storage/audit/...`
- `backend/storage/compliance_audit/...`
- `backend/storage/memory_index/...`

### Specs and durable project context

Two repo areas matter for feature work and documentation:

- `context/features/`: numbered feature specs that describe the intended product surface
- `.omx/`: OMX v2 plans, research notes, tasks, reviews, and team state

## API Surface

### Root

| Method | Path | Notes |
|---|---|---|
| `GET` | `/` | Health check returning backend status |

### Access

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/access/probe?scope=inspection|execution|admin` | Returns how the current request is authorized |

### Chat

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/chat` | SSE chat endpoint with typed events and per-turn `request_id` / `event_index`. Turns for the same `session_id` are serialized — a second request that arrives while one is still streaming fails fast with HTTP 409 rather than interleaving writes. |

Current emitted SSE event types:

- `retrieval`
- `token`
- `tool_start`
- `tool_end`
- `plan_created`
- `plan_updated`
- `verification_result`
- `new_response`
- `done`
- `error`

### Sessions

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/sessions` | List sessions |
| `POST` | `/api/sessions` | Create a session |
| `PUT` | `/api/sessions/{session_id}` | Rename a session |
| `DELETE` | `/api/sessions/{session_id}` | Delete a session and clear runtime state |
| `GET` | `/api/sessions/{session_id}/history` | Raw stored history with typed content blocks |
| `GET` | `/api/sessions/{session_id}/continuity` | Structured summaries for compressed older history |
| `GET` | `/api/sessions/{session_id}/archives/{archive_id}` | Load one archived history batch |
| `GET` | `/api/sessions/{session_id}/files/summary` | Session-scoped file workspace summary |
| `POST` | `/api/sessions/{session_id}/generate-title` | Generate a title from the first user prompt |

### Files and skills

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/files?path=...` | Read whitelisted file content |
| `GET` | `/api/files/raw?path=...` | Read raw file bytes or rewritten schema JSON |
| `POST` | `/api/files` | Save allowed files under workspace, memory, skills, or knowledge |
| `GET` | `/api/skills` | Active runtime-selected skill summary |
| `GET` | `/api/skills/registry` | Full runtime skill registry with metadata |

### Tokens

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/tokens/session/{session_id}` | Session-level token stats with system, input, output, tool, context-window, and tokenizer metadata |
| `POST` | `/api/tokens/files` | Batch token counts for whitelisted repo-relative workspace, memory, skill, or knowledge paths |

## Verification

### Backend

```bash
conda activate miniAgent
cd backend
python -m pytest
```

### Frontend

```bash
conda activate miniAgent
cd frontend
npm run typecheck
npm test
npm run lint
```

### End-to-end

```bash
conda activate miniAgent
cd frontend
npm run test:e2e
```

## Notes For Contributors

- Prefer the repo context files under `context/` over stale mental models.
- Treat `backend/` as the runtime root when debugging file paths.
- Keep `README.md` aligned with `backend/app.py`, `backend/api/*`, `backend/tools/*`, `backend/graph/*`, `frontend/package.json`, and the current workflow/spec layout.
