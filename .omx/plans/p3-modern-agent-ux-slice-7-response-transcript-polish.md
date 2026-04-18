# P3 Modern Agent UX Slice 7 - Response Transcript Polish

## Goal

Make the BioAPEX response surface feel closer to `claude_code_src`: flatter assistant transcript rows, lighter live activity, and subtler motion while preserving BioAPEX's richer scientific and compliance truth.

## Scope

- Replace avatar-like chat markers with transcript-style sigils.
- Flatten the streaming activity feed into a slim process rail instead of stacked status cards.
- Compress tool activity rows so they read like inline process updates.
- Tune blink timing and transcript entrance motion to feel more like the reference without importing terminal chrome.
- Keep the final answer quiet after completion and preserve the current contract tests.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ThoughtChain.tsx`
- `frontend/src/app/globals.css`
- `context/current-feature.md`
- `.omx/research/claude-code-src-response-ux-2026-04-02.md`
- `.omx/plans/p3-modern-agent-ux-slice-7-response-transcript-polish-verification.md`

## Must Do

1. Restyle user and assistant turns into a flatter transcript grammar.
2. Replace heavy live card chrome with a compact thinking/activity rail.
3. Keep tool results and pending work visible while streaming without persisting them in the final transcript.
4. Borrow the reference repo's subtle blink cadence and low-motion feel.
5. Verify the updated transcript contract with focused frontend tests plus typecheck.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the transcript feels closer to a live coding-agent log than a consumer chat bubble stack
- streaming state stays visible with minimal visual noise
- finished turns settle into calm, readable answer text
- BioAPEX still surfaces warning and compliance meaning honestly
