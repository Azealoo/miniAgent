# Backend Harness-First Redesign Program Verification Map

Date: 2026-04-02

## Slice 1

- Runtime route regression:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- Session persistence regression:
  - confirm accepted user turns are saved even when execution stops after preflight, evidence gating, or mid-stream failure
- Frontend contract safety:
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Slice 2

- Tool contract regression:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tools.py tests/test_tool_policy.py -q`
- Helper-agent exposure regression:
  - planner sees only planner-exposed read-only tools
  - verifier remains non-mutating and still has `evidence_review` where intended

## Slice 3

- Streaming contract regression:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_session_manager.py -q`
- Backward-compatibility assertions:
  - legacy clients can ignore `plan_created`, `plan_updated`, and `verification_result`
  - persisted `plan` and `verification` blocks round-trip through session load paths

## Slice 4

- Planner/verifier loop behavior:
  - planner runs before substantive tool use on complex turns
  - trivial turns can bypass the planner
  - verifier can trigger one repair loop and then stops
- Compatibility regression:
  - workflow requests still run through the adapter during migration
  - ordinary chat no longer depends on workflow-first route branching

## Program closeout

- Full backend:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest -q`
- Frontend compile + tests:
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && NEXT_DIST_DIR=.next-build PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`
