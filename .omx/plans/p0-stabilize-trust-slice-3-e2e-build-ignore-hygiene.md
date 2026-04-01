# P0 Stabilize Trust - Slice 3 - E2E Build Ignore Hygiene

## Goal

Keep the required Playwright/E2E build path from polluting the repo by ignoring `frontend/.next-e2e-build/` at the repo root, without changing runtime behavior or broadening the slice into naming cleanup.

## Why This Slice Comes Next

- It is the smallest remaining unfinished P0 cleanup item.
- The required `npm run test:e2e` path materializes `frontend/.next-e2e-build/`, and the worktree currently shows that directory as untracked noise.
- Human-facing BioAPEX naming cleanup spans README copy, backend app/service labels, workspace identity text, tool user-agent text, and package metadata, so it is broader and should stay isolated in the final P0 slice.

## Files Likely To Change

- `.gitignore`

## Slice Must Do

1. Add a repo-level ignore rule for `frontend/.next-e2e-build/` alongside the existing Next.js build artifacts.
2. Preserve the existing `build:e2e`, `start:e2e`, and Playwright wiring; this slice is hygiene only.
3. Keep the change additive so rerunning the E2E verification path no longer leaves an untracked build directory in the worktree.

## Non-Goals In This Slice

- human-facing `miniOpenClaw`/`Claw` to `BioAPEX` naming cleanup
- package metadata, backend health response, or backend app title changes
- Playwright config or Next build contract changes

## Done Means

- root `.gitignore` ignores `frontend/.next-e2e-build/`
- the existing E2E verification path still runs successfully
- `git status --short --ignored -- frontend/.next-e2e-build` reports the generated directory as ignored instead of untracked

## Dependencies

- depends on the existing `build:e2e` / `test:e2e` harness already present in `frontend/package.json` and `frontend/playwright.config.ts`

## Serial Or Parallel

This slice should remain serial.

Why:
- it is a one-path hygiene fix on the exact verification route we already depend on
- splitting it would add overhead without closing any additional roadmap acceptance
- the naming cleanup is broader and should remain isolated until this worktree-noise fix is landed

## Follow-On Slice

After this, the only remaining P0 work should be the human-facing BioAPEX naming cleanup while preserving machine-facing compatibility.
