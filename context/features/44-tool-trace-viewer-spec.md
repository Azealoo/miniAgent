# Tool Trace Viewer Spec

## Overview

Build the compact tool-trace card shown below the workflow card so BioAPEX keeps its transparency promise without forcing users to stare at raw logs. This phase should present tool execution as structured, inspectable steps with restrained visual weight.

## Requirements

- Implement a `Tool Trace` card in the center panel below the workflow card.
- Show a compact list of tool calls for the active run or answer.
- Each row should display:
  - tool name
  - execution state
  - lightweight status badge
  - optional duration or token/count metric
- Support expandable detail rows for richer trace data later, but keep the default state compact.
- Provide clear styling for:
  - running
  - success
  - warning
  - error
- Ensure the card does not visually compete with the main assistant response or workflow card.
- Keep this card aligned with the structured event envelopes already parsed in the frontend rather than inventing a separate data model.
- Preserve future room for:
  - artifact refs
  - structured payload previews
  - warnings
  - evidence review notes

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/chat/ThoughtChain.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/chat.py

