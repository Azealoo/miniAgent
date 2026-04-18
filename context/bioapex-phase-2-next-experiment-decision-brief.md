# BioAPEX Phase 2: Next-Experiment Decision Brief

## Summary

After the current roadmap lands, the next step for BioAPEX should be to move from a system that explains the study to a system that helps the lab decide what to do next.

The right post-roadmap north star is a `Next-Experiment Decision Brief` capability:
- advisory, not executable
- grounded in dossier state, evidence, claim graph, workflow outputs, and compliance context
- optimized for a scientist deciding the next assay, control, validation step, or follow-up analysis

This keeps the product trustworthy while making the agent meaningfully more valuable at the scientific decision point.

## Key Changes

### Product behavior

BioAPEX should add a first-class `Next Step` surface inside the Study Dossier.
From that surface, a scientist can generate a decision brief for a study.

Each brief should produce:
- one recommended next experiment or validation move
- up to two alternatives
- the question the brief is trying to answer
- the evidence and workflow results that support the recommendation
- the key uncertainty or contradiction being resolved
- expected learning if the experiment succeeds or fails
- required prerequisites and missing metadata
- compliance or approval implications
- explicit confidence and rationale

The system should not create runnable workflow or protocol payloads in this phase.
This phase is recommendation and decision support only.

### Backend and artifact model

Add a new durable artifact type: `decision_brief`.

Add a second durable artifact type: `decision_log`.

`decision_brief` is system-generated and should include:
- `id`
- `study_id`
- `generated_at`
- `study_context`
- `decision_question`
- `primary_recommendation`
- `alternative_recommendations`
- `supporting_artifacts`
- `contradictions_or_gaps`
- `expected_learning`
- `prerequisites`
- `compliance_notes`
- `confidence`
- `status`

`decision_log` is human-authored and should include:
- `id`
- `study_id`
- `decision_brief_id`
- `disposition`
- `decided_by`
- `rationale`
- `linked_followup_artifacts`
- `created_at`

Use `disposition` values:
- `accepted`
- `deferred`
- `rejected`

A brief should remain immutable after generation.
Human response should always be captured in a separate `decision_log` artifact.

### Decision pipeline

The decision brief generator should assemble a study packet from:
- Study Dossier summary and detail
- latest relevant workflow runs
- evidence cards and evidence reviews
- claim graph
- QA and checklist artifacts
- compliance state
- exports only when they add useful context

Generation logic should be conservative:
- if the system lacks enough evidence to support a recommendation, it should emit `insufficient_context` instead of inventing a confident next step
- if contradictions exist, the brief should prefer contradiction-resolving experiments or validation controls
- if QC or metadata problems remain unresolved, the brief should recommend study-readiness fixes before proposing new biology work
- if compliance risk is implicated, the brief should mark that clearly but not initiate approval or execution

### Frontend UX

Add a `Next Step` section to the Study Dossier with:
- `Generate Brief`
- list of prior briefs for the study
- current brief detail view
- `Accept`, `Defer`, and `Reject` actions for authorized users
- links to all supporting evidence, workflow, and compliance artifacts
- timeline integration showing when a brief was generated and how it was decided

The detail view should always show:
- recommendation
- why now
- what uncertainty it resolves
- what evidence it uses
- what would be learned
- what needs to be true before running it

Accepted briefs should not auto-create workflows in this phase.
They should only create a `decision_log` and optionally deep-link to existing workflow/protocol creation surfaces.

## Public APIs and Interfaces

Additive backend routes:
- `GET /api/studies/{study_id}/decision-briefs`
- `POST /api/studies/{study_id}/decision-briefs`
- `GET /api/decision-briefs/{brief_id}`
- `POST /api/decision-briefs/{brief_id}/decision-log`

Additive frontend types:
- `DecisionBrief`
- `DecisionRecommendation`
- `DecisionLog`
- `DecisionDisposition`

Additive Study Dossier summary/detail fields:
- `latest_decision_brief_at`
- `latest_decision_disposition`
- `open_decision_brief_count`

Default generation request input should be minimal:
- `decision_question?: string`
- `focus_mode?: "biology" | "validation" | "qc" | "analysis"`
- default `focus_mode` is `biology`

## Test Plan

### Backend scenarios
- generate a decision brief for a study with workflow evidence and claim graph support
- generate a contradiction-driven brief when the claim graph contains conflicting claims
- return `insufficient_context` when the study lacks enough evidence or result structure
- prefer readiness fixes when QC or required metadata gaps are unresolved
- create immutable `decision_brief` artifacts and separate `decision_log` artifacts
- reject invalid `decision_log` dispositions or missing `decided_by`

### Frontend scenarios
- dossier shows `Next Step` section only for studies with valid study ids
- scientist can generate and inspect a brief from the dossier
- supporting artifacts are clickable from the brief
- authorized user can accept, defer, or reject a brief
- accepted/deferred/rejected decisions appear in dossier timeline and brief history
- no UI path implies the brief is executable or already approved to run

### Acceptance criteria
- a scientist can open a study and get a grounded recommendation for the next experiment
- every recommendation shows explicit supporting evidence and uncertainty
- every human decision on a recommendation is durable and auditable
- the system fails conservatively when evidence is weak instead of inventing a next move

## Assumptions and Defaults

- This phase starts after Study Dossier and approval UX from the current roadmap are in place.
- Recommendations are advisory only; no workflow or protocol auto-generation is included.
- The canonical entry point is the Study Dossier, not chat.
- `decision_brief` is generated from existing study artifacts and does not become a new source of study truth.
- `decision_log` is required to close the loop between recommendation and human choice.
- The success metric for this phase is not autonomy; it is whether scientists trust the agent enough to use it when deciding the next experiment.
