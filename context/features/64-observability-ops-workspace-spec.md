# Observability Ops Workspace Spec

## Overview

Build an `Ops` or equivalent production-inspection workspace that exposes BioAPEX observability data. The backend now provides overview, metrics, traces, and dashboard definitions; this phase should turn those into a usable operator-facing frontend rather than leaving them as hidden APIs.

## Requirements

- Add an `Ops` workspace or equivalent admin/inspection surface in the frontend.
- Include an observability overview section that can summarize recent system health and workflow/runtime behavior.
- Support dedicated views for:
  - overview
  - metrics
  - traces
  - dashboard definitions if useful
- Keep the UI operational and filter-driven, not chart-heavy by default.
- Make it possible to filter by real backend dimensions such as:
  - request ID
  - session ID
  - run ID
  - step ID
  - workflow ID
  - trace ID
- Present metrics and traces in a way that helps with debugging workflow execution and tool behavior.
- Keep this workspace clearly distinct from user-facing scientific work; it should feel like an inspection and operations surface.
- Respect inspection-only access semantics and handle unauthorized responses gracefully.

## References

- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/observability.py
- @backend/access_control.py
- @context/features/51-workspace-mode-navigation-spec.md

