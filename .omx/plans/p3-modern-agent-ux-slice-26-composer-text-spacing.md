# P3 Modern Agent UX Slice 26 - Composer Text Spacing

## Goal

Tighten the one-line composer so the typed text sits more naturally inside the stripped-down input shell.

## Scope

- Adjust composer shell padding and textarea sizing in `frontend/src/components/chat/ChatInput.tsx`.
- Keep the existing minimal composer behavior intact.
- Reuse focused composer verification.
- Record implementation plus pending review in OMX state.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-26-composer-text-spacing.md`
- `.omx/plans/p3-modern-agent-ux-slice-26-composer-text-spacing-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Reduce excess vertical space around the typed line.
2. Preserve one-line default behavior and multiline growth.
3. Re-run focused frontend verification.
4. Leave the slice in honest review-ready state instead of auto-approving it.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the typed line sits more naturally in the composer shell
- one-line default behavior remains intact
- focused frontend verification stays green
- OMX runtime state reflects implemented-but-pending-review status
