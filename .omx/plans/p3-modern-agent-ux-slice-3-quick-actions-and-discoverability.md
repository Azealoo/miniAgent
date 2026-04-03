# P3 Modern Agent UX Slice 3 - Quick Actions And Agent Discoverability

## Goal

Finish the third `claw-code`-inspired UX slice by making BioAPEX more learnable from the composer itself: lightweight quick actions for common intents plus compact status cues that explain the current workspace context.

## Scope

- Add a discoverable quick-action surface in the session composer.
- Reuse BioAPEX-native prompt and navigation intents instead of introducing a general command palette.
- Surface compact workspace context in the shell chrome.
- Keep the changes frontend-only and additive.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/components/layout/Navbar.tsx`
- `frontend/src/components/layout/workspace-data.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Add a lightweight composer quick-action surface for:
   - workflow start prompts
   - evidence/compliance prompts
   - high-value inspector/workspace jumps
2. Keep the quick actions BioAPEX-native and descriptive rather than slash-command driven.
3. Make the shortcuts disappear once the user is actively drafting so the composer stays calm.
4. Add a compact workspace status cue in the shell so users can tell where they are without scanning the sidebar.
5. Verify prompt priming and surface navigation through frontend tests.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- users can see what BioAPEX can do directly from the composer
- quick actions prime intent or open existing surfaces without cluttering the transcript
- the navbar keeps workspace scope visible in a compact, truthful way
