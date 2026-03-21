# Navbar And Global Status Spec

## Overview

Build the BioAPEX top bar so it communicates product identity, active workspace context, and live backend state without visually crowding the rest of the application. This phase should make the navbar feel reliable and operational rather than decorative.

## Requirements

- Implement a clean top bar with:
  - BioAPEX wordmark/logo area
  - current workspace or project title
  - backend connection status
  - active workflow label
  - RAG state
  - compliance or readiness indicator
  - export action
  - user/profile area
- Keep status indicators concise and scannable. They should read as live system state, not as oversized filter chips.
- Make the project/workspace title visually stronger than the status pills so the bar has a clear anchor.
- Use iconography sparingly and only when it improves scan speed.
- Add visual states for:
  - connected
  - reconnecting or unavailable
  - workflow selected
  - RAG enabled vs disabled
  - clean vs warning compliance state
- Ensure the export action feels like a real product action, not a mock button.
- Keep the navbar height compact enough that the center workspace keeps most of the screen height.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/layout/Navbar.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @frontend/src/lib/api.ts

