# P1 Study Dossier v1 - Slice 4 - Verification

## Required Test Coverage Added In The Slice

- backend regression proving `timeline` is derived newest-first across mixed study artifact classes without changing the existing detail fields
- backend regression proving timeline items keep truthful label/status mapping and workflow identity fallback behavior
- backend regression proving valid studies with no qualifying post-manifest activity return `timeline: []`
- frontend contract test proving the selected dossier renders the additive `Timeline` section from mocked detail data
- frontend contract coverage for a truthful empty-state render when the selected study has no timeline items

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_studies_api.py -q`
Purpose: verify additive study-detail timeline derivation and keep the existing summary/detail/output regressions green.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok or app_import_does_not_require_tiktoken'`
Purpose: confirm the additive read-model change does not break app import or protected health behavior.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: keep the extended study detail types, validator, and dossier wiring type-safe.

4. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: exercise the mocked `Timeline` contract and empty-state rendering path without requiring a live backend.

## Exit Criteria

- all four commands pass
- `GET /api/studies/{study_id}` remains additive and read-only
- the dossier adds only the planned `Timeline` section in this slice
- no persisted `study`, `study_dossier`, or study-timeline artifact is introduced anywhere under `backend/artifacts/` or `backend/storage/`
- no workflow-step playback, chat chronology, or connector history is introduced under the guise of the timeline
