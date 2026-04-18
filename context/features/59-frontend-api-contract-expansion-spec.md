# Frontend API Contract Expansion Spec

## Overview

Expand the frontend API layer so the UI can fully consume the production-capable backend, not just sessions, chat, files, and basic token counts. This phase should define a clean frontend client surface for artifact registry lookup, raw file preview, audit inspection, observability, connectors, and skills registry management.

## Requirements

- Extend the frontend API client to support the backend routes that are not yet surfaced in the UI.
- Add typed client functions for:
  - artifact registry lookup
  - artifact registry rebuild
  - raw file reads
  - audit event queries
  - observability overview
  - observability metrics
  - observability traces
  - dashboard definitions
  - connector registry list/detail/update/validate/action
  - skills registry list/update
- Add or refine TypeScript types so these routes do not rely on `object` or unstructured data.
- Keep the API layer consistent with the current `req()` and `streamChat()` client style unless there is a clear reason to split concerns.
- Make inspection routes clearly distinguishable from execution/admin routes in the frontend code so permission handling is not hidden.
- Ensure the API layer supports filtered artifact and audit queries using the real backend query parameters.
- Prepare the API client to pass bearer tokens or auth state later without rewriting every caller.
- Do not break the current session/chat flow while expanding the client surface.

## References

- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/artifact_registry.py
- @backend/api/files.py
- @backend/api/audit.py
- @backend/api/observability.py
- @backend/api/connectors.py
- @backend/api/skills_registry.py
- @backend/access_control.py

