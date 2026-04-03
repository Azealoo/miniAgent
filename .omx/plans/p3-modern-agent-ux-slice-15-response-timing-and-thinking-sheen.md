# P3 Modern Agent UX Slice 15 - Response Timing And Thinking Sheen

## Goal

Make the assistant feel lighter by showing elapsed-time copy instead of the old `working through` phrasing, and add a subtle sheen animation to the live thinking header.

## Scope

- Add frontend-only message timing fields for live assistant turns.
- Show elapsed-time copy in the live thinking header when timing is available.
- Show a faint worked-duration note under completed assistant answers.
- Add a subtle left-to-right sheen animation to the thinking header.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/app/globals.css`
- `frontend/src/lib/message-duration.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/types.ts`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Keep the timing copy small and secondary to the actual answer.
2. Make the thinking animation subtle and compatible with reduced-motion settings.
3. Verify the focused chat/frontend contract after the polish.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the live thinking header prefers elapsed-time language when timing is known
- completed assistant answers can show a faint worked-duration note
- the thinking header has a subtle left-to-right sheen while streaming
- focused frontend verification remains green
