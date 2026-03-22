# Evidence And Sources Inspector Spec

## Overview

Implement the `Sources` side of the inspector so BioAPEX can expose evidence-backed reasoning in a way that feels concrete and reviewable. This phase should establish how structured source material, evidence summaries, and scientific references appear in the session UI.

## Requirements

- Build a `Sources` inspector tab distinct from generic generated files.
- Support compact evidence/source cards that can show:
  - source label or title
  - source type
  - identifier such as PMID, dataset ID, or protocol ID
  - confidence or support state when available
- Keep the presentation structured and review-friendly rather than summary-heavy.
- Differentiate retrieved context from reviewed evidence:
  - retrieval belongs in the center retrieval card
  - sources/evidence belong in this inspector view
- Allow this inspector to grow into a richer evidence-review surface later without changing the card model.
- Provide a clear empty state when no sources or evidence are attached to the current turn/run.
- Align the UI with backend evidence cards and related source metadata where possible.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/types.ts
- @frontend/src/lib/store.tsx
- @backend/api/chat.py
- @backend/api/artifact_registry.py

