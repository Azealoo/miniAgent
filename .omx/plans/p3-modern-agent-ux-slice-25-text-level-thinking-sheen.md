# P3 Modern Agent UX Slice 25 - Text-Level Thinking Sheen

## Goal

Move the live `Thinking` animation onto the text itself so the left-to-right light pass reads through the glyphs instead of a pill or bubble around them.

## Scope

- Replace the pill-focused sheen styling in `frontend/src/app/globals.css` with a text-clipped live gradient sweep.
- Keep the live-only class behavior in the transcript feed unchanged.
- Reuse the focused transcript verification commands from the previous sheen slices.
- Record implementation plus pending review in OMX state.

## Files In Scope

- `frontend/src/app/globals.css`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-25-text-level-thinking-sheen.md`
- `.omx/plans/p3-modern-agent-ux-slice-25-text-level-thinking-sheen-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Animate the `Thinking` text itself rather than the surrounding container.
2. Keep the motion absent from completed turns.
3. Re-run focused frontend verification.
4. Leave the slice in honest review-ready state instead of auto-approving it.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- live `Thinking` text shows a left-to-right light pass through the glyphs
- completed turns remain static
- focused frontend verification stays green
- OMX runtime state reflects implemented-but-pending-review status
