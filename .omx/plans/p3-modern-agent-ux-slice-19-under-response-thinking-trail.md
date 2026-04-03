# P3 Modern Agent UX Slice 19 - Under Response Thinking Trail

## Goal

Make assistant answers lead visually, then show a compact process trail underneath so users can see what the system looked at or ran.

## Scope

- Move the live thinking rail below the response when answer text exists.
- Keep a completed thinking/process trail visible under finished assistant answers.
- Add slightly more descriptive generic tool lines when a readable target is available.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ThoughtChain.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`

## Must Do

1. Lead with answer text whenever the assistant has visible content.
2. Keep the process trail compact and non-bulleted.
3. Preserve the existing choice prompts and quiet transcript styling.
4. Re-verify the focused frontend contract.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- assistant answers appear before their thinking/process trail when text exists
- completed assistant messages can still show what was looked at or run
- focused frontend verification remains green
