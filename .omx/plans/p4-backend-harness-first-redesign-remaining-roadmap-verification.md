# P4 Backend Harness-First Redesign Remaining Roadmap Verification

Date: 2026-04-02

## Purpose

Lock the verification expectations for the remaining P4 slices so future implementation chats can execute one slice at a time without reopening the phase-level success criteria.

## Slice 4 Verification

Use:
- `.omx/plans/p4-backend-harness-first-redesign-slice-4-bounded-verification-repair-loop-verification.md`

Must prove:
- one non-pass verifier result can trigger exactly one repair retry
- the repair pass receives explicit plan + verifier + prior-draft context
- no third pass is possible
- both passes remain visible in the transcript/session artifacts

## Slice 5 Verification

Use:
- `.omx/plans/p4-backend-harness-first-redesign-slice-5-runtime-turn-ledger-and-finalization-verification.md`

Must prove:
- transcript blocks and assistant segments can be assembled from runtime-owned state rather than route-local accumulators
- accepted user turns and finalized assistant segments still persist correctly across multi-pass turns
- existing SSE clients still receive compatible `token`, `tool_*`, `plan_*`, `verification_result`, `new_response`, `done`, and `title` behavior

## Slice 6 Verification

Use:
- `.omx/plans/p4-backend-harness-first-redesign-slice-6-legacy-dispatch-quarantine-verification.md`

Must prove:
- ordinary chat no longer branches through legacy workflow/protocol logic by default
- legacy workflow or protocol requests still work through the explicit compatibility path retained for migration
- plain chat, helper-agent turns, and legacy workflow runs all preserve session and streaming artifacts

## Phase-Close Confidence Sweep

When Slice 6 lands, run a final phase-close sweep:

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && NEXT_DIST_DIR=.next-build /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`

## Phase Done Means

- the runtime, not the route, is the center of ordinary chat lifecycle behavior
- bounded repair behavior is verified and auditable
- legacy workflow/protocol behavior is clearly quarantined rather than architecturally central
- backend and frontend contracts still compile and pass at full-suite confidence
