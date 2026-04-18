# P2 Scientific Runtime Foundation - Verification

## Slice 1 - Prompt Context And Tool Manifest Foundation

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py -q`
Purpose: prove prompt assembly still works while adding bounded instruction discovery and prompt-budget coverage.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tools.py tests/test_tool_output_contracts.py -q`
Purpose: prove the new tool-manifest layer does not break tool loading or the canonical `tool_result.v1` contract.

## Slice 2 - Session Schema vNext With Typed Content Blocks

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_session_manager.py tests/test_chat_streaming.py -q`
Purpose: prove backward-compatible session loading, typed-block persistence, and streamed tool/chat behavior.

2. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: keep the session/history API and any new message-block types aligned with frontend contracts.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: verify the app shell still renders and consumes the session/chat contract after the session-schema change.

## Slice 3 - Tool Policy Middleware

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_compliance_preflight.py tests/test_evidence_review.py -q`
Purpose: prove pre/post tool policy behavior, compliance gating, and evidence review requirements stay truthful in the streamed runtime path.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tool_output_contracts.py -q`
Purpose: confirm policy annotation or blocking does not corrupt `tool_result.v1` normalization.

## Slice 4 - Layered Runtime Config

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_config.py -q`
Purpose: prove layered config precedence, typing, and compatibility behavior.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok or app_import'`
Purpose: confirm config-loading changes do not break protected health paths or app startup behavior.

## Slice 5 - Runtime Verification And Hardening Sweep

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py tests/test_tools.py tests/test_tool_output_contracts.py tests/test_session_manager.py tests/test_chat_streaming.py tests/test_config.py tests/test_api_health.py -q`
Purpose: run the core runtime regression suite as one final backend proof.

2. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: confirm frontend type contracts still match the hardened backend runtime.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: verify the inspection shell still behaves correctly after the runtime foundation work.

## Exit Criteria

- Slice 1 prompt discovery and tool manifest work lands without breaking current tool contracts.
- Slice 2 adds typed session blocks without regressing old sessions or current chat rendering.
- Slice 3 enforces runtime policy through explicit middleware rather than hidden special cases.
- Slice 4 introduces layered runtime config without breaking existing config paths.
- Slice 5 proves the new foundations work together end-to-end.
