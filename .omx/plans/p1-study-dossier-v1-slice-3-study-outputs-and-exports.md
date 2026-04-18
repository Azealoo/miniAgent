# P1 Study Dossier v1 - Slice 3 - Study Outputs And Exports

## Goal

Extend the additive, read-only `GET /api/studies/{study_id}` contract so the Studies workspace can render the next dossier section, `Outputs & Exports`, from already-persisted workflow output refs and export artifacts without introducing timeline reconstruction, new persistence, or any study write flow.

## Why This Is The Smallest Remaining Additive Slice

- Slice 2 already shipped the dossier shell plus summary fields that expose `export_available` and per-run `output_count`.
- The backend already persists `workflow_run.outputs` refs plus valid study-scoped `provenance`, `biocompute`, `eln_export`, and `eln_export_archive` registry records.
- The frontend already has path-based inspection and raw-file opening flows, so scientists can inspect these artifacts without any new download or generation route.
- `Timeline` still needs a broader chronology model across mixed artifact classes, which is a larger follow-on slice than exposing the already-available outputs and export paths.

## Exact Route And Type Scope

- Existing route extended in scope:
  - `GET /api/studies/{study_id}`
- Existing dependency reused without contract change:
  - `GET /api/studies`
- Existing file-access dependency reused without contract change:
  - `GET /api/files/raw?path=...`
- Types in scope:
  - `StudyOutputsSummary`
  - `StudyOutputArtifact`
- Existing type extended:
  - `StudyDetail`
- Existing types reused without change:
  - `StudySummary`
  - `StudyOverview`
  - `StudyRunSummary`
  - `StudyEvidenceSummary`
  - `StudyComplianceSummary`
- Types explicitly deferred:
  - `StudyTimelineItem`
  - any export-generation request type
  - any study write/edit type

## Additive Contract

```ts
type StudyOutputArtifact = {
  artifact_type: string;
  path: string;
  run_id: string;
  workflow_slug: string;
  workflow_name: string;
  created_at: string | null;
};

type StudyOutputsSummary = {
  latest_run_outputs: StudyOutputArtifact[];
  exports: StudyOutputArtifact[];
};

type StudyDetail = ExistingStudyDetail & {
  outputs: StudyOutputsSummary;
};
```

## Derivation Rules

1. Preserve every slice 2 `StudyDetail` field exactly and add only `outputs`.
2. Reuse the same valid `dataset_manifest.id` study grouping already shipped in slices 1 and 2.
3. Build `outputs.latest_run_outputs` from the newest valid, loadable `workflow_run` in the study group:
   - iterate that run's `outputs`
   - keep only refs with a non-empty `path`
   - preserve the run document order
   - carry `artifact_type`, `path`, and `run_id` from the output ref
   - carry `workflow_slug` and `workflow_name` from the originating workflow run
   - use the matching valid registry record `created_at` when available, otherwise fall back to the originating workflow run `created_at`
   - if no valid workflow run exists, or the newest valid run has no output refs, return an empty array
4. Build `outputs.exports` from valid study-scoped registry records whose `artifact_type` is one of:
   - `provenance`
   - `biocompute`
   - `eln_export`
   - `eln_export_archive`
5. Sort `outputs.exports` newest-first by registry activity timestamp and de-duplicate by path.
6. For each export entry, carry `artifact_type`, `path`, `run_id`, `created_at`, and resolve `workflow_slug` / `workflow_name` from the matching loadable workflow run when present, falling back to registry workflow identifiers if needed.
7. Keep the slice inspection-only and file-first:
   - no new persisted `study` or `study_dossier` artifact
   - no export generation or mutation route
   - no timeline reconstruction in this slice

## Backend Owner

### File Ownership

- `backend/graph/studies_workspace.py`
- `backend/tests/test_studies_api.py`

### Must Do

1. Extend the existing study-detail read model with the additive `outputs` block only.
2. Reuse the current grouped-study helpers instead of inventing a parallel export/output lookup path.
3. Keep `GET /api/studies` unchanged and preserve every slice 2 field on `GET /api/studies/{study_id}`.
4. Add regressions for:
   - latest-run output derivation from `workflow_run.outputs`
   - newest-first export derivation across `provenance`, `biocompute`, and ELN export artifacts
   - empty outputs/export arrays when no matching study artifacts exist

### Must Not Do

- do not add a new study route
- do not materialize or regenerate exports
- do not add timeline items in this slice
- do not introduce any persistence under `backend/artifacts/` or `backend/storage/`

## Frontend Owner

### File Ownership

- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/components/layout/workspace-data.ts`
- `frontend/src/components/layout/WorkspacePanel.tsx`
- `frontend/src/test/fixtures.ts`
- `frontend/src/test/app-shell.contract.test.tsx`

### Must Do

1. Add `StudyOutputsSummary` and `StudyOutputArtifact` types and extend the `StudyDetail` validator to require the new `outputs` block.
2. Keep the existing studies list and previously shipped dossier sections unchanged.
3. Add an `Outputs & Exports` dossier section with two truthful subsections:
   - `Latest Run Outputs`
   - `Portable Exports`
4. Render entries directly from backend-derived paths and artifact metadata; do not infer output/export state from chat or session text.
5. Reuse existing path-based inspection/raw-open flows for artifact actions instead of adding new routing or download state.
6. Provide explicit empty states when the selected study has no latest-run outputs or no export artifacts yet.

### Must Not Do

- do not add URL routing or new global store state
- do not add export generation, download orchestration, or share actions
- do not add timeline UI in this slice
- do not change the existing `GET /api/studies` contract

## Reviewer Owner

### Ownership

- read-only review and verification only; no product-file edits in this slice

### Review Focus

1. Confirm the slice is additive and keeps `GET /api/studies/{study_id}` backward-compatible apart from the new `outputs` field.
2. Confirm output/export entries are derived from persisted workflow/run artifacts and registry records rather than client inference.
3. Confirm the frontend actions only inspect/open already-persisted files and do not trigger new export generation behavior.
4. Confirm `Timeline` remains fully deferred.
5. Confirm no persisted `study` or `study_dossier` artifact is introduced.

## Non-Goals In This Slice

- study timeline reconstruction
- export generation or regeneration
- URL-addressable dossier pages
- study edit, rename, pin, or approval actions
- server-side study search, filter, or sort

## Done Means

- `GET /api/studies/{study_id}` returns the additive `outputs` block while preserving the existing slice 2 detail fields
- the Studies workspace renders `Outputs & Exports` from backend-derived data only
- scientists can inspect the latest run outputs and existing portable export artifacts from the dossier shell
- no new persistence or parallel study source of truth is introduced
- backend and frontend verification commands pass

## Dependencies

- reuse the study identity and detail contract shipped in slices 1 and 2
- reuse existing path-based file inspection/open flows instead of adding new transport
- no schema migration, database migration, or new artifact type is required

## Follow-On Slice

P1 slice 4 should add the remaining `Timeline` section so scientists can understand study chronology across runs, evidence, compliance, QA, and export materialization without leaving the dossier.
