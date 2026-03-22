# Sticky Composer Spec

## Overview

Implement the bottom composer so the session screen feels like a live working assistant instead of a static dashboard. This phase should make the composer the obvious action surface of the app while preserving the calm, premium BioAPEX visual style.

## Requirements

- Keep the composer sticky at the bottom of the center workspace.
- Include:
  - prompt textarea
  - workflow selector
  - attached identifier chips
  - attach/reference action
  - send action
- Make the composer visually integrated with the center workspace rather than looking like a detached footer.
- Keep the textarea large enough for scientific prompts, but avoid the oversized, bulky feel of earlier versions.
- Ensure attached identifiers or selections can be displayed as lightweight chips without crowding the input.
- Support clear states for:
  - idle / ready
  - streaming / submitting
  - disabled because of app state
- Preserve real integration points already present in the frontend API contract for `selected_workflow` and `attached_identifiers`.
- Make the composer feel precise and premium, not like a generic messaging box.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/chat/ChatInput.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts

