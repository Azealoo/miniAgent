# Chat-Only Cleanliness Review

Date: 2026-04-02
Mode: ultrawork + review

## Question

Is the current frontend and backend clean enough for a product boundary that keeps only chat, its tools, and the memory system?

## Verdict

Changes requested.

The backend route surface is close to the target, but the frontend shell and parts of the supporting codebase still model a much broader product. The current repo is stable enough to continue from, but it is not yet "chat-only clean".

## Findings

### 1. Frontend still exposes major product surfaces whose backend routes were already deleted

Severity: high

Evidence:

- `frontend/src/components/layout/WorkspacePanel.tsx` still renders `DocsWorkspace`, `FilesWorkspace`, `StudiesWorkspace`, `OpsWorkspace`, and `ArtifactsWorkspace`.
- `frontend/src/components/layout/OpsWorkspace.tsx` still calls observability, audit, and connector registry APIs.
- `frontend/src/components/editor/InspectorPanel.tsx` still calls skills registry, token usage, and artifact registry APIs.
- `frontend/src/lib/api.ts` still exports clients for `/api/studies`, `/api/skills/registry`, `/api/tokens/session/*`, `/api/artifacts/registry`, `/api/audit/events`, `/api/observability/*`, and `/api/connectors/registry`.
- `backend/tests/test_chat_engine_health.py` explicitly asserts that `app.py` should not import the deleted route modules for artifacts, audit, connectors, observability, skills, studies, and tokens.

Why it matters:

- The frontend is still promising capabilities the backend app surface intentionally removed.
- Even where these surfaces are mocked in tests, they are now outside the desired product boundary and create cleanup debt.

### 2. The app shell still centers multi-workspace navigation instead of a chat-first shell

Severity: high

Evidence:

- `frontend/src/lib/types.ts` still defines workspace modes `docs`, `files`, `studies`, `ops`, and `artifacts` in addition to `sessions`.
- `frontend/src/components/layout/workspace-data.ts` still defines a six-mode primary navigation model and large workspace metadata tables.
- `frontend/src/components/layout/Sidebar.tsx` still renders the full workspace rail and search copy for sessions, docs, files, studies, and ops.
- `frontend/src/components/chat/ChatInput.tsx` still exposes quick actions that jump into sources, turn details, and files workspaces instead of keeping the composer narrowly chat-focused.

Why it matters:

- This is not unused code; it is active UI product scope.
- If the intended product is chat plus tools plus memory, the shell should stop teaching users that docs, studies, ops, and artifact browsers are first-class destinations.

### 3. At least one backend read model is now orphaned

Severity: medium

Evidence:

- `backend/graph/studies_workspace.py` defines `list_studies_workspace(...)` and `get_study_detail_workspace(...)`.
- A repo-wide search shows no remaining callers outside that file itself.

Why it matters:

- This is true dead backend code after the app-route cleanup.
- Leaving it in place makes the backend look broader than it really is and invites stale maintenance.

### 4. Workflow-era transcript and type plumbing still survives deep in the chat UI

Severity: medium

Evidence:

- `frontend/src/lib/store.tsx` still normalizes `workflow_event` blocks into `workflow_events`.
- `frontend/src/components/chat/TurnActivityFeed.tsx` still summarizes workflow start, step, artifact, blocked, and done events.
- `frontend/src/lib/types.ts` still carries extensive workflow event, study, observability, and artifact-registry types.

Why it matters:

- The runtime no longer centers workflows, but the chat UI still carries that vocabulary and data model.
- This is the main residual shape keeping the frontend from being a simpler chat-plus-tools shell.

### 5. Config and hardening still preserve connector-era settings that are no longer part of the current app surface

Severity: medium

Evidence:

- `backend/config.py` still exposes `get_connector_entry(...)` and `set_connector_entry(...)`.
- `backend/hardening.py` still includes `connectors_configuration_enabled` and `connectors_runtime_actions_enabled`.

Why it matters:

- These knobs are not harmful by themselves, but they are another sign that the repo still carries removed product slices in configuration and policy.
- If connectors are explicitly out of scope for now, these should either move behind a later feature boundary or be removed.

### 6. Verification is green for the current mixed-scope shell, not for a strict chat-only shell

Severity: medium

Evidence:

- `backend/tests/test_chat_engine_health.py`, `backend/tests/test_runtime_query_engine.py`, and `backend/tests/test_chat_streaming.py` pass.
- `frontend npm run typecheck` passes.
- `frontend npm test -- src/test/app-shell.contract.test.tsx` passes.
- However, `frontend/e2e/app-shell.e2e.spec.ts` and `frontend/src/test/app-shell.contract.test.tsx` still mock or exercise removed route families such as tokens, observability, studies, skills registry, artifacts, and workflow-oriented UX.

Why it matters:

- The repo is internally consistent enough to work, but the tests still codify a broader shell than the desired product.
- A later cleanup should replace these mixed-scope tests with chat-only shell contracts.

## Recommendation

Do one explicit "chat-only frontend/backend cull" slice before the `chat.py` refactor.

Suggested order:

1. Remove extra workspace modes from the frontend shell.
2. Remove frontend API clients and inspector/workspace panels for deleted backend routes.
3. Delete orphaned backend read models such as `backend/graph/studies_workspace.py`.
4. Prune workflow-era transcript plumbing that no longer has a real runtime producer.
5. Rebaseline tests around the smaller shell.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
