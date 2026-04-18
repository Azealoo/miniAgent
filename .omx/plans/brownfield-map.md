# Brownfield Map

## 2026-04-01 Full-Stack Health Pass

### Scope

- Audit the current BioAPEX frontend and backend as-shipped.
- Confirm the least dangerous path now that the runtime foundation and Study Dossier slices 1 through 3 are in place.
- Distinguish shipped behavior from planned-but-not-landed work so "working as expected" stays honest.

### Current Entry Points

- Backend bootstrap:
  - `backend/app.py`
  - owns startup scanning, agent initialization, memory indexing, and router registration
- Backend runtime path:
  - `backend/api/chat.py`
  - owns execution access, SSE streaming, compliance/evidence gating, tool traces, and session persistence
- Backend derived read models:
  - `backend/api/studies.py`
  - `backend/graph/studies_workspace.py`
  - own the read-only dossier surface derived from artifact registry truth
- Frontend shell:
  - `frontend/src/app/page.tsx`
  - `frontend/src/lib/store.tsx`
  - own access probing, session bootstrap, streaming state, and workspace mode selection
- Frontend contract boundary:
  - `frontend/src/lib/api.ts`
  - `frontend/src/lib/types.ts`
  - own auth-aware API calls and strict payload validation
- Frontend multi-surface renderer:
  - `frontend/src/components/layout/WorkspacePanel.tsx`
  - owns the Studies, Files, Docs, Registry, and related inspectable workspaces

### Must-Preserve Invariants

- Keep the backend/frontend split intact:
  - backend owns scientific/runtime truth
  - frontend renders typed contracts and should not infer missing backend state
- Keep chat/session behavior additive and inspectable:
  - typed session blocks
  - explicit SSE event types
  - visible tool and workflow traces
- Keep Studies workspace read-only and derived:
  - no persisted `study`, `study_dossier`, or parallel dossier storage
  - no chronology derived from chat/session inference
- Keep access-scope behavior explicit:
  - inspection surfaces should remain usable without silently depending on admin-only routes
  - execution-only actions should stay gated server-side
- Keep auth-aware file preview/open behavior:
  - raw-file opens and previews must continue using the bearer-aware client path instead of anonymous URL assumptions

### Current Repo Truth

- The runtime foundation is landed and has a durable OMX handoff:
  - `.omx/plans/p2-scientific-runtime-foundation-handoff.md`
- The shipped Studies dossier currently includes:
  - `Overview`
  - `Runs`
  - `Evidence & Claims`
  - `Compliance & QA`
  - `Outputs & Exports`
- The planned `Timeline` slice is not landed yet:
  - current-feature and slice-4 plan files describe it
  - the shipped backend/frontend study detail types do not yet include `timeline`

### Verification Evidence

- Backend regression sweep:
  - `300 passed`
  - covered studies, health/import, chat streaming, sessions, prompt/runtime/tool/config/policy paths
- Frontend verification:
  - `npm run typecheck` passed
  - `npm test -- src/test/app-shell.contract.test.tsx` passed with `9` tests
  - production `next build` passed
- Manual browser validation was not available in this sandbox, so live interaction risk remains low but non-zero

### Risky Subsystems

- `backend/api/chat.py`
  - highest backend blast radius
  - changes here affect access control, tool execution, evidence/compliance flow, observability, and stored session shape
- `frontend/src/lib/store.tsx`
  - highest frontend state blast radius
  - changes here affect auth state, session loading, streaming assembly, and workspace routing
- `frontend/src/components/layout/WorkspacePanel.tsx`
  - highest UI integration blast radius
  - large multi-workspace component where small edits can regress unrelated surfaces
- `backend/graph/studies_workspace.py`
  - highest dossier-contract blast radius
  - must stay additive and artifact-derived as the final `Timeline` slice is introduced
- Product/runtime drift risk:
  - `context/current-feature.md` is already pointed at slice 4 `Timeline`, but the codebase still reflects slice 3 as the shipped state

### Recommended Path

- Do not refactor the current frontend/backend architecture right now.
- Treat the current system as a stable baseline for shipped behavior:
  - runtime foundation looks healthy
  - current dossier slices look healthy
  - the build/test surface is green
