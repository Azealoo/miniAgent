# Files Workspace Spec

## Overview

Build the `Files` workspace shown in `files.png`. This phase should present generated outputs and artifacts as a dedicated center-panel file browser so users can review results outside of the chat transcript while keeping the same BioAPEX shell and inspector context.

## Requirements

- Render a dedicated `Output Files` center workspace when the `Files` mode is selected.
- Include a page title and subtitle that frame the area as a home for results, plots, and generated artifacts.
- Display a vertically stacked list of generated file cards or rows in the center workspace.
- Each file row should include:
  - file name
  - file size
  - relative time
  - associated run identifier or short run label
- Keep file rows large enough to feel substantial, but compact enough to scan quickly.
- Support common output types such as:
  - CSV / TSV results
  - images and plots
  - JSON summaries
  - HTML reports
- Ensure the file browser feels related to the active run summary and generated-file section already present in the right inspector.
- Prepare for future actions without redesigning the list:
  - preview
  - inspect metadata
  - open raw file
  - open structured artifact
- Support empty state, loading state, and no-results state.
- Keep the workspace aligned with the backend file and artifact APIs rather than a mock-only data model.

## References

- @context/screenshots/files.png
- @frontend/src/app/page.tsx
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @backend/api/files.py
- @backend/api/artifact_registry.py

