# P3 Modern Agent UX Slice 2 - Turn Details And Transcript Policy

## Goal

Finish the second `claw-code`-inspired UX slice by making BioAPEX's answer surface quiet after completion while exposing a first-class inspectable turn-details surface backed by session `blocks`.

## Scope

- Keep main chat focused on final answer text plus action-affecting policy states.
- Expose a dedicated `Turns` inspector surface for full per-turn detail.
- Prefer session `blocks` when present and preserve backward compatibility with legacy sidecar fields.
- Keep this slice frontend-first and additive.

## Files In Scope

- `frontend/src/components/editor/InspectorPanel.tsx`
- `frontend/src/components/editor/TurnDetailsPanel.tsx`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/test/app-shell.contract.test.tsx`
- `context/current-feature.md`

## Must Do

1. Formalize the transcript rule in product behavior:
   - main chat keeps the answer surface
   - turn-by-turn runtime truth moves into the inspector
2. Add a first-class `Turns` inspector tab with chronological rows for:
   - text
   - tool use
   - tool result
   - retrieval
   - workflow event
   - usage
3. Prefer `blocks` as the source of truth when present.
4. Preserve compatibility for legacy history payloads that still rely on `content`, `tool_calls`, `workflow_events`, or `retrievals`.
5. Keep long detail compact in the inspector without dumping full payloads into main chat.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`

## Done Means

- main chat stays calm after turn completion
- `Turns` inspector exposes the detailed runtime record
- session `blocks` are product-visible rather than hidden plumbing
- old sessions still render truthfully
