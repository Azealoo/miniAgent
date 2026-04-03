# P3 Modern Agent UX Slice 27 - Second Plan Merged Helper Prefix Fix

## Goal

Stop second-plan helper narration from leaking into the transcript without hiding the real answer text that can share the same merged text block.

## Scope

- Trim planner helper prefixes and matched step-list prefixes at text-block normalization time.
- Keep legitimate numbered final answers visible when they do not mirror the nearby plan steps.
- Add coverage for the real reducer shape where post-plan tokens merge into one text block.

## Files In Scope

- `frontend/src/lib/message-blocks.ts`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/lib/chat-stream-reducer.test.ts`
- `.omx/plans/p3-modern-agent-ux-slice-27-second-plan-merged-helper-prefix-fix.md`
- `.omx/plans/p3-modern-agent-ux-slice-27-second-plan-merged-helper-prefix-fix-verification.md`

## Must Do

1. Strip only helper narration prefixes instead of suppressing whole merged text blocks.
2. Match removable step lists against the adjacent `plan` block rather than any numbered list.
3. Regress the single merged post-plan text-block shape.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/lib/chat-stream-reducer.test.ts src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the updated-plan helper preamble and duplicated step list no longer render in the assistant answer area
- merged text blocks still preserve the real follow-up answer
- unrelated numbered answers remain visible
- focused frontend verification is green
