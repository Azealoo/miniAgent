# Generated Files List Spec

## Overview

Build the generated-files section in the right inspector so BioAPEX’s file-first behavior becomes visible in the UI. This phase should focus on compact file rows, metadata clarity, and a clean mapping between workflow outputs and the artifact surface users can inspect.

## Requirements

- Implement a `Generated` or equivalent file-output section in the Files inspector.
- Render output rows for workflow-generated files such as:
  - result tables
  - plots
  - JSON summaries
  - reports
- Each row should include:
  - file name
  - lightweight file-type cue if useful
  - file size or small metadata value
- Keep rows dense and scannable, suitable for several generated artifacts.
- Ensure styling differentiates file outputs from generic navigation items.
- Prepare the list for future interaction:
  - preview
  - open raw file
  - open structured artifact
- Make the file list consistent with backend file and artifact capabilities rather than inventing disconnected mock concepts.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/files.py
- @backend/api/artifact_registry.py

