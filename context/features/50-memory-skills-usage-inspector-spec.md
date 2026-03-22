# Memory Skills And Usage Inspector Spec

## Overview

Finish the right inspector by implementing the `Memory`, `Skills`, and `Usage` tabs as practical operational tools. This phase should keep the existing backend-powered capabilities visible while restyling them so they match the revised BioAPEX product experience.

## Requirements

- Preserve and refine the `Memory` tab so users can inspect and edit `memory/MEMORY.md` within the updated inspector layout.
- Preserve and refine the `Skills` tab so available skills remain browsable and editable in a cleaner UI.
- Add or refine a `Usage` tab for token and usage visibility tied to the current session.
- Make these tabs feel secondary to the main run/files workflow, but still clearly useful.
- Improve hierarchy for:
  - editor area
  - open file path
  - save action
  - token counts
  - skill list rows
- Avoid letting the Monaco editor or metadata bars overwhelm the narrower inspector layout.
- Ensure save states, loading states, and dirty-file states remain obvious and trustworthy.
- Keep the `Usage` surface compact and numerical rather than decorative.
- Align all three tabs with the revised visual system established by the new inspector shell.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @frontend/src/lib/store.tsx
- @backend/api/files.py
- @backend/api/tokens.py
