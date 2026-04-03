# P3 Modern Agent UX Slice 24 - Visible Live Thinking Sheen

## Goal

Fix the live `Thinking` sheen so the left-to-right light pass is actually visible on the real pale label, not just technically present in CSS.

## Scope

- Increase contrast and visibility in `frontend/src/app/globals.css`.
- Keep the live-only class behavior in the transcript feed unchanged.
- Reuse the focused transcript tests and verification commands from the previous sheen slice.
- Record implementation plus pending review in OMX state.

## Files In Scope

- `frontend/src/app/globals.css`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-24-visible-live-thinking-sheen.md`
- `.omx/plans/p3-modern-agent-ux-slice-24-visible-live-thinking-sheen-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Strengthen the sheen so the sweep is perceptible on the live `Thinking` pill.
2. Keep the motion absent from completed turns.
3. Re-run focused frontend verification.
4. Leave the slice in honest review-ready state instead of auto-approving it.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- live `Thinking` labels show a clearly perceptible left-to-right light pass
- completed turns remain static
- focused frontend verification stays green
- OMX runtime state reflects implemented-but-pending-review status
