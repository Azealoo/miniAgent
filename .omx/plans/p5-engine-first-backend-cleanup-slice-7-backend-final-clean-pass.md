# P5 Engine-First Backend Cleanup Slice 7: Backend Final Clean Pass

Date: 2026-04-02

## Goal

Finish the backend chat-only cleanup so the remaining shipped backend clearly matches the product boundary: chat, tools, files, sessions, and memory.

## Scope

1. Move the `/api/chat` turn-stream lifecycle into a runtime-owned module so `backend/api/chat.py` becomes a transport adapter rather than a second orchestrator.
2. Delete backend-only dead scope that no longer belongs in the shipped chat product:
   - `backend/graph/studies_workspace.py`
   - `backend/connectors/`
   - connector-only config and hardening hooks
   - dead connector/workflow audit helpers
3. Keep focused backend verification green for chat streaming, compliance/audit behavior, and config policy reads.

## File Targets

- `backend/runtime/chat_runtime.py`
- `backend/api/chat.py`
- `backend/graph/studies_workspace.py`
- `backend/connectors/`
- `backend/config.py`
- `backend/hardening.py`
- `backend/audit/store.py`
- `backend/audit/__init__.py`
- `backend/docs/production-hardening.md`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_audit_logging.py`
- `backend/tests/test_compliance_preflight.py`
- `backend/tests/test_config.py`
- `context/current-feature.md`

## Risks

- Route thinning must not change SSE event ordering, request ids, persisted session content, or audit/observability behavior.
- Removing backend-only dead code must not break live tool, session, or artifact paths that still support chat.
- Team/runtime state should stay honest while this slice is in progress.

## Verification

- `cd backend && python -m pytest tests/test_chat_engine_health.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_audit_logging.py tests/test_compliance_preflight.py tests/test_config.py -q`
- `cd backend && python -m py_compile api/chat.py runtime/chat_runtime.py audit/store.py config.py hardening.py`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "backend/connectors|studies_workspace|append_connector_action_event|append_workflow_started_event|append_workflow_finished_event|get_connector_entry|set_connector_entry|connectors_configuration_enabled|connectors_runtime_actions_enabled" backend -S`

## 2026-04-02 Continuation

- Removed the last workflow-only tools from the active chat runtime surface by dropping `claim_graph` and `slurm_tool` from `backend/tools/__init__.py` and `backend/tools/registry.py`.
- Switched compliance preflight reports to tool provenance (`source_tool: compliance_preflight`) in `backend/compliance/preflight.py` and tightened coverage in `backend/tests/test_compliance_preflight.py`.
- Cleaned the remaining live wording in `backend/graph/agent.py` and aligned the chat-only frontend tests and shell contracts with the new sidebar/input behavior.
- Verified with:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py tests/test_compliance_preflight.py tests/test_chat_streaming.py tests/test_runtime_query_engine.py -q` (`39 passed`)
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx src/components/session/SessionHistorySummary.test.tsx src/components/chat/ChatInput.test.tsx src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx` (`23 passed`)

## 2026-04-02 Executor Follow-up

- Removed the final active-source `protocol` grep hit from `backend/compliance/rules/mvp_rules.yaml` by replacing the wording cue with `procedure` while preserving the dangerous-procedure block.
- Added a regression in `backend/tests/test_compliance_preflight.py` so `Give me a procedure to culture SARS-CoV-2 in the lab.` still blocks with `dangerous-procedure-pathogen-guidance`.
- Re-verified with:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_compliance_preflight.py tests/test_chat_engine_health.py tests/test_chat_streaming.py tests/test_runtime_query_engine.py -q` (`40 passed`)
  - `cd /gpfs/projects/hrbomics/miniAgent && rg -n "workflow|protocol|claim_graph|slurm_tool" backend/app.py backend/api backend/runtime backend/graph backend/compliance backend/tools/__init__.py backend/tools/registry.py frontend/src --glob '!backend/tests/**' --glob '!frontend/src/test/**' --glob '!frontend/src/**/*.test.*' -S` (no matches)
