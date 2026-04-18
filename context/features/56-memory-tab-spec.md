# Memory Tab Spec

## Overview

Implement the `Memory` inspector tab shown in `memory.png`. This phase should evolve the current memory experience from a raw editor-first surface into a compact context-memory manager that still respects BioAPEX’s file-first architecture.

## Requirements

- Add a designed `Memory` tab layout that matches the screenshot structure.
- Render a `Context Memory` section with stacked memory items.
- Each memory item should support:
  - memory namespace or key
  - memory value
  - status badge such as `ACTIVE`
  - compact action row
- Include small actions for memory items consistent with the screenshot, such as:
  - edit
  - duplicate or copy
  - delete
- Keep item cards narrow-panel friendly and easy to scan vertically.
- Add an `Add Item` action at the bottom of the memory list.
- Preserve a clear path to the underlying file-first memory model already used by the app.
- Ensure this tab still supports eventual editing or syncing with `memory/MEMORY.md`, even if the first implementation begins with a more structured UI overlay.
- Preserve the inspector export action at the bottom.
- Define empty, loading, and unsaved-edit states clearly.

## References

- @context/screenshots/memory.png
- @frontend/src/components/editor/InspectorPanel.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @backend/api/files.py
- @backend/graph/memory_retriever.py

