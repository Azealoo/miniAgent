# P3 Modern Agent UX Slice 22 - Persistent Process-First Transcript

## Goal

Keep the compact thinking/process transcript visible first, both while the assistant is streaming and after the answer completes, while the answer itself streams directly in the normal markdown block below it.

## Scope

- Keep the `Thinking` rail above the answer for live turns.
- Preserve the same compact process rail above the completed answer instead of collapsing it away.
- Stream the assistant answer directly in the markdown content area below the process rail.
- Update focused transcript tests and runtime records to match the final policy.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `context/current-feature.md`
- `.omx/plans/p3-modern-agent-ux-slice-22-persistent-process-first-transcript.md`
- `.omx/plans/p3-modern-agent-ux-slice-22-persistent-process-first-transcript-verification.md`
- `.omx/state/tasks.json`
- `.omx/state/reviews.json`

## Must Do

1. Keep the compact process rail mounted above the answer for both live and completed assistant turns when process activity exists.
2. Let the markdown answer stream in its own block below that rail instead of mixing answer snippets into the rail.
3. Preserve the existing duration caption and inline approval/review prompts.
4. Re-run the focused frontend verification and record the final OMX state.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- process/thinking stays visible first for live and completed assistant turns
- answer text streams directly below the process rail
- focused frontend verification stays green
- OMX runtime state reflects the final transcript policy
