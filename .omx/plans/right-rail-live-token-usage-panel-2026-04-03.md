## Right-Rail Live Token Usage Panel

Date: 2026-04-03

Goal:
- Restore a screenshot-aligned `Usage` inspector tab on the right rail that shows total token usage, input/output/tool breakdown, context pressure, and compact provenance metadata.

Scope:
- Reintroduce a lightweight backend session-token route for tracked totals.
- Add a frontend usage client plus a live overlay so totals move during streaming.
- Keep the inspector export footer and existing tabs intact while adding the new usage surface.

Verification:
- Backend route checks for tracked session usage and tokenizer provenance.
- Focused frontend tests for live usage aggregation and usage-tab rendering.
- Frontend typecheck after the inspector and API contract changes.
