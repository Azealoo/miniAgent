# Audit Events View Spec

## Overview

Add an audit events view so BioAPEX’s traceability promise is visible in the frontend. This phase should allow operators or reviewers to inspect what happened across runs, tools, connectors, and workflow events without relying on raw files or backend-only inspection.

## Requirements

- Add an audit events surface in the frontend, likely under the `Ops` workspace.
- Support querying audit events with the same filter dimensions exposed by the backend, including:
  - event type
  - session ID
  - run ID
  - step ID
  - job ID
  - workflow ID
  - tool name
  - connector name
  - outcome
- Present events in a compact, chronological, review-friendly list or table.
- Include retention-policy information somewhere in the audit view so operators understand audit limits.
- Make it easy to correlate audit rows with:
  - workflow runs
  - connectors
  - tool executions
  - blocked actions
- Ensure the view handles large event volumes via pagination, limits, or incremental loading.
- Keep the audit surface practical and inspectable, not visually noisy.

## References

- @frontend/src/lib/api.ts
- @backend/api/audit.py
- @backend/access_control.py
- @context/features/64-observability-ops-workspace-spec.md

