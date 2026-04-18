# P1 Study Dossier v1 - Slice 1 - Verification

## Required Test Coverage Added In The Slice

- backend aggregation regression proving study summaries group by `dataset_manifest.id`
- backend state-derivation regression proving the newest workflow, evidence, compliance, QA, and export artifacts drive the returned summary states
- backend access regression proving `GET /api/studies` remains inspection-scoped
- frontend contract test proving the `Studies` workspace loads mocked `/api/studies` data, renders summary metadata, and supports local search/sort plus selected-study preview

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_studies_api.py -q`
Purpose: verify grouping, derived summary fields, and route access behavior for the new studies API.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok or app_import_does_not_require_tiktoken'`
Purpose: confirm the additive router registration does not break app import or the protected health contract.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: keep the new study contract, workspace mode, and component wiring type-safe.

4. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: exercise the mocked studies contract and the new workspace rendering path without needing a live backend.

## Exit Criteria

- all four commands pass
- the slice adds only `GET /api/studies`
- no persisted `study` or `study_dossier` artifact is introduced anywhere under `backend/artifacts/` or `backend/storage/`
- the frontend shows backend-derived states truthfully and keeps search/sort client-side
