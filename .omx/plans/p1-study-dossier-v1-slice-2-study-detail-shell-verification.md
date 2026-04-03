# P1 Study Dossier v1 - Slice 2 - Verification

## Required Test Coverage Added In The Slice

- backend regression proving `GET /api/studies/{study_id}` reuses `dataset_manifest.id` grouping and returns the derived detail payload for a valid study
- backend regression proving the new detail route returns `404` for an unknown study id and keeps inspection access enforcement intact
- backend regression proving newest valid workflow, evidence, compliance, QA, and checklist artifacts drive the detail payload fields and run ordering
- frontend contract test proving selecting a study loads `/api/studies/{study_id}` and renders `Overview`, `Runs`, `Evidence & Claims`, and `Compliance & QA` states from the mocked detail contract
- frontend contract coverage for detail loading and error handling without regressing the existing study list behavior

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_studies_api.py -q`
Purpose: verify the additive detail route, detail derivation, missing-study behavior, and the unchanged summary route coverage.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok or app_import_does_not_require_tiktoken'`
Purpose: confirm the additive router change does not break app import or protected health behavior.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: keep the new study detail types, API validation, and workspace wiring type-safe.

4. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: exercise the mocked study detail contract and detail-shell rendering path without requiring a live backend.

## Exit Criteria

- all four commands pass
- `GET /api/studies/{study_id}` is additive and read-only
- `GET /api/studies` remains compatible with the slice 1 contract
- the first dossier detail shell renders only the planned sections
- no persisted `study` or `study_dossier` artifact is introduced anywhere under `backend/artifacts/` or `backend/storage/`
