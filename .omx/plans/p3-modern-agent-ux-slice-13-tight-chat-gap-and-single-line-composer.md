# P3 Modern Agent UX Slice 13 - Tight Chat Gap And Single-Line Composer

## Goal

Bring the last assistant turn closer to the composer and make the prompt box read like a true one-line field by default.

## Scope

- Reduce the reserved bottom space under the session transcript.
- Tighten the sticky composer spacer and shell padding.
- Make the textarea rest at one line while preserving multiline growth.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/components/session/SessionHistorySummary.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Pull the final transcript line closer to the sticky composer without clipping content.
2. Keep the minimal composer shell, slash commands, uploads, and workflow controls intact.
3. Verify the focused frontend contract after the spacing pass.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the transcript ends closer to the composer
- the prompt box rests as a one-line field by default
- focused frontend verification remains green
