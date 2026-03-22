# Active Run Summary Spec

## Overview

Implement the active-run summary module in the right inspector so users can immediately understand the status of the current workflow without leaving the session view. This phase should surface run-state context in a compact, highly scannable form.

## Requirements

- Add an `Active Run` summary card near the top of the Files inspector.
- Display:
  - run title or workflow name
  - current run state
  - completed steps vs total steps
  - optional progress label
- Keep the card compact and easy to parse in under a second.
- Ensure the summary reflects actual workflow state from the frontend store or streamed events rather than static mock text.
- Support at least these states:
  - not started
  - in progress
  - blocked
  - completed
  - failed
- Keep this card visually distinct from the generated-files list below it.
- Make the module robust when no run is active by providing a graceful empty state.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @backend/api/chat.py

