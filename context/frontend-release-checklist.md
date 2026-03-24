# Frontend Release Checklist

Use this checklist before shipping BioAPEX frontend changes that affect session, workflow, inspector, or protected-route behavior.

## Automated Verification

- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test`
- `cd frontend && NEXT_DIST_DIR=.next-build /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next build`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH PLAYWRIGHT_BROWSERS_PATH=0 /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run test:e2e`
- `cd frontend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/node node_modules/next/dist/bin/next lint`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Key Interaction Checks

- Confirm session creation, recent-session switching, and chat streaming still produce the expected center-panel state transitions.
- Confirm workflow events, retrieval cards, compliance cards, and generated artifact surfaces render from the current backend event and payload contracts.
- Confirm the Files workspace and Inspector preview the currently selected generated artifact or raw file without dropping run context.
- Confirm Sources, Memory, Skills, and Usage tabs still load their current-session data and report meaningful empty or failure states.
- Confirm the Artifact Registry workspace loads registry records, reacts to filter changes, and preserves truthful empty or filtered-empty messaging.

## Protected Routes

- Confirm inspection-protected surfaces explain token-required or forbidden states without silently clearing the whole app into misleading empty states.
- Confirm admin-only controls remain blocked when admin access is unavailable and continue to render explicit guidance instead of generic failures.
- Confirm execution-protected chat and mutation actions stay disabled or fail truthfully when execution access is unavailable.

## Visual Smoke

- Review the `Sessions`, `Files`, `Artifacts`, and `Ops` workspaces for layout regressions at standard desktop widths.
- Review the right-rail Inspector tabs (`Files`, `Sources`, `Memory`, `Skills`, `Usage`) for clipping, overflow, and empty-state regressions.
- Review the main chat stack for streaming cursor behavior, retrieval/compliance cards, and workflow progress rendering.
