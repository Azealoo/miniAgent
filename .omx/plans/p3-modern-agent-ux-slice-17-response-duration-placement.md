# P3 Modern Agent UX Slice 17 - Response Duration Placement

## Goal

Remove the live elapsed-time clock from the thinking header and place the final `Worked for ...` label above completed assistant answers.

## Scope

- Stop showing streaming elapsed-time copy in the thinking header.
- Keep the existing thinking rail wording and sheen behavior.
- Move the completed response-duration label to the top of the finished assistant answer block.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `context/current-feature.md`

## Must Do

1. Keep the transcript visually quiet while removing the live timer.
2. Make the final duration note read like a small response caption, not a footer.
3. Re-verify the focused frontend contract.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the thinking header no longer shows `Elapsed ... so far.`
- completed assistant answers show `Worked for ...` above the response text
- focused frontend verification remains green
