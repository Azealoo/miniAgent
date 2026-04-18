# P3 Modern Agent UX Slice 6 - Prompt Shell And Streaming Reveal

## Goal

Close the remaining `claw-code` interaction gap in the BioAPEX session shell by making the composer feel more commandable and by making streamed answers reveal like a live transcript instead of a token-by-token markdown reflow.

## Scope

- Add a slash-command surface to the existing composer for high-value BioAPEX prompt and navigation actions.
- Keep the live "Thinking" activity visible for the whole streaming turn, including plain-text drafting phases.
- Render streamed assistant markdown through a safe-boundary reveal so completed blocks render cleanly while partial blocks stay visibly in-progress.
- Keep the existing `selected_workflow`, `attached_identifiers`, and turn-details inspector contracts intact.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/app/globals.css`
- `frontend/src/lib/streaming-markdown.ts`
- `frontend/src/lib/streaming-markdown.test.ts`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Add keyboard-friendly slash suggestions that map to the current BioAPEX quick actions and shell surfaces.
2. Keep the composer visually prompt-like rather than form-like, with clear prompt and command cues.
3. Keep the live turn header visible until the turn finishes, even if only assistant text is arriving.
4. Buffer streamed markdown to paragraph/code-fence boundaries before rendering the rich markdown view.
5. Preserve existing frontend contracts and verify with focused chat-shell tests plus typecheck.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/components/chat/ChatMessage.test.tsx src/lib/streaming-markdown.test.ts src/test/app-shell.contract.test.tsx`

## Done Means

- the composer supports Claw-like prompt discovery without importing a full terminal command table
- streamed answers feel calmer and more intentional because partial markdown is buffered before rich rendering
- the live turn state stays visible while BioAPEX is still working, then collapses back to a quieter finished transcript
