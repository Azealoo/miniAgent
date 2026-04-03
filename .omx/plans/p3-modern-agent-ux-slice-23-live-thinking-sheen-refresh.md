# P3 Modern Agent UX Slice 23 - Live Thinking Sheen Refresh

## Goal

Keep the left-to-right light sweep on the `Thinking` label clearly visible while a turn is actively streaming, without introducing motion on completed turns.

## Scope

- Refresh the `Thinking` label sheen styling in `frontend/src/app/globals.css`.
- Keep the live-only class behavior in the transcript feed.
- Add a focused transcript assertion that the animation class is present only while streaming.
- Record the polish pass in the current feature and OMX runtime state.

## Files In Scope

- `frontend/src/app/globals.css`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-23-live-thinking-sheen-refresh.md`
- `.omx/plans/p3-modern-agent-ux-slice-23-live-thinking-sheen-refresh-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Make the sheen pass easier to notice on live `Thinking` labels.
2. Keep the animation attached only to live turns.
3. Re-run focused frontend verification.
4. Update durable OMX state to match the shipped polish.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- live `Thinking` labels show a clearer left-to-right light pass
- completed turns remain static
- focused frontend verification stays green
- OMX runtime state reflects the polish pass
