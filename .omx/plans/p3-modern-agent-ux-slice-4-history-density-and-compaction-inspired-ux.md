# P3 Modern Agent UX Slice 4 - History Density And Compaction-Inspired UX

## Goal

Finish the fourth `claw-code`-inspired UX slice by making long BioAPEX sessions easier to scan: compress older work into high-signal summary surfaces while keeping recent turns rich and older detail reopenable on demand.

## Scope

- Reuse the existing session compression and archive machinery instead of introducing a parallel history format.
- Add additive session continuity data for compressed summaries and archived turn batches.
- Compact older visible turns in the main session workspace while preserving on-demand expansion.
- Keep recent turns fully rendered in the main transcript.

## Files In Scope

- `backend/api/sessions.py`
- `backend/graph/session_manager.py`
- `backend/tests/test_session_manager.py`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/components/session/SessionHistorySummary.tsx`
- `frontend/src/components/session/SessionHistorySummary.test.tsx`
- `frontend/src/test/fixtures.ts`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Add an additive saved-session continuity contract that exposes compressed summaries plus archive batch metadata.
2. Keep recent turns rich while compacting older visible turns into summary rows.
3. Show dense summary cues for older work, including request framing, tools/sources/artifacts when available, and compliance state.
4. Let archived or compacted history reopen into full chat messages on demand instead of forcing permanent loss of detail in the UI.
5. Verify the backend continuity mapping plus the frontend history-density behavior.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_session_manager.py -q -k "archived_history or session_continuity or compressed_summaries"`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/session/SessionHistorySummary.test.tsx src/components/chat/ChatInput.test.tsx src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- long sessions stay readable without flattening everything into the main transcript
- recent work remains fully expanded and conversational
- older visible turns and archived compressed history both remain inspectable on demand
