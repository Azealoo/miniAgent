# P5 Slice 2 Public Engine Surface Cleanup

Date: 2026-04-02

## Goal

Make the intended `QueryEngine` API obvious by centering ordinary chat on `run_turn(...)`, demoting legacy helper entrypoints that product code no longer uses, and keeping compatibility behavior available only through named boundaries.

## Scope

This slice is limited to the public engine surface and its directly related tests. It should not delete valid workflow or protocol product capabilities, but it may remove or demote engine helper methods whose only remaining callers are stale tests or compatibility-era scaffolding.

## Likely Files

- `backend/runtime/query_engine.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- optional support changes:
  - `backend/api/chat.py`
  - `context/current-feature.md`

## Must Do

1. Define one obvious ordinary-chat entrypoint:
   - `run_turn(...)` remains the primary public runtime surface
2. Demote or remove legacy helper entrypoints if product code no longer relies on them:
   - `submit_turn(...)`
   - `submit_message(...)`
   - direct legacy-resolution helpers that only survive for older internal shapes
3. Keep legacy workflow/protocol compatibility behavior intact through the runtime paths that still matter for product behavior.
4. Update focused tests so they cover the intended engine boundary instead of obsolete helper shapes.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "submit_turn\\(|submit_message\\(" backend -S`

## Exit Conditions

- the ordinary chat runtime has one obvious public entrypoint
- stale helper APIs are removed or clearly marked as legacy-only
- focused runtime/chat tests cover the intended engine surface
- workflow/protocol compatibility still works where product behavior depends on it
