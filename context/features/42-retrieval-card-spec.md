# Retrieval Card Spec

## Overview

Build the `Knowledge Retrieved` card shown in the revised design so retrieval becomes a visible, trustworthy part of the conversation. This phase should help users understand what supporting context BioAPEX pulled into the answer without drowning them in raw trace data.

## Requirements

- Implement a retrieval card directly under the assistant response when supporting context is available.
- The card should clearly communicate:
  - that knowledge or memory was retrieved
  - what major sources or snippets were used
  - how many sources contributed
- Support compact row entries for retrieved items such as:
  - datasets
  - protocols
  - notes
  - knowledge-base files
- Keep the card visually lighter than the main assistant response while still feeling first-class.
- Make the source count visible and easy to scan.
- Ensure retrieved items can later grow into clickable references or drill-down actions without redesigning the card structure.
- Distinguish retrieval from evidence review:
  - retrieval card = contextual support loaded into the run
  - evidence card = structured scientific support surfaced separately
- Keep the card aligned with real retrieval data already handled by the frontend store and stream parser.

## References

- @context/screenshots/dashboard.png
- @frontend/src/components/chat/RetrievalCard.tsx
- @frontend/src/lib/store.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts

