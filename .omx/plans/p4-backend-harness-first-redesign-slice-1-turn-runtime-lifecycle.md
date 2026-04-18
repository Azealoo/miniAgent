# P4 Slice 1 Turn Runtime Lifecycle

Date: 2026-04-02

## Goal

Move the accepted-turn lifecycle deeper into the runtime boundary so `backend/api/chat.py` stops being the de facto conversation engine.

## Scope

This slice is limited to runtime extraction and compatibility preservation. It does not yet add new planner/verifier SSE events or a repair loop.

## Files

- `backend/api/chat.py`
- `backend/runtime/query_engine.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `context/current-feature.md`

## Must Do

1. Extend `QueryEngine` so it can own more than just workflow/protocol/agent dispatch.
2. Persist the accepted user turn from the runtime path before the long-running loop begins.
3. Reduce the amount of pre-gate branching in `backend/api/chat.py`.
4. Keep the route responsible for SSE transport and observability only where practical in this slice.
5. Preserve legacy event order and session-history compatibility.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Exit Conditions

- runtime tests cover the extracted lifecycle behavior
- chat streaming tests still pass
- frontend typecheck stays green
- the resulting code leaves a cleaner path for planner/verifier event and loop slices

## Execution Note

Slice 1 is now implemented.

- `backend/runtime/query_engine.py` owns accepted-turn persistence signaling, compliance preflight, evidence-review gate orchestration, and post-gate dispatch into the existing workflow/agent compatibility paths.
- `backend/api/chat.py` is thinner and now consumes runtime lifecycle events rather than orchestrating preflight/gate logic directly.
- Added focused regressions for the new runtime lifecycle plus a chat-streaming regression that proves accepted user turns persist before an executor failure.
- Verification passed with focused backend runtime tests, frontend typecheck, and a full backend suite rerun.
