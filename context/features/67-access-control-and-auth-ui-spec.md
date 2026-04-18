# Access Control And Auth UI Spec

## Overview

Add the frontend access-control layer required to safely use inspection, execution, and admin routes in non-local or production settings. The backend already distinguishes loopback access from bearer-token protected access. This phase should make those access requirements explicit in the UI and API client behavior.

## Requirements

- Add a frontend strategy for attaching bearer tokens to protected requests when required.
- Distinguish the UI capabilities that require:
  - inspection access
  - execution access
  - admin access
- Show clear, non-confusing unauthorized and forbidden states when the backend denies access.
- Prevent the UI from advertising admin-only mutations as normal user actions when the current access scope does not permit them.
- Add shared request/interceptor behavior so auth headers do not need to be manually threaded through every API call site.
- Ensure the frontend handles the current backend local-development behavior gracefully:
  - loopback access without auth where allowed
  - bearer-token requirement when loopback bypass is not available
- Provide a visible but restrained connection/access state somewhere in the shell or ops surfaces.
- Keep the auth/access experience simple enough for local development while production-safe enough for remote inspection and admin use.

## References

- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @backend/access_control.py
- @backend/api/config_api.py
- @context/features/38-navbar-status-spec.md
- @context/features/64-observability-ops-workspace-spec.md
- @context/features/66-connectors-registry-ui-spec.md

