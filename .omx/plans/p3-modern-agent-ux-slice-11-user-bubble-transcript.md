# P3 Modern Agent UX Slice 11 - User Bubble Transcript

## Goal

Make sent user prompts feel like clean chat bubbles instead of prompt-bar transcript rows.

## Scope

- Remove the old user-side `>` prompt sigil.
- Render user prompts as right-aligned bubbles.
- Keep the assistant transcript and approval/thinking surfaces unchanged.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`

## Must Do

1. Keep user prompts readable and compact in the center transcript.
2. Preserve existing assistant-side transcript behavior.
3. Verify the transcript component and shell contract after the presentation shift.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- user prompts sit on the right as bubbles
- the old prompt sigil is gone
- transcript verification remains green
