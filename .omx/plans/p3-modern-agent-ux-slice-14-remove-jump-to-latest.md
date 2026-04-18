# P3 Modern Agent UX Slice 14 - Remove Jump To Latest

## Goal

Remove the `Jump to latest` affordance so the chat shell stays visually clean.

## Scope

- Delete the `Jump to latest` button from the sticky chat footer.
- Remove any button-specific state and handlers that are no longer needed.
- Keep the rest of the transcript and composer behavior unchanged.

## Files In Scope

- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Remove the visible `Jump to latest` affordance from the chat session shell.
2. Clean up any dead state or imports left behind by that removal.
3. Verify the chat shell still builds and the button text no longer exists in the frontend source.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "Jump to latest" frontend/src -S`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the `Jump to latest` button is gone
- the chat shell has no dead button-specific state
- focused frontend verification remains green
