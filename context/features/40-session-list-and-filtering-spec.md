# Session List And Filtering Spec

## Overview

Refine the session experience inside the left rail so it supports fast switching and orientation without turning into a noisy chat transcript index. This phase should make recent work easy to scan while keeping the sidebar compact.

## Requirements

- Implement a filtered session list that responds to the sidebar search field.
- Show session title first and keep timestamps visually secondary.
- Keep list rows compact and readable, with enough spacing to avoid accidental clicks.
- Preserve clear active-session highlighting.
- Ensure switching sessions remains safe while streaming; the UI should reflect any disabled or blocked state clearly.
- Support empty states for:
  - no sessions yet
  - no matches for the current search
- Make recent-session metadata intentionally lightweight:
  - relative timestamp
  - optional status indicator if useful
- Avoid inline destructive controls unless they are deliberate and well-contained. Session rename/delete/compress can remain accessible, but they should not overwhelm the list.
- Keep the list behavior aligned with the actual session store semantics in the frontend app state.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/layout/Sidebar.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts

