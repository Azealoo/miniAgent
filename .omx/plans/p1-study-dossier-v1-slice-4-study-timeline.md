# P1 Study Dossier v1 - Slice 4 - Study Timeline

## Goal

Extend the additive, read-only `GET /api/studies/{study_id}` contract so the Studies workspace can render the final dossier section, `Timeline`, as a flat major-activity feed derived from already-persisted study artifacts without introducing step-event playback, session chronology, connector sync history, or any new study persistence.

## Why This Slice Comes Next

- Slice 3 is implemented, verified, and approved, so `Timeline` is the only remaining unfinished `P1 Study Dossier v1` detail section from the roadmap.
- The backend already groups study artifacts by `dataset_manifest.id` and now exposes the other dossier sections from the same derived detail contract, so chronology can stay additive instead of opening a parallel model.
- Valid study-scoped registry records already carry `artifact_type`, `path`, `run_id`, `workflow`, and activity timestamps across runs, evidence, compliance, QA, and export artifacts.
- A flat major-artifact feed answers the remaining scientist question, "what happened when?", while broader chronology systems remain explicitly deferred.

## Exact Route And Type Scope

- Existing route extended in scope:
  - `GET /api/studies/{study_id}`
- Existing dependencies reused without contract change:
  - `GET /api/studies`
  - `GET /api/files/raw?path=...`
- Types in scope:
  - `StudyTimelineItem`
- Existing type extended:
  - `StudyDetail`
- Existing types reused without change:
  - `StudySummary`
  - `StudyOverview`
  - `StudyRunSummary`
  - `StudyEvidenceSummary`
  - `StudyComplianceSummary`
  - `StudyOutputsSummary`
  - `StudyOutputArtifact`
- Types explicitly deferred:
  - any timeline filter, grouping, or pagination request type
  - any workflow-step or SSE event replay type
  - any connector-sync or chat/session chronology type

## Additive Contract

```ts
type StudyTimelineItem = {
  artifact_type: string;
  label: string;
  status: string | null;
  path: string;
  run_id: string;
  workflow_slug: string;
  workflow_name: string;
  created_at: string | null;
};

type StudyDetail = ExistingStudyDetail & {
  timeline: StudyTimelineItem[];
};
```

## Derivation Rules

1. Preserve every slice 3 `StudyDetail` field exactly and add only `timeline`.
2. Reuse the same valid `dataset_manifest.id` study grouping already shipped in slices 1 through 3.
3. Build `timeline` from valid study-scoped records whose `artifact_type` is one of:
   - `workflow_run`
   - `evidence_review`
   - `claim_graph`
   - `compliance_report`
   - `qa_report`
   - `checklist_results`
   - `provenance`
   - `biocompute`
   - `eln_export`
   - `eln_export_archive`
4. Sort timeline items newest-first by study record activity timestamp (`created_at` when present, otherwise `indexed_at`) and then by path for stable ties.
5. Keep one timeline item per valid artifact path; do not replay every generated output or duplicate registry entry.
6. Resolve `workflow_slug` and `workflow_name` from the matching loadable workflow run when possible, falling back to the registry workflow identifier when needed.
7. Populate `label` and `status` with this exact mapping:
   - `workflow_run` -> label = originating workflow name, status = `lifecycle_status`
   - `evidence_review` -> label = `Evidence Review`, status = `review_status`
   - `claim_graph` -> label = `Claim Graph`, status = `null`
   - `compliance_report` -> label = `Compliance Report`, status = `runtime_state`
   - `qa_report` -> label = `QA Report`, status = `overall_status`
   - `checklist_results` -> label = `Checklist Results`, status = `overall_status`
   - `provenance` -> label = `Provenance Export`, status = `null`
   - `biocompute` -> label = `BioCompute Export`, status = `null`
   - `eln_export` -> label = `ELN Export`, status = `null`
   - `eln_export_archive` -> label = `ELN Export Archive`, status = `null`
