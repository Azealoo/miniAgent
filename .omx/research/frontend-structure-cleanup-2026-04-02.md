# 2026-04-02 Frontend Structure And Dead-Code Review

## Question

Is the current BioAPEX frontend in a good structural state, what dead code can be removed safely now, and what should BioAPEX actually mimic from `ponponon/claude_code_src`?

## Repo Truth

- The current frontend is heavily concentrated in a few large files:
  - `frontend/src/components/editor/InspectorPanel.tsx` (`4600` lines)
  - `frontend/src/components/layout/OpsWorkspace.tsx` (`4489` lines)
  - `frontend/src/components/layout/WorkspacePanel.tsx` (`3586` lines)
  - `frontend/src/lib/store.tsx` (`1387` lines)
- A stricter TypeScript pass (`tsc --noUnusedLocals --noUnusedParameters`) found real dead code in the active tree:
  - unused `selectedWorkflow` and `onSelectWorkflow` props in `ChatInput`
  - an unused callback parameter in `TurnActivityFeed`
  - unused helper functions in `InspectorPanel`
  - unused imports in `OpsWorkspace` and `Sidebar`
- Search showed four chat components with no frontend imports:
  - `frontend/src/components/chat/ThoughtChain.tsx`
  - `frontend/src/components/chat/StreamingActivityPill.tsx`
  - `frontend/src/components/chat/RetrievalCard.tsx`
  - `frontend/src/components/chat/WorkflowProgressCard.tsx`
- `quickStartItems.workflowId` had become dead data in the current composer flow; quick starts now work as prompt-drafting actions rather than workflow preselection.

## External Truth

- `ponponon/claude_code_src` is organized around domain directories such as `src/components`, `src/screens`, `src/state`, `src/services`, `src/tools`, and `src/types`.
- The reference repo still has very large entrypoint files, especially `src/main.tsx`, so it is not evidence that "one huge file" is the desired end state.
- The clearest lesson to copy is boundary organization:
  - separate screen/surface code from shared state and helpers
  - keep domain folders explicit
  - avoid leaving feature logic stranded in stale one-off UI components

## Risks

- `WorkspacePanel`, `InspectorPanel`, and `OpsWorkspace` are already large enough to behave like god components, which raises review cost and makes dead branches harder to notice.
- `frontend/src/lib/store.tsx` currently mixes access control, session loading, draft state, file uploads, and workspace UI state in one provider.
- Deleting currently unused UI files is safe only because strict TS, targeted tests, and a production build stayed green after removal.

## Recommendation

Land targeted pruning now, then split by surface boundary in a second pass if desired.

### Safe cleanup landed in this pass

- removed unreferenced chat components
- removed stale composer workflow-selection props and dead quick-start workflow metadata
- removed unused helpers, imports, and one dead CSS animation path

### What to mimic from `claude_code_src`

- copy the explicit module-boundary style, not the file sizes
- prefer domain folders and clear surface ownership
- treat "screen" level surfaces as extraction boundaries for future refactors

### Best next refactor if a second pass is wanted

- split `WorkspacePanel` by workspace mode
- split `InspectorPanel` by tab
- move access/session side effects from `store.tsx` into dedicated hooks while keeping one shared app context boundary

## Open Questions

- Should quick starts stay draft-message based, or should BioAPEX reintroduce explicit workflow preselection in a slimmer form?
- Do we want the next pass to be a pure structural extraction with no UX changes, focused on `WorkspacePanel` and `InspectorPanel` only?

## Verification

- `cd frontend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/typescript/bin/tsc --noEmit --noUnusedLocals --noUnusedParameters -p tsconfig.typecheck.json`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatInput.test.tsx src/test/app-shell.contract.test.tsx`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd frontend && NEXT_DIST_DIR=.next-build PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`
