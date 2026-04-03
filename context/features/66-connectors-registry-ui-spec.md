# Connectors Registry UI Spec

## Overview

Build a connectors registry UI so external integration points are manageable from the frontend. The backend already supports connector listing, inspection, configuration, validation, and runtime actions. This phase should expose those capabilities in a safe, production-aware admin surface.

## Requirements

- Add a connectors registry section under the `Ops` workspace or another clearly administrative surface.
- Show a list of connectors with:
  - connector name
  - enabled state
  - basic status or health indication
- Support a connector detail panel that can display:
  - current config summary
  - validation state
  - available runtime actions
- Add UI flows for:
  - viewing connector details
  - enabling/disabling connectors
  - editing config payloads
  - validating connector configuration
  - invoking supported runtime actions
- Make all mutation and runtime-action affordances clearly admin-only.
- Surface production-hardening policy blocks and permission failures clearly when the backend denies an action.
- Keep this UI practical and controlled; it should feel like an operator surface, not a consumer settings page.
- Preserve auditability by making runtime and mutation actions visibly tied to result states.

## References

- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/connectors.py
- @backend/access_control.py
- @context/features/64-observability-ops-workspace-spec.md

