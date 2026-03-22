# Inspector Shell Spec

## Overview

Build the right-side inspector shell so it becomes a true support surface for the active run instead of a generic editor pane. This phase should establish the tab layout, card rhythm, and visual density of the inspector before adding each specific content module.

## Requirements

- Implement a lighter, narrower right inspector that complements rather than competes with the center panel.
- Add a top tab row for:
  - Files
  - Sources
  - Memory
  - Skills
  - Usage
- Make tab labels explicit and readable; do not rely on icons alone.
- Keep the inspector content vertically scannable with compact cards and clear section headers.
- Preserve the ability to swap inspector content based on tab selection.
- Make the inspector feel tightly related to the current run/session context.
- Reduce visual heaviness compared with the earlier editor-first inspector.
- Keep the panel consistent with the revised dashboard proportions and overall BioAPEX design language.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/app/page.tsx
- @frontend/src/lib/store.tsx

