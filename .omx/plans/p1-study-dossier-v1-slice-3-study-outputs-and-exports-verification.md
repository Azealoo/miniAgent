# P1 Study Dossier v1 - Slice 3 - Verification

## Required Test Coverage Added In The Slice

- backend regression proving `outputs.latest_run_outputs` comes from the newest valid workflow run's persisted `outputs` refs
- backend regression proving `outputs.exports` collects valid study-scoped export artifacts newest-first without changing the existing slice 2 detail fields
- backend regression proving output/export arrays stay explicit empty arrays when the selected study lacks those artifacts
- frontend contract test proving the selected dossier renders `Outputs & Exports` from the mocked additive detail contract
- frontend contract coverage for truthful empty-state rendering when latest-run outputs or export artifacts are absent

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_studies_api.py -q`
Purpose: verify additive study-detail output/export derivation and keep the existing summary/detail regressions green.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok or app_import_does_not_require_tiktoken'`
Purpose: confirm the additive read-model change does not break app import or protected health behavior.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: keep the extended study detail types, validator, and dossier wiring type-safe.

4. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: exercise the mocked `Outputs & Exports` contract and empty-state rendering path without requiring a live backend.

## Exit Criteria

- all four commands pass
- `GET /api/studies/{study_id}` remains additive and read-only
- the dossier adds only the planned `Outputs & Exports` section in this slice
- `Timeline` remains deferred
- no persisted `study` or `study_dossier` artifact is introduced anywhere under `backend/artifacts/` or `backend/storage/`
