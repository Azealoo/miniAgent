# Sidebar Navigation Spec

## Overview

Implement the compact left sidebar shown in the revised dashboard. This phase should turn the sidebar into a focused navigation rail that surfaces sessions, workflow entry points, and recent context without stealing visual weight from the center workspace.

## Requirements

- Make the sidebar noticeably narrower and more efficient than the earlier session-heavy layout.
- Include a prominent `New` action near the top of the rail.
- Add a search field for quickly filtering sessions and saved work.
- Implement a compact primary navigation area with entries for:
  - Sessions
  - Flows
  - Docs
  - Files
- Add a `Quick Start` group with workflow shortcuts such as:
  - RNA-seq DE
  - Evidence Review
  - Compliance
- Add a `Recent` group with recently used sessions or workspaces.
- Create clear hierarchy between:
  - primary nav icons
  - quick-start shortcuts
  - recent items
- Ensure active and hover states are obvious but subtle.
- Keep the sidebar visually light:
  - minimal chrome
  - tight spacing
  - muted metadata
- Preserve session management affordances already supported by the backend/frontend store where possible, but avoid bloating the left rail with inline controls in this phase.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/layout/Sidebar.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts

