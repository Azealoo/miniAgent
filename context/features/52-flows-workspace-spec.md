# Flows Workspace Spec

## Overview

Build the `Flows` workspace shown in `flows.png`. This phase should turn workflow browsing into a dedicated center-panel experience where users can quickly understand available workflow types, recent activity, and run frequency without opening a single chat session first.

## Requirements

- Render a dedicated `Workflows` center workspace when the `Flows` mode is selected.
- Include a page title and supporting subtitle matching the tone of the screenshot:
  - title communicates the mode clearly
  - subtitle explains that workflows can be managed and tracked here
- Add a clear `New Workflow` primary action in the upper-right area of the center workspace.
- Show a list of workflow cards for key workflow types such as:
  - RNA-seq DE Analysis
  - Evidence Review
  - Compliance Check
- Each workflow card should include:
  - workflow name
  - current status badge
  - run count
  - relative activity timestamp
  - a right-facing affordance indicating drill-in or open details
- Keep workflow cards large enough to feel clickable, but visually light enough to stack several in one column.
- Support distinct visual styling for at least:
  - active
  - idle
  - blocked
  - failed
- Preserve consistency with actual backend workflow concepts:
  - workflow types
  - run history
  - workflow states
- Make the workspace usable even when there are no active workflows by defining an empty state for the card list.

## References

- @context/screenshots/flows.png
- @frontend/src/components/layout/Sidebar.tsx
- @frontend/src/app/page.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @backend/workflow_specs.py
- @backend/workflow_runner.py
- @backend/api/chat.py

