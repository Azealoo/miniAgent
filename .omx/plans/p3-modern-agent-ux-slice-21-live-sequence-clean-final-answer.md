# P3 Modern Agent UX Slice 21 - Live Sequence Clean Final Answer

## Goal

Make streamed assistant turns feel fluent by showing thinking and answer text in one live sequence, then collapse the completed turn back to the clean final answer without leftover thinking lines.

## Scope

- Keep a live `Thinking` rail for all streaming turns.
- Render mixed process-and-answer streaming turns as one chronological sequence.
- Remove the thinking trail once the assistant response is complete.
- Preserve the final worked-duration caption and existing choice prompts.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-21-live-sequence-clean-final-answer.md`
- `.omx/plans/p3-modern-agent-ux-slice-21-live-sequence-clean-final-answer-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Keep streamed thinking visible while the turn is active.
2. Make mixed live turns read in chronological order instead of answer-plus-leftover-trail.
3. Remove the thinking/process trail from the completed final message.
4. Re-verify the focused frontend contract and record the runtime state.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- live turns show a fluent sequential stream of process and answer updates
- completed turns keep only the final answer plus its duration caption
- focused frontend verification stays green
- OMX runtime state reflects the cleanup
