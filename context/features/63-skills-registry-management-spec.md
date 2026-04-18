# Skills Registry Management Spec

## Overview

Upgrade the `Skills` surface from a static skills list/editor into a production-aware registry view. The backend now exposes a separate skills registry with enable/disable state and metadata. This phase should make that registry manageable from the frontend while preserving the current file-based skills workflow.

## Requirements

- Add a registry-aware skills view that consumes `/api/skills/registry`.
- Show each skill with:
  - name
  - location
  - enabled state
  - key metadata if available
- Distinguish between:
  - skill registry state
  - raw skill file editing
- Add controls for enable/disable that map to the backend update route.
- Make admin-only skill mutations visually distinct from read-only inspection.
- Preserve the ability to open or inspect the underlying skill file where appropriate.
- Keep the UI consistent with the existing `Skills` tab design, but expand it so it feels operational rather than purely editorial.
- Provide clear handling for:
  - registry loading
  - update pending
  - update failure
  - unauthorized mutation attempts

## References

- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/skills_registry.py
- @backend/tools/skills_scanner.py
- @context/features/57-skills-tab-spec.md

