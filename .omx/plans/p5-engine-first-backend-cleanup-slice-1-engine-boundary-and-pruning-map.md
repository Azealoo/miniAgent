# P5 Slice 1 Engine Boundary And Pruning Map

Date: 2026-04-02

## Goal

Create a deletion-safe map of the backend orchestration surface so the cleanup phase can remove only non-relevant engine-path code, not real product capabilities.

## Scope

This slice is a boundary and inventory pass. It should document what stays central, what gets isolated, and what becomes a real deletion candidate before the first structural cleanup lands.

## Likely Files

- `backend/runtime/query_engine.py`
- `backend/api/chat.py`
- `backend/runtime/turn_ledger.py`
- `backend/runtime/helper_agent_runner.py`
- `backend/protocol_executor.py`
- `backend/workflow_chat.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_protocol_executor.py`
- `backend/tests/test_workflow_chat.py`
- `context/current-feature.md`

## Must Do

1. Define the intended public engine surface:
   - ordinary chat should center on `run_turn(...)`
   - identify whether `submit_turn(...)`, `submit_message(...)`, and direct legacy helpers are still real public API or only cleanup candidates
2. Separate code into three buckets:
   - keep in the engine path
   - isolate behind named legacy compatibility boundaries
   - delete once unreferenced
3. Verify import-level dependencies so valid workflow/protocol product capabilities are not mistaken for dead code.
4. Record the first concrete cleanup slice that should follow from the boundary map.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "submit_turn\\(|submit_message\\(|run_turn\\(|run_protocol_compatibility_turn\\(|run_workflow_compatibility_turn\\(" backend -S`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "from workflow_chat|from protocol_executor|selected_workflow|workflow_|protocol" backend backend/tests frontend -S`
- confirm the resulting keep/move/remove map is reflected in:
  - `.omx/plans/p5-engine-first-backend-cleanup.md`
  - `context/current-feature.md`
  - the queued OMX team tasks for the next slice

## Exit Conditions

- the phase has an explicit keep/move/remove map
- the first cleanup implementation slice is identified and queueable
- no code has been deleted speculatively
