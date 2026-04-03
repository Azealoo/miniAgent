# P5 Slice 3 Legacy Compatibility Isolation

Date: 2026-04-02

## Goal

Make `backend/runtime/query_engine.py` read like the normal engine path first by moving workflow/protocol compatibility helpers behind a smaller named runtime boundary, while keeping the legacy product behavior that still matters intact.

## Scope

This slice is structural refactoring only. It should isolate the legacy compatibility code paths without deleting valid workflow/protocol functionality and without changing the existing user-visible compatibility behavior.

## Likely Files

- `backend/runtime/query_engine.py`
- `backend/runtime/legacy_compat.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- optional support changes:
  - `context/current-feature.md`

## Must Do

1. Move protocol/workflow compatibility orchestration behind a smaller runtime helper boundary.
2. Leave `QueryEngine` centered on:
   - accepted turn lifecycle
   - compliance and evidence gating
   - ordinary harness dispatch
3. Preserve current compatibility behavior for:
   - selected workflow runs
   - protocol-execution turns
   - existing workflow events and persisted artifacts
4. Keep focused tests proving both the ordinary engine path and the compatibility paths still work.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "run_protocol_compatibility_turn|run_workflow_compatibility_turn|LegacyCompatibilityTurn|protocol_executor|workflow_chat" backend/runtime -S`

## Exit Conditions

- `QueryEngine` is shorter or clearer on the normal engine path
- compatibility helpers live behind a smaller, named boundary
- selected-workflow and protocol-execution behavior still round-trip cleanly
