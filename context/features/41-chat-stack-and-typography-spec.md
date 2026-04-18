# Chat Stack And Typography Spec

## Overview

Implement the central message stack so the conversation feels precise, scientific, and trustworthy. The revised design already has good structure; this phase should tune the message hierarchy, typography, and spacing so the center panel reads like a serious analytical workspace rather than an oversized consumer chat UI.

## Requirements

- Implement a message stack that clearly separates:
  - user request
  - assistant response
  - supporting cards that belong to the same turn
- Reduce oversized prompt/response typography and tighten line height slightly so content feels more disciplined.
- Use clear hierarchy between:
  - speaker identity
  - main body text
  - supporting metadata
  - timestamps or technical labels
- Make the assistant response feel calm and highly readable for multi-paragraph scientific output.
- Keep enough whitespace between turns to maintain clarity, but avoid excessive vertical looseness.
- Preserve streaming behavior in the center workspace so the conversation can grow naturally without layout jumps.
- Ensure the message area visually hands off into the retrieval, workflow, and trace cards below instead of feeling like separate mini-apps.
- Keep message styling aligned with the BioAPEX palette and avoid generic bubble-chat patterns.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/chat/ChatPanel.tsx
- @frontend/src/components/chat/ChatMessage.tsx
- @frontend/src/app/globals.css
- @frontend/src/lib/store.tsx

