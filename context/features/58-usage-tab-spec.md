# Usage Tab Spec

## Overview

Implement the `Usage` inspector tab shown in `usage.png`. This phase should present token and session usage as a compact operational readout, not a generic analytics dashboard. The tab should help users understand cost and context pressure without distracting from the main workflow.

## Requirements

- Add a designed `Usage` tab layout that matches the screenshot structure.
- Display a strong top-line total token value as the primary metric.
- Show a compact breakdown for:
  - input
  - output
  - tools
- Include a context-usage indicator with current usage vs available budget or window.
- Add a compact metadata section for:
  - provenance or mode label
  - session identifier
  - model name
- Keep the visual treatment minimal and numerical rather than chart-heavy.
- Make the tab readable in the narrow inspector width without wrapping into clutter.
- Align values with the real token stats already available in the frontend/backend interfaces.
- Preserve the inspector export footer at the bottom.
- Define empty and unavailable states gracefully for sessions without usage data.

## References

- @context/screenshots/usage.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/tokens.py
