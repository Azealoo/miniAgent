# P3 Modern Agent UX Slice 16 - Thinking Simplification And Evidence Choice

## Goal

Make the live thinking rail calmer by collapsing it into short status phrases, and turn evidence-review-required biology turns into an explicit replay choice instead of a synthetic warning answer.

## Scope

- Simplify retrieval, tool, and workflow live-copy into terse sentence fragments.
- Add a first-class evidence-review choice contract to the chat request path.
- Pause review-required biology turns until the user chooses how to continue.
- Replay the original request with the selected evidence-review mode from the transcript.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/components/chat/ThoughtChain.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/session/SessionHistorySummary.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/evidence.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/types.ts`
- `frontend/src/test/app-shell.contract.test.tsx`
- `frontend/src/test/fixtures.ts`
- `backend/api/chat.py`
- `backend/evidence/review_gate.py`
- `backend/tests/test_chat_streaming.py`
- `context/current-feature.md`

## Must Do

1. Keep the live thinking rail free of payload dumps, snippets, and metric-heavy sentences.
2. Show a real user choice prompt when evidence review is required before answering.
3. Preserve the existing compliance approval replay behavior and quiet transcript layout.
4. Verify both the frontend contract and the backend evidence-review gate path.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py -q -k "evidence_review"`
- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_evidence_review.py -q`

## Done Means

- the live thinking rail uses short `Used...`, `Ran...`, or `Review choice needed.` lines
- evidence-review-required turns can stop without emitting a synthetic warning answer
- the transcript shows a two-choice replay prompt for `review_first` vs `skip_review`
- focused frontend and backend verification stay green
