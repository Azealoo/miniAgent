# P4 Slice 5 Runtime Turn Ledger And Finalization

Date: 2026-04-02

## Goal

Move multi-pass transcript assembly, assistant-segment persistence, and turn finalization behind the runtime boundary so `backend/api/chat.py` stops acting like the hidden turn ledger.

## Scope

This slice is limited to runtime-owned turn assembly and finalization for ordinary chat. It should preserve the current JSON session format, keep the same SSE contract, and avoid changing legacy workflow/protocol routing yet.

## Likely Files

- `backend/runtime/query_engine.py`
- `backend/runtime/__init__.py`
- `backend/runtime/turn_ledger.py`
- `backend/api/chat.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `context/current-feature.md`

## Must Do

1. Introduce a runtime-owned turn ledger/result object that can accumulate:
   - text segments across one or two passes
   - `tool_use` / `tool_result` blocks
   - `retrieval`, `workflow_event`, `plan`, and `verification` blocks
   - pending tool-call metadata needed for normalized tool traces
   - final `turn_status`, final text, and title-generation eligibility
2. Move the current route-local transcript bookkeeping out of `backend/api/chat.py` and behind the runtime boundary.
3. Make the runtime produce a final turn outcome that is sufficient for:
   - session persistence
   - `done` payload construction
   - optional `title` emission on the first successful assistant turn
4. Keep additive compatibility:
   - existing SSE event names still stream in the same order
   - saved session messages still round-trip existing `tool_calls`, `workflow_events`, `retrievals`, and `blocks`
   - helper-agent artifacts from Slice 3 and repair behavior from Slice 4 remain visible
5. Leave observability and transport glue lightweight in the route, but remove route ownership of the turn transcript itself.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- optional confidence sweep:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest -q`

## Exit Conditions

- `backend/runtime/query_engine.py` owns the multi-pass turn ledger for ordinary chat
- `backend/api/chat.py` no longer builds assistant segments or transcript blocks itself
- first-pass and repair-pass artifacts persist in the same durable order they were streamed
- `done` and optional `title` behavior remain compatible for existing clients

## Depends On

- `.omx/plans/p4-backend-harness-first-redesign-slice-4-bounded-verification-repair-loop.md`
