# Workflow Progress Card Spec

## Overview

Implement the center-panel workflow card that visualizes the active scientific run. This should be one of the most distinctive BioAPEX UI elements: a clear, structured view of step-based progress that turns backend workflow events into something researchers can follow at a glance.

## Requirements

- Render a workflow progress card in the main conversation stack when a workflow is active.
- Display:
  - workflow name
  - current step position
  - total step count
  - individual steps in order
  - per-step state
  - optional duration or elapsed time
- Support visual states for:
  - pending
  - running
  - completed
  - blocked
  - failed
- Ensure the current step is clearly highlighted without overwhelming the rest of the list.
- Keep the card clean and scannable enough for six or more steps.
- Make the design compatible with streamed workflow events from the backend, not just static mock data.
- Let the workflow card feel operational, not merely informational: it should communicate “where the run is” right now.
- Prepare space for future expansion into QC, approval, or artifact step details without changing the high-level layout.

## References

- @context/screenshots/dashboard.png
- @backend/api/chat.py
- @frontend/src/components/chat/ChatPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @frontend/src/lib/store.tsx

