# P3 Modern Agent UX Slice 12 - Composer Micro Polish

## Goal

Apply the last small visual polish to the minimal composer: slightly shorter height and simpler placeholder text.

## Scope

- Reduce the default textarea height a bit.
- Change the empty composer placeholder to `Ask any biology related questions`.
- Keep the minimal composer shell and its existing behaviors intact.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Make the composer feel slightly tighter without undoing the recent cleanup.
2. Update tests to match the new placeholder copy.
3. Verify the focused composer contract after the micro-polish.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the composer is a bit shorter
- the placeholder reads `Ask any biology related questions`
- focused frontend verification remains green
