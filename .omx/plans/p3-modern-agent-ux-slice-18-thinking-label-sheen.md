# P3 Modern Agent UX Slice 18 - Thinking Label Sheen

## Goal

Move the live sheen effect onto the `Thinking` label itself so it reads like a small lit badge with a steady left-to-right pass.

## Scope

- Replace the broader thinking-header sheen with a label-level sheen.
- Keep the animation subtle, continuous, and compatible with reduced-motion settings.
- Preserve the simplified thinking rail copy and layout.

## Files In Scope

- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/app/globals.css`
- `context/current-feature.md`

## Must Do

1. Keep the animation attached to the `Thinking` label instead of the full header row.
2. Make the light pass consistent and gentle.
3. Re-verify the focused frontend contract.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the `Thinking` label renders as a small animated pill
- a soft light passes left to right consistently across that label
- focused frontend verification remains green
