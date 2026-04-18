# Remove Stale Routes And Compliance UI Slice

Date: 2026-04-03

## Goal

Align the active frontend and backend with the simplified chat-engine runtime by:

- removing frontend clients for backend routes that no longer exist
- pruning clearly duplicate compatibility routes that no longer have live callers
- stripping compliance-first UI copy and cards from active chat/history/inspector surfaces

## Scope

- `backend/api/sessions.py`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/chat-stream-events.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/session-status.ts`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/editor/TurnDetailsPanel.tsx`
- `frontend/src/components/editor/InspectorPanel.tsx`
- `frontend/src/components/session/SessionHistorySummary.tsx`
- `frontend/src/components/layout/Navbar.tsx`
- `frontend/src/components/layout/workspace-data.ts`
- impacted frontend tests

## Planned edits

1. Remove dead client/server route surface:
   - drop frontend token-usage, session-compression, and skill-registry mutation clients
   - remove the duplicate `/api/sessions/{session_id}/messages` compatibility route
2. Remove or neutralize broken UI affordances:
   - remove the Usage inspector tab
   - remove admin-only skill enable/disable controls that no longer have a backend route
3. Replace compliance-first active UI with generic source/readiness language:
   - remove compliance cards from inspector
   - remove compliance-specific outcome language from turn activity and turn details
   - remove compliance badges from session history summaries
   - update navbar readiness state to use generic warnings/errors instead of compliance-specific summaries

## Verification

- frontend targeted vitest for affected files
- frontend typecheck
- backend targeted pytest for session/api health coverage if needed
