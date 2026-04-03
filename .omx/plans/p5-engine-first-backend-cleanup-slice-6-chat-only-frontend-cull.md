# P5 Slice 6: Chat-Only Frontend Cull

Date: 2026-04-02

## Goal

Remove workflow/protocol UI and compatibility reads from the frontend so the shell matches the chat-only backend boundary.

## Scope

- Delete flow-mode navigation, selection state, and the dedicated flows workspace.
- Stop sending `selected_workflow` from the frontend chat client.
- Remove the temporary `/api/sessions/workflows/summary` dependency and delete the matching backend compatibility route.
- Update shell and contract tests so they assert the new chat-only payload shape and quick-start copy.

## Implemented

- Removed `selectedWorkflow` / `selectWorkflow` state from `frontend/src/lib/store.tsx`.
- Removed flow-focused shell UI from:
  - `frontend/src/components/layout/Sidebar.tsx`
  - `frontend/src/components/layout/Navbar.tsx`
  - `frontend/src/components/layout/WorkspacePanel.tsx`
  - `frontend/src/components/layout/workspace-data.ts`
- Removed the flows workspace summary contract from:
  - `frontend/src/lib/api.ts`
  - `frontend/src/lib/types.ts`
  - `backend/api/sessions.py`
- Updated frontend contract/tests to expect no `selected_workflow` request field and the current RNA-seq quick-start copy.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts src/test/app-shell.contract.test.tsx src/components/chat/ChatInput.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_audit_logging.py -q`