- If you want the next change, make it only the planned `Timeline` slice:
  - backend owner: `backend/graph/studies_workspace.py`, `backend/tests/test_studies_api.py`
  - frontend owner: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/components/layout/workspace-data.ts`, `frontend/src/components/layout/WorkspacePanel.tsx`, `frontend/src/test/fixtures.ts`, `frontend/src/test/app-shell.contract.test.tsx`
- If you are intentionally stopping here, the business decision you should make explicitly is whether `Timeline` is required before calling the Study Dossier work "done". If not, update `context/current-feature.md` to reflect that slice 3 is the stable stopping point instead of leaving the repo in a planned-but-unlanded state.

### What Would Make This Fail

- mixing timeline behavior into session/chat history instead of keeping it artifact-derived
- broad refactors in `store.tsx`, `WorkspacePanel.tsx`, or `chat.py` while the current system is already stable
- treating the green automated checks as a substitute for all future user-flow checks once the next dossier slice lands

## Scope

Clarify whether the pasted oh-my-codex demo guide matches the OMX runtime currently installed in this BioAPEX workspace, and identify which OMX v2 features are most useful in this repo right now.

## Boundaries

- BioAPEX repo boundary:
  - This repository is an application/workspace repo with its own backend and frontend.
  - The repo root is not the standalone `oh-my-codex` package source tree.
- OMX runtime boundary:
  - The active CLI in this workspace resolves to `/gpfs/home/yininz6/.codex/omx-v2-staticpayload-20260401/packages/cli/dist/bin.js`.
  - The active MCP server in `~/.codex/config.toml` points at `/gpfs/home/yininz6/.codex/omx-v2-staticpayload-20260401/packages/mcp-server/dist/index.js`.
- Team-runtime boundary:
  - Durable team state is present under `.omx/team/` and `.omx/state/`.
  - `omx team status` returns an active tmux-backed runtime for this repo.

## Must-Preserve Invariants

- Treat repo truth and installed CLI behavior as authoritative over copied demo text.
- Do not assume upstream demo commands are valid locally without checking the installed CLI surface.
- Keep the distinction clear between:
  - the BioAPEX application repo
  - the installed OMX v2 runtime layered into this repo

## Observed Runtime Truth

- `omx version` reports `2.0.0`.
- `omx doctor` passes the core runtime checks in this workspace.
- Top-level `omx status` is not a valid command in the installed CLI.
- `omx team status` is valid and returns the live durable team state.
- The local OMX v2 README states: Codex is the first-party executor in v2 and there is no Claude bridge in this release.

## Risk Notes

- The pasted guide includes features and examples that do not exactly match the installed build, including:
  - top-level `omx status`
  - mixed Codex/Claude worker demo language
- The safest interpretation is that the guide is broadly about OMX usage, but not a byte-for-byte contract for this exact installed version.

## Recommended Path

- Answer the user that we are using OMX v2 right now in this workspace.
- Clarify that the pasted guide is directionally relevant, but parts of it do not match the exact installed local command surface and runtime capabilities.
- Recommend the highest-leverage features based on current local truth:
  - `omx doctor` for environment validation
  - `omx hud --json` for runtime truth
  - `$ultrawork` as the default workflow wrapper
  - `omx team ...` for durable multi-slice work
  - `omx explore ...` for codebase mapping before risky edits
  - `omx plugins doctor` because plugin wiring is healthy here
- De-emphasize hooks for this workspace until Codex hooks are enabled, because local hook status currently reports disabled and uninstalled.
- When in doubt, verify against:
  - `omx version`
  - `omx doctor`
  - `omx team status`
  - `~/.codex/config.toml`

## 2026-04-02 Backend Access-Control Follow-Up

### Scope

- Re-check the backend flaw identified during the `claude_code_src` comparison around dev-first access defaults.
- Confirm whether the remaining issue is only a deployment recommendation or a concrete backend trust-boundary bug.
- Choose the least dangerous mitigation that improves hosted/proxied safety without breaking normal localhost development.

### Current Entry Points

- Access decision boundary:
  - `backend/access_control.py`
  - owns loopback detection, bearer-token enforcement, and the shared route-access contract used by API routers
- Hardening policy contract:
  - `backend/hardening.py`
  - owns typed `production_hardening.api` settings
- Runtime config loading:
  - `backend/config.py`
  - owns default policy values plus user/project/local override layering
- API surface used to verify auth mode:
  - `backend/api/access.py`
  - exposes `/api/access/probe`
- Backend bootstrap and operator-facing guidance:
  - `backend/app.py`
  - `backend/docs/production-hardening.md`

### Must-Preserve Invariants

- Keep direct localhost development usable without mandatory bearer-token setup when the operator explicitly allows loopback bypass.
- Keep remote traffic on inspection, execution, and admin routes behind deterministic bearer-token checks.
- Keep the hardening contract additive:
  - existing configs should continue to load
  - safer behavior should be opt-out only where there is a concrete trust-boundary reason
- Keep access behavior inspectable through `/api/access/probe` and focused backend tests.

### Current Repo Truth

- `backend/access_control.py` currently trusts `request.client.host` alone when `allow_loopback_without_auth=True`.
- The backend has no proxy-awareness middleware and no forwarded-header safety check.
- In a same-host reverse-proxy deployment, the app can see the proxy as `127.0.0.1` while the real client is remote.
- `backend/docs/production-hardening.md` already says loopback bypass should remain local-development-only, which means the current runtime contract is stricter in docs than in the proxied-host reality.

### Real Choice

1. Flip `allow_loopback_without_auth` to `false` by default everywhere.
   - strongest hosted posture
   - breaks current local development flow without additional token setup
2. Add a broader hosted-vs-local deployment profile layer.
   - directionally correct
   - more invasive and larger than this narrow backend risk warrants right now
3. Keep direct loopback development behavior, but stop trusting loopback when forwarded-client headers are present unless the operator explicitly opts in.
   - closes the most likely proxy-trust mistake
   - preserves normal local development
   - fits the existing typed hardening-policy model

### Recommended Path

- Choose option 3.
- Add a new additive hardening knob under `production_hardening.api` that defaults to `false` and controls whether forwarded-client headers are allowed to coexist with unauthenticated loopback trust.
- Treat requests carrying `Forwarded`, `X-Forwarded-For`, or `X-Real-IP` as remote by default even if `request.client.host` is loopback.
- Keep direct loopback bypass unchanged for non-proxied local development.
- Document the behavior clearly in the runbook and verify it through `/api/access/probe` tests.

### What This Avoids

- breaking current localhost workflows by silently forcing bearer tokens everywhere
- pretending the app is proxy-safe when it currently is not
- introducing a bigger deployment-profile system before the repo needs that extra surface area

### What Would Make This Fail

- trusted proxies that do not emit any forwarded-client headers would still look local to the app
- operators might re-enable forwarded-header loopback trust without fully understanding the exposure
- broader hosted posture would still remain incomplete until a later slice disables other dev-first defaults more aggressively
