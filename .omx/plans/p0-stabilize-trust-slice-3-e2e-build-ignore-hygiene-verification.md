# P0 Stabilize Trust - Slice 3 - Verification

## Required Coverage Added In The Slice

- repo-level ignore coverage for the generated `frontend/.next-e2e-build/` directory
- verification that the real E2E test path can still materialize that directory and leave it ignored

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run test:e2e -- e2e/app-shell.e2e.spec.ts`
Purpose: exercise the real Playwright verification path that creates `frontend/.next-e2e-build/`.

2. `cd /gpfs/projects/hrbomics/miniAgent && git status --short --ignored -- frontend/.next-e2e-build`
Purpose: confirm the generated directory is ignored (`!! frontend/.next-e2e-build/`) instead of appearing as an untracked worktree artifact.

## Exit Criteria

- the E2E command passes
- `git status --short --ignored -- frontend/.next-e2e-build` reports the directory as ignored
- no naming-cleanup files are changed in the slice
