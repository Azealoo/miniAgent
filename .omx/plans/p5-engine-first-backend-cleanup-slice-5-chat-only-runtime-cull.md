# P5 Slice 5 Chat-Only Runtime Cull

Date: 2026-04-02

## Goal

Finish the backend pivot from "engine-first with legacy compatibility" to "chat-engine-only" by deleting workflow and protocol execution paths that no longer belong in the backend runtime.

## Scope

This slice removes workflow/protocol execution from the live backend path while preserving the ordinary chat surface and a minimal read-only compatibility stub where the frontend still expects one.

## Files

- `backend/runtime/query_engine.py`
- `backend/api/chat.py`
- `backend/api/sessions.py`
- `backend/runtime/turn_ledger.py`
- deleted modules:
  - `backend/protocol_executor.py`
  - `backend/workflow_chat.py`
  - `backend/workflow_runner.py`
  - `backend/workflow_streaming.py`
  - `backend/reproducibility_drills.py`
  - `backend/graph/workflow_workspace.py`
- test updates:
  - `backend/tests/test_runtime_query_engine.py`
  - `backend/tests/test_chat_streaming.py`
  - `backend/tests/test_audit_logging.py`
  - `backend/tests/test_chat_engine_health.py`
  - deleted suites:
    - `backend/tests/test_protocol_executor.py`
    - `backend/tests/test_workflow_chat.py`
    - `backend/tests/test_workflow_runner.py`

## Completed Work

1. Removed protocol/workflow compatibility branching from `QueryEngine`, leaving compliance preflight, evidence review gating, and ordinary harness dispatch as the only runtime turn path.
2. Kept `selected_workflow` as an accepted compatibility request field in `/api/chat`, but made the chat runtime ignore it.
3. Removed workflow SSE handling from the live chat route.
4. Deleted the workflow/protocol execution modules and their dedicated backend test suites.
5. Kept `/api/sessions/workflows/summary` as a minimal compatibility stub returning `{"items": []}` so the shell can stay calm while backend workflow execution is gone.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_audit_logging.py -q`
  - `34 passed`
- `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m py_compile backend/runtime/query_engine.py backend/api/chat.py backend/api/sessions.py backend/tests/test_runtime_query_engine.py backend/tests/test_chat_streaming.py backend/tests/test_audit_logging.py`
- `rg -n "workflow_chat|workflow_runner|workflow_workspace|protocol_executor|workflow_streaming" backend -S`
  - remaining matches are example payload strings or negative assertions, not live imports

## Exit Conditions

- Ordinary chat has one obvious runtime path.
- Workflow/protocol execution is no longer implemented in the backend.
- Deleted modules are no longer imported by live backend code.
- The remaining backend surface is chat, access, sessions, and files.
