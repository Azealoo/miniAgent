# P3 Modern Agent UX Slice 20 - Sequenced Thinking Review Fix

## Goal

Resolve the slice 19 review gaps by turning the under-response thinking rail into a real block-ordered mini transcript, surfacing concrete source labels, and backfilling durable OMX runtime state for the modern-agent transcript work.

## Scope

- Render assistant thinking/process lines in block order instead of one aggregated summary.
- Show concrete source or memory labels in retrieval lines.
- Keep the answer-first transcript layout while adding short answer-update lines underneath for mixed turns.
- Record a real OMX task/review trail for this review remediation pass.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-20-sequenced-thinking-review-fix.md`
- `.omx/plans/p3-modern-agent-ux-slice-20-sequenced-thinking-review-fix-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Keep the finished answer at the top of the assistant message.
2. Replace the bundled thinking summary with a chronological mini log derived from streamed blocks.
3. Make retrieval lines name concrete sources or memory instead of only source counts.
4. Leave behind a durable OMX task/review verdict for this fix.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- assistant messages keep the answer-first layout while the under-response thinking trail follows block order
- retrieval lines can name concrete files or memory
- focused frontend verification is green
- `.omx/state/tasks.json` and `.omx/state/reviews.json` include a real runtime entry for this pass
