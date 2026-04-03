# P3 Modern Agent UX - Post-Slice Stabilization E2E Pass

## Goal

Harden the completed modern-agent UX phase with one real browser path for compact history and by aligning older E2E expectations to the shipped transcript policy.

## Scope

- Add a Playwright scenario for dense session history plus archived-turn reopening.
- Update the existing streamed-chat browser test so it matches the current quiet-final-transcript contract.
- Keep the pass frontend-only and verification-focused.

## Files In Scope

- `frontend/e2e/app-shell.e2e.spec.ts`
- `context/current-feature.md`

## Must Do

1. Add a browser test that loads a dense saved session with continuity summaries.
2. Prove the UI can expand an older visible turn and reopen an archived summary batch.
3. Update stale browser assertions that still expect permanent retrieval cards in the final chat transcript.
4. Run the focused app-shell E2E spec end to end.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run test:e2e -- e2e/app-shell.e2e.spec.ts`

## Done Means

- the new compact-history path has real browser coverage
- the browser suite matches the shipped live-vs-final transcript behavior
