# P3 Modern Agent UX Slice 5 - General Biology Agent Shell

## Goal

Finish the next `claw-code`-inspired UX slice by making BioAPEX feel like a general biology agent first: invite broad biology questions by default, keep structured analysis runs optional, and soften workflow-centric shell language.

## Scope

- Reframe composer copy and quick actions around open-ended biology questions, evidence review, and optional structured analysis runs.
- Rename the primary structured-run workspace cue from `Flows` to the softer user-facing label `Analysis` without changing internal routing ids.
- Keep the existing workflow request contract intact so `selected_workflow` still works when the user explicitly chooses a structured run.
- Keep the slice frontend-only and additive.

## Files In Scope

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/chat/ChatPanel.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/src/components/layout/workspace-data.ts`
- `frontend/src/components/layout/WorkspacePanel.tsx`
- `frontend/src/components/chat/ChatInput.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Make the composer placeholder and quick actions question-first for a general biology assistant.
2. Keep structured analysis modes available, but present them as an optional add-on instead of the default starting point.
3. Add at least one clearly general quick action that does not preselect a workflow.
4. Soften user-facing shell copy from `Flows`/`workflow` toward `Analysis`/`structured analysis` where it improves comprehension.
5. Verify the updated contract with focused frontend tests and typecheck.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Done Means

- users can start from a biology question without feeling forced into a workflow picker
- structured analysis runs remain available and explicit when reproducible execution is needed
- the shell copy points people toward questions, evidence, and outcomes rather than workflow jargon