8. When a source document is unavailable but the valid registry record exists, keep the event in the timeline with the mapped label above and `status = null` rather than inventing a replacement artifact source.
9. Return `404` when the requested `study_id` does not resolve to a valid grouped study with a loadable manifest.
10. Keep this slice inspection-only and derived:
    - no new persisted `study` or `study_dossier` artifact
    - no timeline write flow, annotation flow, or approval flow
    - no workflow-step playback or chat/session event reconstruction

## Backend Owner

### File Ownership

- `backend/graph/studies_workspace.py`
- `backend/tests/test_studies_api.py`

### Must Do

1. Extend the existing study-detail read model with the additive `timeline` array only.
2. Reuse the current grouped-study helpers and workflow identity resolution already present in the read model instead of inventing a parallel chronology service.
3. Preserve `GET /api/studies` unchanged and preserve every slice 3 field on `GET /api/studies/{study_id}`.
4. Add regressions for:
   - mixed-artifact timeline derivation ordered newest-first
   - additive preservation of the existing detail sections alongside the new timeline
   - truthful `status` mapping and workflow identity fallback
   - empty timeline arrays when a valid study exists but has no qualifying post-manifest activity artifacts

### Must Not Do

- do not add a new study route
- do not materialize a persisted timeline artifact
- do not include generic generated outputs, step-level workflow events, or chat/session events in this slice
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

1. Add `StudyTimelineItem` and extend the `StudyDetail` validator to require the additive `timeline` field.
2. Keep the existing studies list and previously shipped dossier sections unchanged.
3. Add a `Timeline` dossier section that renders a flat newest-first major-activity feed.
4. Render each timeline card directly from backend-derived fields:
   - `label`
   - optional `status`
   - `created_at`
   - `workflow_name`
   - `run_id`
   - `path`
5. Reuse existing path-based inspection and raw-file opening actions instead of adding new route state or download orchestration.
6. Provide a truthful empty state when the selected study has no qualifying timeline items yet.
7. Update the Studies workspace section copy so it reflects the now-complete dossier surface.

### Must Not Do

- do not add URL routing or new global store state
- do not add timeline filters, grouping UI, pagination, or export/share actions
- do not change the existing `GET /api/studies` contract
- do not refactor the already-shipped detail sections beyond what is required to insert `Timeline`

## Reviewer Owner

### Ownership

- read-only review and verification only; no product-file edits in this slice

### Review Focus

1. Confirm the slice is additive and keeps `GET /api/studies/{study_id}` backward-compatible apart from the new `timeline` field.
2. Confirm timeline items come from persisted study artifacts and registry activity, not from chat history, session text, or client inference.
3. Confirm backend and frontend write sets remain disjoint and reviewer stays read-only.
4. Confirm `Timeline` stays a flat major-artifact feed rather than quietly expanding into step-event playback, connector history, or a persisted study record.
5. Confirm no new persistence or parallel study truth source is introduced.

## Non-Goals In This Slice

- workflow-step or SSE event playback
- chat/session chronology inside the dossier
- connector sync/retry/conflict history
- timeline filtering, grouping, pagination, or deep links
- study editing, annotations, approvals, or exports beyond existing file-open flows

## Done Means

- `GET /api/studies/{study_id}` returns the additive `timeline` field while preserving the existing slice 3 detail contract
- the Studies workspace keeps the shipped summary browser and existing dossier sections while adding `Timeline`
- scientists can scan major study chronology across runs, evidence, compliance, QA, and exports from backend-derived data only
- no new persistence or parallel study source of truth is introduced
- backend and frontend verification commands pass

## Dependencies

- reuse the study identity and detail contract shipped in slices 1 through 3
- reuse existing path-based inspection/open flows instead of adding transport or routing
- no schema migration, database migration, or new artifact type is required

## Follow-On

Completing this slice should finish `P1 Study Dossier v1`; any later chronology work belongs to a new phase because it would expand beyond the minimal derived dossier contract.
