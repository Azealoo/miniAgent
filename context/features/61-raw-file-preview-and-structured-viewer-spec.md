# Raw File Preview And Structured Viewer Spec

## Overview

Add a raw-file and structured-artifact preview layer so users can inspect outputs without leaving BioAPEX. This phase should make the `Files` workspace and artifact flows feel production-ready by supporting both plain file content and structured JSON-like artifacts.

## Requirements

- Add frontend support for the backend raw-file endpoint.
- Support preview modes for at least:
  - plain text / markdown
  - JSON
  - HTML-like report references
  - image outputs
- For JSON or structured payloads, provide a readable structured view instead of a raw blob when possible.
- Preserve a path back to the raw content for advanced inspection.
- Make file preview aware of artifact context:
  - display file path
  - artifact type when available
  - run identifier when available
- Ensure larger files fail gracefully with clear messaging if the UI cannot or should not fully render them inline.
- Keep preview surfaces visually subordinate to the main workflow/chat workspace while still feeling powerful.
- Avoid building a generic IDE file explorer; the goal is scientific output inspection.

## References

- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/files.py
- @context/features/48-generated-files-list-spec.md
- @context/features/54-files-workspace-spec.md

