# P4 Slice 6 Legacy Workflow And Protocol Dispatch Quarantine Verification

Date: 2026-04-02

## Verification Plan

1. Ordinary chat routing
   - prove ordinary no-workflow chat enters the harness path directly
   - prove planner/verifier/repair turns still function after legacy dispatch is split away
2. Legacy compatibility routing
   - prove explicit workflow requests still run through the retained compatibility adapter
   - prove explicit protocol execution still produces the expected tool and text artifacts
3. Contract compatibility
   - prove legacy `workflow_*` streaming events still surface for legacy runs
   - prove session history still loads both ordinary harness turns and legacy workflow turns
4. Confidence
   - run the full backend suite
   - keep frontend typecheck green
   - preferably run full frontend tests and build at phase close

## Commands

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- recommended at phase close:
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && NEXT_DIST_DIR=.next-build /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`

## Done Means

- ordinary chat no longer carries branch-heavy workflow/protocol architecture
- legacy compatibility remains explicit and verified
- the phase can close on a harness-first runtime with compatible contracts
