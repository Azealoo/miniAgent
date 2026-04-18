# P1 Study Dossier v1 - Slice 2 - Study Detail Shell

## Goal

Deliver the first real dossier detail experience by adding an additive, read-only `GET /api/studies/{study_id}` route and replacing the current summary-only preview pane with a derived detail shell that renders `Overview`, `Runs`, `Evidence & Claims`, and `Compliance & QA` from existing artifacts.

## Why This Slice Comes Next

- P1 slice 1 already established `dataset_manifest.id` as the stable study key and shipped the list-level summary contract.
- Scientists can now find a study, but they still cannot inspect run context, evidence posture, or compliance/QA detail without leaving the Studies workspace or reading chat history.
- The backend already has canonical `dataset_manifest`, `workflow_run`, `evidence_review`, `claim_graph`, `compliance_report`, `qa_report`, and `checklist_results` artifacts, so the detail shell can stay additive and derived.

## Exact Route And Type Scope

- New route in scope:
  - `GET /api/studies/{study_id}`
- Existing dependency reused without contract change:
  - `GET /api/studies`
- Types in scope:
  - `StudyDetail`
  - `StudyOverview`
  - `StudyRunSummary`
  - `StudyEvidenceSummary`
  - `StudyComplianceSummary`
- Existing type reused without change:
  - `StudySummary`
- Types explicitly deferred:
  - `StudyTimelineItem`
  - any outputs/export-specific detail type
  - any write/edit request type

## StudyDetail Contract

```ts
type StudyDetail = {
  summary: StudySummary;
  overview: {
    reference_build: string | null;
    experiment_type: string | null;
    analysis_kind: string | null;
    condition_summary: string | null;
    condition_fields: string[];
    batch_fields: string[];
    replicate_structure: string | null;
    timepoints: string[];
    source_files: string[];
  };
  runs: Array<{
    run_id: string;
    workflow_slug: string;
    workflow_name: string;
    lifecycle_status: string;
    qc_status: string | null;
    created_at: string | null;
    step_count: number;
    warning_count: number;
    error_count: number;
    output_count: number;
  }>;
  evidence: {
    review_status: string;
    confidence: string | null;
    review_question: string | null;
    included_evidence_count: number;
    source_fact_count: number;
    limitation_count: number;
    claim_count: number;
    supported_claim_count: number;
    contradiction_count: number;
  } | null;
  compliance: {
    runtime_state: string;
    decision_source: string | null;
    risk_category: string | null;
    human_approval_required: boolean;
    approval_scope: string | null;
    approved_by: string | null;
    qa_state: string;
    qa_warning_count: number;
    qa_failed_check_count: number;
    missing_artifact_count: number;
    checklist_status: string | null;
  } | null;
};
```

## Derivation Rules

1. Resolve the study group from the same valid registry grouping shipped in slice 1: `dataset_manifest.id` is the only dossier key.
2. Reuse the existing summary derivation so `StudyDetail.summary` stays consistent with `GET /api/studies`.
3. Build `overview` from the newest valid `dataset_manifest` in the study group:
   - `reference_build`
   - `design.experiment_type`
   - `design.analysis_kind`
   - `design.condition_summary`
   - `design.condition_fields`
   - `design.batch_fields`
   - `design.replicate_structure`
   - `design.timepoints`
   - `source_files`
4. Build `runs` from valid `workflow_run` artifacts in the study group, sorted newest-first by `created_at` and then path:
   - one entry per valid loaded workflow run
   - `step_count = len(steps)`
   - `warning_count` and `error_count` derived by summing per-step warnings/errors
   - `output_count = len(outputs)`
5. Build `evidence` from the newest valid `evidence_review` plus the newest valid `claim_graph` in the study group:
   - if no `evidence_review` exists, return `null`
   - `claim_count`, `supported_claim_count`, and `contradiction_count` come from `claim_graph.summary` when available and fall back to zero otherwise
6. Build `compliance` from the newest valid `compliance_report`, `qa_report`, and `checklist_results` in the study group:
   - if none of those artifacts exist, return `null`
   - `qa_state` must reuse the same QA-state mapping already used in slice 1 summaries
   - `qa_warning_count`, `qa_failed_check_count`, and `missing_artifact_count` come from the newest `qa_report`
   - `checklist_status` comes from the newest `checklist_results.overall_status` when present
7. Return `404` when the study id does not map to a valid grouped study with a loadable canonical manifest.
8. Keep the route inspection-only and additive:
   - no persistence
   - no mutation
   - no parallel study artifact

## Backend Owner

### File Ownership

- `backend/api/studies.py`
- `backend/graph/studies_workspace.py`
- `backend/tests/test_studies_api.py`

### Must Do

1. Add `GET /api/studies/{study_id}` to the existing studies router.
2. Keep the route handler thin: inspection access check, study-id decode, service call, JSON serialization.
3. Extend the derived read model in `backend/graph/studies_workspace.py` so the detail route reuses the same grouping and canonical-manifest logic already used for study summaries.
4. Preserve `GET /api/studies` behavior and contract unchanged while adding detail helpers.
5. Expand backend regressions for:
   - detail success for a study with multiple runs and mixed artifact types
   - detail `404` for a missing study id
   - inspection access behavior on the new detail route
   - stable newest-first run ordering and evidence/compliance/QA derivation

### Must Not Do

- do not add persistence under `backend/artifacts/` or `backend/storage/`
- do not introduce a separate dossier identity model
- do not add timeline or outputs/export detail payloads in this slice

## Frontend Owner

### File Ownership

- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/components/layout/workspace-data.ts`
- `frontend/src/components/layout/WorkspacePanel.tsx`
- `frontend/src/test/fixtures.ts`
- `frontend/src/test/app-shell.contract.test.tsx`

### Must Do

1. Add `StudyDetail`, `StudyOverview`, `StudyRunSummary`, `StudyEvidenceSummary`, and `StudyComplianceSummary` types plus a validator/fetcher for `/api/studies/{study_id}`.
2. Keep the current studies list from `GET /api/studies`, but make the right-hand pane fetch dossier detail for the selected study id.
3. Replace the summary-only preview with a first dossier shell that renders:
   - `Overview`
   - `Runs`
   - `Evidence & Claims`
   - `Compliance & QA`
4. Keep list and detail states separate so the study browser stays usable while detail is loading or errors.
5. Preserve artifact-registry drill-through by continuing to drive the workspace from the existing `selectedStudyId` flow.
6. Update sidebar study sections so they describe the first dossier sections instead of the old preview-only shell.

### Must Not Do

- do not change the `GET /api/studies` contract
- do not add URL routing, deep links, or new global store state
- do not add edit, approve, rename, pin, or export actions
- do not land `Outputs & Exports` or `Timeline` UI in this slice

## Reviewer Owner

### Ownership

- read-only review and verification only; no product-file edits in this slice

### Review Focus

1. Confirm backend and frontend write sets remain disjoint and reviewer stays read-only.
2. Confirm the new detail shell is fully derived from backend contracts and does not infer state from chat/session history.
3. Confirm `GET /api/studies` stays backward-compatible while `GET /api/studies/{study_id}` is additive only.
4. Confirm no persisted `study` or `study_dossier` artifact is introduced.
5. Confirm only the first dossier sections land:
   - `Overview`
   - `Runs`
   - `Evidence & Claims`
   - `Compliance & QA`
   and `Outputs & Exports` plus `Timeline` remain deferred.

## Non-Goals In This Slice

- outputs/export detail cards
- study timeline reconstruction
- URL-addressable dossier pages
- study editing or approval actions
- server-side study search, sort, or filtering

## Done Means

- `GET /api/studies/{study_id}` returns a derived detail payload for a valid study id and `404`s for missing studies
- the Studies workspace keeps the shipped summary browser and upgrades the right pane into a detail shell backed by the new route
- overview, runs, evidence/claims, and compliance/QA sections render from artifact-derived fields only
- no new persistence or parallel study source of truth is introduced
- backend and frontend verification commands pass

## Dependencies

- reuse the study identity and grouping shipped in slice 1; do not redefine it
- backend detail route should land before the frontend detail-shell wiring
- no schema migration, database migration, or new artifact type is required

## Follow-On Slice

P1 slice 3 should add `Outputs & Exports` plus `Timeline` so scientists can follow publication bundles and temporal study activity without overloading this first detail shell.
