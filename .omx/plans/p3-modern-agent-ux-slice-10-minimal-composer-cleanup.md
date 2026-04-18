# P3 Modern Agent UX Slice 10 - Minimal Composer Cleanup

## Goal

Simplify the BioAPEX composer into the cleanest practical browser shell: mostly just the prompt box, a few necessary controls, and no extra command chrome.

## Scope

- Remove the visible command rail from the composer.
- Remove the prompt sigil and extra BioAPEX header/footer copy around the textarea.
- Make the send control icon-only.
- Keep slash-command discovery, analysis-mode selection, uploads, and context chips working.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Make the composer feel cleaner and emptier without deleting existing prompt-shell behaviors.
2. Preserve slash-command execution for prompt, inspector, and workspace actions.
3. Keep analysis mode and file upload controls available.
4. Verify the composer and app-shell contract coverage after the cleanup.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- the composer reads as a quiet empty input surface instead of a command center
- the send affordance is icon-only
- slash commands and the remaining controls still behave correctly under focused frontend verification
