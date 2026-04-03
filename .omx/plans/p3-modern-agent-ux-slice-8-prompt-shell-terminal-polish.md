# P3 Modern Agent UX Slice 8 - Prompt Shell Terminal Polish

## Goal

Refine the BioAPEX composer so the prompt box feels closer to `claude_code_src`: one calm command shell with inline prompt cues, lighter command discovery, and less card-like chrome.

## Scope

- Flatten the existing composer container and reduce nested panel treatment.
- Restyle quick actions as command-first rails instead of rounded action pills.
- Restyle slash suggestions and analysis-mode selection as sparse helper rails.
- Keep the existing send, workflow, upload, slash-command, and exact-command behaviors intact.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Keep the shipped quick-action and slash-command interactions working.
2. Make the prompt surface read as one shell rather than a stack of cards.
3. Promote command text, sigils, and inline helper cues over icon-heavy chrome.
4. Preserve the existing analysis-mode and reference-upload affordances.
5. Verify with focused frontend tests and typecheck.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the composer reads like a browser-adapted terminal prompt instead of a glossy form card
- command discovery is lighter and more inline
- BioAPEX keeps the existing prompt-shell capabilities without regressing focused frontend coverage
