# P4 Slice 6 Legacy Workflow And Protocol Dispatch Quarantine

Date: 2026-04-02

## Goal

Finish the harness-first shift by moving workflow/protocol compatibility out of the ordinary chat hot path so default `/api/chat` behavior is clearly centered on the general harness loop.

## Scope

This slice is limited to dispatch architecture. It should preserve backward compatibility for explicit legacy workflow/protocol requests during migration, but those paths should no longer dominate the default chat turn design.

## Likely Files

- `backend/runtime/query_engine.py`
- `backend/api/chat.py`
- `backend/protocol_executor.py`
- `backend/workflow_chat.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `context/current-feature.md`

## Must Do

1. Separate ordinary harness turns from legacy compatibility dispatch:
   - ordinary chat should enter the planner/executor/verifier harness path directly
   - explicit workflow or protocol runs should go through a named compatibility adapter or dedicated entry path
2. Remove branch-heavy legacy dispatch from the main ordinary-chat path in `backend/runtime/query_engine.py`.
3. Preserve migration compatibility:
   - explicit workflow requests still run
   - explicit protocol execution still runs
   - existing `workflow_*` events and durable workflow artifacts remain intact for those legacy paths
4. Keep the user-visible contract stable while making the internal architecture clearer:
   - `/api/chat` can still accept legacy-compatible fields during the migration window
   - ordinary chat without explicit legacy intent should no longer pay architectural complexity for those branches
5. Update tests so plain chat, repair-loop turns, and legacy workflow/protocol runs each exercise the correct dispatch path.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- recommended phase-close sweep after landing:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest -q`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && NEXT_DIST_DIR=.next-build /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`

## Exit Conditions

- ordinary chat is unmistakably harness-first in the runtime boundary
- workflow/protocol routing survives only as explicit compatibility behavior
- legacy workflow artifacts and events still round-trip during the migration window
- the phase can close without the route remaining architecturally workflow-first

## Depends On

- `.omx/plans/p4-backend-harness-first-redesign-slice-5-runtime-turn-ledger-and-finalization.md`
