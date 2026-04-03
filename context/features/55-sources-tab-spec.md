# Sources Tab Spec

## Overview

Implement the `Sources` inspector tab shown in `sources.png`. This phase should make the right-side panel feel like a compact evidence review surface where citations, support strength, and compliance outcomes are easy to scan during or after a run.

## Requirements

- Add a fully designed `Sources` tab to the right inspector using the screenshot as the reference layout.
- Keep the tab compact, scannable, and visually lighter than the center workspace.
- Include a `Citations` section that renders source entries with:
  - source title or topic
  - stable identifier such as PMID
  - support/confidence percentage
- Make individual citations feel reviewable and clearly separated from each other.
- Support a compact badge or pill style for source identifiers so they remain readable in a narrow panel.
- Add a `Compliance` summary card under the citations list.
- The compliance card should support checklist-style rows such as:
  - provenance verified
  - params logged
  - audit complete
- Keep the card structure flexible enough to map to actual compliance or evidence-review data later.
- Preserve the export footer action at the bottom of the inspector.
- Ensure the `Sources` tab does not duplicate the retrieval card in the center workspace; this tab should feel like a downstream inspection surface.

## References

- @context/screenshots/sources.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/types.ts
- @frontend/src/lib/store.tsx
- @backend/api/chat.py
- @backend/api/artifact_registry.py

