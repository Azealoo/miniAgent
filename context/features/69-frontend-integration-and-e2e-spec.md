# Frontend Integration And E2E Spec

## Overview

Add the verification layer needed to trust the BioAPEX frontend in a production-like setting. This phase should focus on integration and end-to-end coverage for the highest-value flows so the UI stays aligned with the backend contracts as the system grows.

## Requirements

- Add integration and E2E coverage for the most important frontend/backend flows.
- Cover at least:
  - session creation and switching
  - streaming chat assembly
  - workflow event rendering
  - retrieval card rendering
  - generated-file display
  - sources/memory/skills/usage tab loading
  - artifact registry query flow
  - unauthorized inspection/admin route handling
  - compliance warning/block rendering
- Prefer tests that validate real frontend state transitions against the actual event contracts and API shapes.
- Ensure the test plan covers both happy path and degraded path behavior.
- Define a minimal release checklist for the frontend that includes:
  - build success
  - key interaction verification
  - protected-route failure handling
  - visual smoke checks for major workspaces
- Keep the testing approach aligned with the actual stack used in this repo rather than assuming a separate design-system-only environment.

## References

- @frontend/package.json
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @backend/api/chat.py
- @backend/api/artifact_registry.py
- @backend/api/audit.py
- @backend/api/observability.py
- @backend/api/connectors.py
- @backend/access_control.py
