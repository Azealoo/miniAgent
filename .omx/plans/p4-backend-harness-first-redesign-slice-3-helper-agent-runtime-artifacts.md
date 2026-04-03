# P4 Slice 3 Helper-Agent Runtime Artifacts

Date: 2026-04-02

## Goal

Make planner and verifier helper-agent outputs first-class harness artifacts by emitting additive runtime events and persisting typed transcript blocks, without breaking the existing tool trace, SSE clients, or session-history consumers.

## Scope

This slice is limited to runtime event emission, typed transcript persistence, and compatibility updates needed so current frontend/session consumers can safely load the new blocks. It does not yet add a repair loop or force planner/verifier invocation.

## Files

- `backend/runtime/query_engine.py`
- `backend/api/chat.py`
- `backend/graph/session_manager.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/api.stream-chat.test.ts`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/editor/TurnDetailsPanel.tsx`
- `context/current-feature.md`

## Must Do

1. Detect successful `plan_agent` and `verification_agent` tool results in the runtime and emit additive helper-agent events:
   - `plan_created`
   - `plan_updated`
   - `verification_result`
2. Persist typed `plan` and `verification` transcript blocks alongside existing `tool_use`, `tool_result`, `retrieval`, `workflow_event`, and `text` blocks.
3. Keep legacy fields and the existing tool trace intact so older consumers still see normal `tool_calls` and text content.
4. Update frontend/session validators and transcript summaries so the new persisted block types load safely without breaking current UX.
5. Prove the additive contract with focused backend and frontend tests.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts src/components/editor/TurnDetailsPanel.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Exit Conditions

- planner/verifier helper-agent results produce additive runtime events
- session history persists typed `plan` and `verification` blocks
- older transcript/tool fields still round-trip
- current frontend validators and detail views accept the new blocks without regressions

## Execution Note

Slice 3 is now implemented.

- `backend/runtime/query_engine.py` emits additive `plan_created`, `plan_updated`, and `verification_result` events when successful helper-agent tool results appear in the main agent stream.
- `backend/api/chat.py` now streams those events and persists typed `plan` / `verification` blocks alongside the existing tool trace and text blocks.
- `backend/graph/session_manager.py` normalizes the new block types without disturbing legacy content, tool calls, workflow events, or retrievals.
- `frontend/src/lib/types.ts` and `frontend/src/lib/api.ts` now accept the new block types, while the stream parser safely ignores the additive SSE events until a richer live UI uses them.
- `frontend/src/components/chat/TurnActivityFeed.tsx` and `frontend/src/components/editor/TurnDetailsPanel.tsx` summarize the new persisted artifacts without changing the existing transcript shape.
