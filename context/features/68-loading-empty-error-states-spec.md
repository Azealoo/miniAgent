# Loading Empty And Error States Spec

## Overview

Harden the frontend experience by systematically defining loading, empty, and error states across all major BioAPEX surfaces. A production-grade UI is not only about happy-path features; it must remain understandable when the backend is unavailable, filtered results are empty, or protected routes fail.

## Requirements

- Define and implement explicit loading, empty, and error states for all major surfaces, including:
  - sessions
  - chat/session workspace
  - flows workspace
  - docs workspace
  - files workspace
  - sources tab
  - memory tab
  - skills tab
  - usage tab
  - artifact registry
  - ops / observability
  - connectors
- Ensure error states preserve context and next steps where possible instead of replacing the entire screen with a generic failure.
- Differentiate between:
  - backend unavailable
  - unauthorized
  - forbidden
  - empty results
  - filtered empty results
  - malformed or unsupported payloads
- Keep fallback states visually aligned with the calm BioAPEX design language.
- Avoid disruptive modal-heavy patterns unless an action is truly destructive or blocking.
- Ensure loading states communicate whether the user is waiting on:
  - a background fetch
  - a streaming operation
  - a mutation
  - an inspection query

## References

- @frontend/src/app/page.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @frontend/src/components/layout/Sidebar.tsx
- @frontend/src/components/chat/ChatPanel.tsx
- @frontend/src/components/editor/InspectorPanel.tsx
- @backend/access_control.py

