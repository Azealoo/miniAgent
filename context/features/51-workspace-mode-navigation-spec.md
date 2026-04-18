# Workspace Mode Navigation Spec

## Overview

Implement the secondary workspace navigation shown across `dashboard.png`, `flows.png`, `docs.png`, and `files.png`. This phase should make switching between `Sessions`, `Flows`, `Docs`, and `Files` feel like a real application mode change instead of a cosmetic sidebar highlight. The goal is to preserve the current BioAPEX shell while letting the center workspace render distinct products surfaces.

## Requirements

- Keep the current three-column BioAPEX shell and preserve the same visual identity.
- Treat the left-rail entries `Sessions`, `Flows`, `Docs`, and `Files` as first-class workspace modes.
- Implement mode switching so the center workspace changes substantially when a different mode is selected.
- Preserve active-state styling in the sidebar and make the selected mode obvious even at a glance.
- Keep the top bar, left rail, and right inspector visually stable while the center workspace changes.
- Ensure switching modes does not destroy the current session state unnecessarily.
- Add a state model for the active workspace mode that can be shared across the shell.
- Ensure the default landing mode remains aligned with the current session-first experience unless intentionally changed.
- Make mode changes fast and visually calm:
  - no hard reload feel
  - no layout jump
  - no heavy transitions
- Keep room for future route-based mode navigation without requiring a redesign of this phase.

## References

- @context/screenshots/dashboard.png
- @context/screenshots/flows.png
- @context/screenshots/docs.png
- @context/screenshots/files.png
- @frontend/src/app/page.tsx
- @frontend/src/components/layout/Sidebar.tsx
- @frontend/src/components/layout/Navbar.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts

