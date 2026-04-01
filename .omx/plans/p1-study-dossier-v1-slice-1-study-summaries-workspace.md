# P1 Study Dossier v1 - Slice 1 - Study Summaries Workspace

## Goal

Deliver the first read-only Study Dossier surface by deriving study summaries from existing artifact registry records and source artifacts, then exposing them in a minimal `Studies` workspace so a scientist can scan study status without reading chat history.

## Why This Slice Comes First

- P1 needs a stable summary contract before any per-study detail route, timeline, or drill-through behavior.
- The backend already has canonical `dataset_manifest`, `workflow_run`, `qa_report`, `compliance_report`, `evidence_review`, `claim_graph`, and export artifacts, so the first slice can stay additive and derived.
- The frontend already has a workspace shell, nav model, and contract-test harness that can host a summaries-first Studies view without inventing new persistence or state infrastructure.

## Exact Route And Type Scope

- Route in scope:
  - `GET /api/studies`
- Route explicitly deferred:
  - `GET /api/studies/{study_id}`
- Types in scope:
  - `StudySummary`
  - `StudyArtifactCounts`
  - `StudiesWorkspaceResponse`
- Types explicitly deferred:
  - `StudyDetail`
  - `StudyRunSummary`
  - `StudyEvidenceSummary`
  - `StudyComplianceSummary`
  - `StudyTimelineItem`

## StudySummary Contract

```ts
type StudySummary = {
  study_id: string;
  title: string;
  assay_type: string;
  organism: string;
  privacy_classification: string;
  latest_activity_at: string | null;
  run_count: number;
  active_run_state: "not_started" | "active" | "blocked" | "failed" | "completed";
  evidence_state: "not_started" | "supported" | "mixed" | "insufficient_evidence";
  compliance_state:
    | "not_started"
    | "allowed"
    | "warning_issued"
    | "approval_required"
    | "approved_override"
    | "blocked";
  qa_state: "not_started" | "passed" | "warning" | "failed" | "blocked";
  export_available: boolean;
  artifact_counts: {
    dataset_manifests: number;
    workflow_runs: number;
    evidence_reviews: number;
    claim_graphs: number;
    compliance_reports: number;
    qa_reports: number;
    checklist_results: number;
    exports: number;
  };
};
```

## Derivation Rules

1. Build studies only from valid artifact registry records with a non-empty `dataset_id`.
2. Group by `dataset_manifest.id`.
3. Resolve one canonical manifest per group from the newest valid `dataset_manifest` record and load it for:
   - `title = design.study_name`
   - `assay_type`
   - `organism`
   - `privacy_classification`
4. Skip any group whose canonical `dataset_manifest` cannot be loaded or validated.
5. Set `latest_activity_at` to the newest available artifact `created_at` in the study, falling back to `indexed_at` only when `created_at` is absent.
6. Set `run_count` to the distinct count of non-empty `run_id` values across valid study records.
7. Derive `active_run_state` from the newest `workflow_run.lifecycle_status` in the study:
   - `created`, `preflight_checked`, `running`, `waiting` -> `active`
   - `blocked` -> `blocked`
   - `failed` -> `failed`
   - `completed` -> `completed`
   - no workflow run -> `not_started`
8. Derive `evidence_state` from the newest `evidence_review.review_status`; if no `evidence_review` exists, return `not_started`.
9. Derive `compliance_state` from the newest `compliance_report.runtime_state`; if no `compliance_report` exists, return `not_started`.
10. Derive `qa_state` from the newest `qa_report.overall_status`; if no `qa_report` exists, fall back to the newest `checklist_results.overall_status`, mapping `not_applicable` to `not_started`.
11. Set `export_available` to `true` when any valid `provenance`, `biocompute`, `eln_export`, or `eln_export_archive` record exists in the study.
12. Keep `artifact_counts` purely derived from valid registry records; do not synthesize counts in the frontend.

## Backend Owner

### File Ownership

- `backend/api/studies.py`
- `backend/graph/studies_workspace.py`
- `backend/app.py`
- `backend/tests/test_studies_api.py`

### Must Do

1. Add an inspection-only `GET /api/studies` route.
2. Keep the route handler thin: access check, service call, and JSON serialization only.
3. Implement the read model in `backend/graph/studies_workspace.py` on top of `ArtifactRegistry(...).ensure_snapshot()` plus source artifact loads.
4. Reuse existing canonical schema loading for `dataset_manifest`, `workflow_run`, `qa_report`, `compliance_report`, and `evidence_review` instead of inventing a parallel parser.
5. Ignore invalid registry records rather than surfacing them as partial study summaries.
6. Add regression coverage for:
   - grouping by `dataset_manifest.id`
   - latest-state derivation across multiple artifacts/runs
   - export availability and artifact-count rollups
   - inspection access enforcement for `GET /api/studies`

### Must Not Do

- do not create any persisted `study`, `study_dossier`, or `studies` artifact under `artifacts/` or `storage/`
- do not add `GET /api/studies/{study_id}` in this slice
- do not move artifact registry logic into the route layer

## Frontend Owner

### File Ownership

- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/components/layout/workspace-data.ts`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/src/components/layout/WorkspacePanel.tsx`
- `frontend/src/test/fixtures.ts`
- `frontend/src/test/app-shell.contract.test.tsx`

### Must Do

1. Add `studies` to `WorkspaceMode` and expose it in the primary nav.
2. Add the `StudySummary`, `StudyArtifactCounts`, and `StudiesWorkspaceResponse` types plus an API validator/fetcher for `/api/studies`.
3. Implement a minimal `StudiesWorkspace` in `WorkspacePanel.tsx` with:
   - loading
   - error
   - empty
   - ready states
   - local search
   - local sort
   - selected-study preview pane
4. Render the backend summary fields directly rather than inferring study state from chat/session data in the client.
5. Keep search and sort client-side only inside the workspace component.

### Must Not Do

- do not add global store state beyond the existing `workspaceMode`
- do not add dossier detail tabs or a study timeline
- do not add any frontend write flow for studies

## Reviewer Owner

### Ownership

- read-only review and verification only; no product-file edits in this slice

### Review Focus

1. Confirm the write sets stay disjoint:
   - backend owner touches backend files only
   - frontend owner touches frontend files only
   - reviewer stays read-only
2. Confirm the slice remains additive:
   - only `GET /api/studies` lands
   - `/api/studies/{study_id}` remains deferred
3. Confirm there is no new persisted study artifact or hidden second source of truth.
4. Confirm the UI states shown in the Studies workspace come from the backend contract, not client inference from chat history.
5. Confirm search and sort remain client-side only.

## Non-Goals In This Slice

- dossier detail route and multi-section detail payloads
- drill-through from files/artifacts/session surfaces into a study
- study editing, pinning, or rename flows
- timeline construction
- server-side study search, filter, or sort

## Done Means

- `GET /api/studies` returns derived study summaries keyed by `dataset_manifest.id`
- the `Studies` workspace loads and renders those summaries with clear empty/error/loading states
- search and sort are local-only and do not mutate backend contracts
- no persisted `study` artifact or parallel dossier storage is introduced
- backend and frontend verification commands pass

## Dependencies

- backend contract should land before the frontend workspace wiring
- no database, migration, or new artifact schema is required

## Follow-On Slice

P1 slice 2 should add `GET /api/studies/{study_id}` plus the first dossier detail sections using the same derived study grouping introduced here, rather than redefining study identity or persistence.
