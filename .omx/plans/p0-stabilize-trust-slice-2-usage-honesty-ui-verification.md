# P0 Stabilize Trust - Slice 2 - Verification

## Required Test Coverage Added In The Slice

- contract coverage proving the Usage tab renders an exact/model-aligned honesty cue when `tokenizer_accuracy = "model_aligned"`
- contract coverage proving the Usage tab renders an approximate/fallback honesty cue when `tokenizer_accuracy = "approximate"`
- browser-level assertion covering the Usage panel with the honesty cue visible in the mocked app-shell flow

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: confirm the Usage UI changes stay consistent with the existing token contract.

2. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: verify the contract-shaped Usage tab assertions for both exact and approximate token payloads.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run test:e2e -- e2e/app-shell.e2e.spec.ts`
Purpose: verify the honesty cue survives the browser-level app-shell flow that exercises the real Usage inspector path.

## Exit Criteria

- all three commands pass
- the Usage tab exposes a clear honesty cue in both exact and fallback modes
- no backend contract changes are required beyond slice 1
- `.next-e2e-build` cleanup and naming cleanup remain explicitly deferred instead of being silently mixed into this slice
