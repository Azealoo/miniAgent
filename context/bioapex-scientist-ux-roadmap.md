# BioAPEX Scientist UX Roadmap

Date: 2026-04-01

## Summary

This roadmap focuses on the highest-leverage product improvements for BioAPEX as a scientist-facing lab system:

- fix the immediate trust issue in offline token counting
- make study state legible through a first-class Study Dossier
- turn approval-required compliance from a model into a usable workflow
- mature execution surfaces for real bench and analysis work

The sequence is:

1. `P0 Stabilize trust`
2. `P1 Study Dossier v1`
3. `P2 Approval and Resume UX`
4. `P3 Bench operator and analysis maturity`

## Mission Fit

BioAPEX should feel less like a hidden agent and more like a transparent lab workspace:

- scientists should understand study status without reading chat history
- approvals should be visible, auditable, and resumable
- workflows should produce durable artifacts instead of ephemeral answers
- evidence, compliance, outputs, and execution state should converge into one inspectable surface

## P0 Stabilize Trust

### Problem

`backend/api/tokens.py` initializes `tiktoken` at import time. In offline or restricted environments this triggers a fetch path and causes backend test failures.

### Implementation

- make tokenization lazy instead of import-time
- ensure importing the API layer never requires network access
- add a deterministic local fallback tokenizer for cache-miss or offline scenarios
- keep token endpoints functional in both exact and fallback modes
- add additive response fields:
  - `tokenizer_backend`
  - `tokenizer_accuracy`
- update the Usage UI so approximate counts are labeled honestly
- add `.next-e2e-build` to `.gitignore`
- clean up human-facing naming drift from `miniOpenClaw`/`Claw` toward `BioAPEX` while preserving machine-facing compatibility

### Acceptance

- backend imports succeed offline
- token endpoints return counts even without model tokenizer availability
- the UI distinguishes exact vs approximate counts
- backend test failures caused by token counting are resolved

## P1 Study Dossier v1

### Goal

Create a single scientist-facing workspace for each study so the current system feels coherent instead of fragmented across sessions, artifacts, and files.

### Product Shape

The Study Dossier is a derived inspection surface, not a new canonical artifact.

- group dossiers by `dataset_manifest.id`
- display title from `dataset_manifest.design.study_name`
- derive state from artifact registry plus source artifact reads
- avoid introducing a second source of truth

### Routes

- `GET /api/studies`
- `GET /api/studies/{study_id}`

### Dossier Summary

Each study summary should include:

- study title
- dataset id
- assay type
- organism
- privacy class
- latest activity timestamp
- run counts
- active run state
- evidence state
- compliance state
- QA/checklist state
- export availability
- key artifact counts

### Dossier Detail Sections

- `Overview`
- `Runs`
- `Evidence & Claims`
- `Compliance & QA`
- `Outputs & Exports`
- `Timeline`

### UX Leverage

This is the biggest user-experience multiplier because it turns the product into something a biologist can scan quickly:

- one place to understand where a study stands
- one place to find outputs and evidence
- one place to see whether anything is blocked or risky
- one place to resume work across computational and experimental contexts

### v1 Constraints

- client-side search and sort only
- no study editing flow yet
- no new persistent study artifact
- drill through from artifacts, files, and relevant session/workflow surfaces into the dossier when dataset context is available

## P2 Approval and Resume UX

### Goal

Turn compliance from passive reporting into an operational scientist/admin workflow.

### Current Gap

Approval-required behavior exists conceptually, but the product still lacks a clean action path for real users to review, approve, and continue blocked work.

### Implementation

- extend `POST /api/chat` with optional `approval_override`
- shape:
  - `approved_by`
  - `rationale`
  - `approval_scope`
- keep `approval_scope` message-only in v1
- add `request_id` to the compliance report payload and frontend types
- implement an admin-only `Approve and Resume` dialog
- capture approver identity and rationale
- replay the original blocked request with `approval_override`
- use the replay itself to materialize the durable `approved_override` artifact and audit trail

### UX States

These states should be visually distinct and actionable:

- `approval required`
- `approved override`
- `blocked`

### Why This Matters

This is one of the most important trust features for a real lab environment:

- scientists know when they are blocked
- admins know what they are authorizing
- the system preserves who approved what and why
- execution can continue without informal side channels

## P3 Bench Operator and Analysis Maturity

### Bench Operator v1

Promote protocol execution into a first-class lab workspace.

Add:

- active protocol run cards
- step timers
- sample identifiers
- reagent and equipment context
- deviation logging
- attachment support
- progress and resume state tied to `protocol_run`

### Analysis Maturity

Keep the current workflow contracts, but make execution truth more honest and more useful:

- label deterministic or demo stages clearly
- prioritize one production-shaped end-to-end analysis path
- upgrade scaffolded analysis outputs incrementally rather than pretending they are fully real

### Connector Reconciliation

After the dossier exists, integration state should be visible inside the study itself:

- ELN sync state
- LIMS sync state
- instrument import/export status
- dry-run mapping review
- retry and conflict resolution

## API and Type Additions

### Additive Token Response Fields

- `tokenizer_backend: "tiktoken_cl100k_base" | "deterministic_fallback"`
- `tokenizer_accuracy: "model_aligned" | "approximate"`

### Additive Chat Request Field

- `approval_override?: { approved_by: string; rationale?: string; approval_scope: "message" }`

### Additive Compliance Field

- `request_id: string`

### New Frontend Types

- `StudySummary`
- `StudyDetail`
- `StudyRunSummary`
- `StudyEvidenceSummary`
- `StudyComplianceSummary`
- `StudyTimelineItem`

## Verification Plan

### Backend

- importing `api.tokens` offline does not fail or attempt network-dependent initialization
- token endpoints return stable counts in exact and fallback modes
- study aggregation groups by `dataset_manifest.id`
- dossier detail correctly links runs, evidence, compliance, QA, outputs, and claim graph context
- chat replay with `approval_override` creates durable `approved_override` audit artifacts

### Frontend

- Usage tab labels exact vs approximate token counts
- Studies workspace loads summaries and opens dossier detail
- blocked or approval-required requests expose `Approve and Resume`
- dossier evidence and compliance surfaces reflect the same source artifacts used elsewhere in the app

### Acceptance Scenarios

- a scientist can open a study and understand status without reading prior chat
- a blocked request can be approved and resumed with a durable audit trail
- dossier views improve discoverability without becoming a parallel truth source

## Recommended Order of Work

1. Fix the offline token-counting defect and add honest fallback labeling.
2. Implement Study Dossier read models and a minimal dossier workspace.
3. Add approval replay with `Approve and Resume`.
4. Improve workflow honesty around stubbed analysis stages.
5. Build Bench Operator v1 on top of protocol execution artifacts.
6. Surface connector reconciliation inside the dossier once the core study view is stable.

## Assumptions

- `dataset_manifest.id` is the stable dossier key
- `dataset_manifest.design.study_name` is presentation-friendly but not identity-defining
- dossier v1 is derived, not persisted
- approval overrides are message-scoped only in v1
- all new routes and types are additive
- no database migration is required for this roadmap

## Near-Term Outcome

If we execute this roadmap in order, BioAPEX will move from a collection of strong backend ideas into a more coherent scientist product:

- more trustworthy
- easier to scan
- easier to resume
- safer in regulated or approval-gated work
- more differentiated as a lab operating surface rather than a generic assistant
