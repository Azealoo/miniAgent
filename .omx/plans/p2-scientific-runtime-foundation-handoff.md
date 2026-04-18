# P2 Scientific Runtime Foundation - Retroactive Handoff

## Why This Note Exists

- The runtime foundation work landed and verified, but the OMX task and review trail was not recorded when the slice work happened.
- Slice 5 required a durable final verification verdict plus residual risk in the current feature log or a follow-on plan note.
- This note is intentionally retrospective. It records what landed and what was verified without pretending the original slice queue was tracked contemporaneously.

## Landed Scope

### Slice 1 - Prompt Context And Tool Manifest Foundation

- Added bounded project-instruction discovery and optional git-context inclusion in `backend/graph/prompt_builder.py`.
- Added typed tool manifest and registry support in `backend/tools/registry.py` and runtime tool helpers in `backend/tools/__init__.py`.
- Verification previously run for this slice:
  - `backend/tests/test_prompt_builder.py`
  - `backend/tests/test_tools.py`
  - `backend/tests/test_tool_output_contracts.py`

### Slice 2 - Session Schema vNext With Typed Content Blocks

- Added additive typed assistant blocks and legacy-field derivation in `backend/graph/session_manager.py`.
- Persisted and surfaced ordered blocks in `backend/api/chat.py` and `backend/api/sessions.py`.
- Kept frontend history/session consumers compatible in `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, and `frontend/src/lib/store.tsx`.
- Verification previously run for this slice:
  - `backend/tests/test_session_manager.py`
  - `backend/tests/test_chat_streaming.py`
  - frontend `npm run typecheck`
  - frontend `npm test -- src/test/app-shell.contract.test.tsx`

### Slice 3 - Tool Policy Middleware

- Added explicit pre-tool and post-tool policy evaluation in `backend/tools/policy.py`, `backend/tools/policy_types.py`, and `backend/tools/policy_wrappers.py`.
- Switched runtime tool loading to policy-wrapped tools in `backend/graph/agent.py` and request-scoped policy context plumbing in `backend/api/chat.py`.
- Verification previously run for this slice:
  - `backend/tests/test_chat_streaming.py`
  - `backend/tests/test_compliance_preflight.py`
  - `backend/tests/test_evidence_review.py`
  - `backend/tests/test_tool_output_contracts.py`
  - `backend/tests/test_tool_policy.py`

### Slice 4 - Layered Runtime Config

- Added layered config loading in `backend/runtime_config.py` and `backend/runtime_config_types.py`.
- Kept `backend/config.json` as the project-layer write target while reading user, project, and local layers in `backend/config.py`.
- Verification previously run for this slice:
  - `backend/tests/test_config.py`
  - `backend/tests/test_prompt_builder.py`
  - `backend/tests/test_tool_policy.py`
  - `backend/tests/test_api_health.py -k 'health_returns_ok or app_import'`

### Slice 5 - Runtime Verification And Hardening Sweep

- The runtime foundation remains additive and backward-compatible in the current tree.
- Final verification results are recorded below after a fresh rerun performed as part of the bookkeeping repair.

## Final Verification Verdict

- Verdict: ready for reviewer confirmation.
- Fresh bookkeeping-repair verification run on 2026-04-01:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py tests/test_tools.py tests/test_tool_output_contracts.py tests/test_session_manager.py tests/test_chat_streaming.py tests/test_config.py tests/test_api_health.py -q`
    - Result: `272 passed in 3.17s`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
    - Result: passed
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
    - Result: `9 passed`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && NEXT_DIST_DIR=.next-build /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`
    - Result: passed, production build completed and prerendered the shipped app routes

## Residual Risk

- No blocking code or regression issue was found in the landed runtime foundation.
- The remaining risk before final approval is review closure only: this phase now has a real OMX task and handoff note, but it still needs the reviewer to attach the final approval or changes-requested verdict to that task.
