# P3 Modern Agent UX From Claw Code

## Goal

Use BioAPEX's existing streaming, inspector, and block-based session foundations to deliver a more modern agent interaction model inspired by `claw-code`: vivid while running, quiet when done, and fully inspectable underneath.

## Why This Phase Comes Next

- `claw-code` research showed that the most reusable UX value is the interaction contract, not the terminal aesthetic.
- BioAPEX already has additive turn blocks in `backend/graph/session_manager.py`, `backend/api/chat.py`, `frontend/src/lib/types.ts`, and `frontend/src/lib/api.ts`.
- The current feature is at a stable dossier stopping point, so this is a good moment to define the next UX quality phase without forcing a broad backend rewrite.

## Phase Rules

1. Borrow `claw-code`'s interaction structure, not its literal terminal chrome.
2. Keep BioAPEX's scientific identity, provenance surfaces, and safety posture intact.
3. Treat the main transcript as the answer surface, not the full runtime log.
4. Use session `blocks` as the preferred truth source when richer turn detail is needed.
5. Keep compliance visible in main chat only when it changes user action or interpretation.

## Slice 1 - Unified Turn Activity Feed

### Why This Slice Comes First

- It creates the biggest visible product improvement with the least architectural risk.
- BioAPEX already has the raw retrieval, workflow, tool, and pending-tool data needed for it.
- It lets the product feel more like a modern agent immediately, even before deeper history or composer work lands.

### Files Likely To Change

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ThoughtChain.tsx`
- `frontend/src/components/chat/RetrievalCard.tsx`
- `frontend/src/components/chat/WorkflowProgressCard.tsx`
- `frontend/src/components/chat/StreamingActivityPill.tsx`
- optional new file:
  - `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`

### Slice Must Do

1. Replace the current fragmented live-only chat widgets with one compact activity feed that can show:
   - thinking state
   - retrieval events
   - workflow progress
   - tool start/result rows
2. Give every live row a consistent shape:
   - icon
   - short verb
   - status
   - one-line summary
   - optional metric such as duration, count, or artifact count
3. Keep the feed visible only while the turn is active by default.
4. Preserve action-affecting compliance visibility after completion:
   - warning
   - approval required
   - blocked
5. Avoid dumping raw tool payloads or long retrieval lists into the main transcript.

### Done Means

- a user can tell what the agent is doing right now without being flooded by permanent chat noise
- live activity looks like one coherent agent timeline instead of separate cards stitched together
- successful low-risk turns end with a cleaner transcript than they started with

### 2026-04-01 Execution Note

Slice 1 is now implemented in the frontend chat surface.

- `ChatMessage` now renders one unified live turn-activity feed during streaming instead of separate retrieval, workflow, and tool trace cards.
- `ThoughtChain` supports an embedded mode so completed and running tool rows can live inside that feed without nested chrome.
- Completed successful traces still disappear from the center transcript after the answer lands, while compact compliance remains visible after completion.
- Verification passed with:
  - `cd frontend && npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd frontend && npm run typecheck`

## Slice 2 - Turn Details And Transcript Policy

### Why This Slice Comes Second

- Once the live feed is coherent, the product needs an equally coherent place for the full inspectable record.
- BioAPEX already has additive session blocks, so this is mostly a projection and presentation problem.

### Files Likely To Change

- `frontend/src/components/editor/InspectorPanel.tsx`
- `frontend/src/components/layout/WorkspacePanel.tsx`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- optional new files:
  - `frontend/src/components/chat/TurnDetailsPanel.tsx`
  - `frontend/src/components/session/TurnBlockTimeline.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`

### Slice Must Do

1. Formalize a transcript rule:
   - main chat keeps answer text plus escalated policy states
   - detailed runtime truth lives in a secondary surface
2. Add a first-class turn-details surface driven by `blocks` when present.
3. Show turn details chronologically with compact rows for:
   - text
   - tool use
   - tool result
   - retrieval
   - workflow event
   - usage
4. Truncate long details in the UI while preserving links to artifacts, raw files, or inspector detail.
5. Keep backward compatibility for sessions that still rely on legacy sidecar fields.

### Done Means

- the main transcript stays calm after completion
- users can still inspect everything the agent did without leaving the product blind
- the structured session model becomes a visible product advantage instead of hidden plumbing

### 2026-04-01 Execution Note

Slice 2 is now implemented and verified.

- `InspectorPanel` now exposes a first-class `Turns` tab for compact per-message runtime detail.
- `TurnDetailsPanel` renders chronological rows for text, retrieval, workflow, tool, and usage blocks without pushing that noise back into main chat.
- `store.tsx`, `api.ts`, and `types.ts` now preserve and validate additive session `blocks` while still supporting legacy sidecar session fields.
- Verification passed with:
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm test -- src/test/app-shell.contract.test.tsx`

### 2026-04-01 Execution Note

Slice 2 is now implemented in the frontend inspector and store layer.

- The frontend store now preserves session `blocks` for history-loaded messages and appends block entries while a live turn streams retrievals, tools, workflow events, and response text.
- Inspector now exposes a first-class `Turns` tab that keeps the detailed turn trace out of the main transcript while making the full runtime record inspectable in one place.
- `TurnDetailsPanel` renders chronological block-driven rows with a backward-compatible fallback for older sessions that only have legacy `content`, `tool_calls`, `workflow_events`, and `retrievals`.
- Verification passed with:
  - `cd frontend && npm test -- src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd frontend && npm run typecheck`

## Slice 3 - Quick Actions And Agent Discoverability

### Why This Slice Comes Third

- `claw-code` feels powerful partly because status and commands are discoverable, not mysterious.
- BioAPEX needs the same confidence boost, but with domain-specific actions instead of a developer-only slash catalog.

### Files Likely To Change

- `frontend/src/components/chat/Composer.tsx`
- `frontend/src/components/layout/Navbar.tsx`
- `frontend/src/components/editor/InspectorPanel.tsx`
- optional new files:
  - `frontend/src/components/chat/QuickActionMenu.tsx`
  - `frontend/src/components/chat/CommandPalette.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`

### Slice Must Do

1. Add a discoverable quick-action surface in or near the composer.
2. Make the first actions BioAPEX-native, for example:
   - run a workflow
   - inspect sources
   - open generated files
   - summarize a study
   - export outputs
3. Surface compact session status cues such as:
   - active workflow
   - selected study or workspace scope
   - model/runtime state when relevant
4. Keep the interaction lightweight and learnable on first use.
5. Avoid importing the full complexity of `claw-code`'s command table into the main UI.

### Done Means

- users can discover what the agent can do without reading docs first
- BioAPEX feels more like a guided tool and less like a blank chat box

### 2026-04-01 Execution Note

Slice 3 is now implemented in the frontend composer and shell chrome.

- `ChatInput` now exposes a lightweight quick-action bar with BioAPEX-native prompt shortcuts and high-value surface jumps instead of introducing a general command palette.
- `ChatPanel` routes those actions through the existing store primitives for workflow selection, draft priming, inspector tab changes, and workspace switching.
- `Navbar` now keeps the active workspace visible as a compact status pill, which makes the current shell scope easier to scan without leaning on the sidebar alone.
- Verification passed with:
  - `cd frontend && npm test -- src/components/chat/ChatInput.test.tsx src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd frontend && npm run typecheck`

## Slice 4 - History Density And Compaction-Inspired UX

### Why This Slice Comes Fourth

- `claw-code` treats long session continuity seriously.
- BioAPEX will need the same as sessions become richer and more artifact-heavy.

### Files Likely To Change

- `frontend/src/components/layout/WorkspacePanel.tsx`
- `frontend/src/lib/store.tsx`
- `backend/graph/session_manager.py`
- optional new files:
  - `backend/graph/session_history_summary.py`
  - `frontend/src/components/session/SessionHistorySummary.tsx`
- `backend/tests/test_session_manager.py`
- `frontend/src/test/app-shell.contract.test.tsx`

### Slice Must Do

1. Collapse older turns into denser summaries in session history views.
2. Preserve recent turns with richer detail.
3. Show summary cues such as:
   - major request
   - tools used
   - artifacts produced
   - compliance state
4. Keep full turn detail accessible on demand rather than deleting history.
5. Reuse existing summary or compression machinery where possible instead of introducing a second history system.

### Done Means

- long sessions stay navigable
- the UI rewards inspectability without becoming visually exhausting

### 2026-04-01 Execution Note

Slice 4 is now implemented across the session API, store, and main chat workspace.

- `session_manager.py` now exposes continuity summaries paired with archived history batch metadata, and archive filenames no longer collide when multiple compressions happen within the same second.
- `api/sessions.py`, `frontend/src/lib/api.ts`, and `frontend/src/lib/store.tsx` now carry additive continuity data into the frontend without changing the existing saved-history contract.
- `SessionHistorySummary` now keeps recent turns fully rendered while compacting older visible turns and archived summaries into reopenable continuity sections in the main session workspace.
- Verification passed with:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_session_manager.py -q -k "archived_history or session_continuity or compressed_summaries"`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/session/SessionHistorySummary.test.tsx src/components/chat/ChatInput.test.tsx src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

### 2026-04-01 Stabilization Note

A post-slice browser QA pass is now landed.

- `frontend/e2e/app-shell.e2e.spec.ts` now covers dense session history and archived-turn reopening in the real browser path.
- The existing streamed-chat browser test now asserts the shipped quiet-final-transcript contract instead of expecting persistent retrieval cards after completion.
- Verification passed with:
  - `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run test:e2e -- e2e/app-shell.e2e.spec.ts`

## Serial Or Parallel

This phase should be mostly serial.

Why:

- Slice 1 defines the visual grammar for live activity.
- Slice 2 depends on the transcript-vs-details rule becoming explicit.
- Slice 3 should follow after those surfaces are stable so quick actions land into a clearer shell.
- Slice 4 depends on the new truth surfaces and session-density rules.

The only likely parallel split is within Slice 2 if one worker owns backend history shaping and another owns the frontend details view.

## Success Criteria

- BioAPEX feels active and transparent during a turn without cluttering the final transcript
- final answers read like collaborator output instead of runtime logs
- users can inspect full turn truth, evidence, and artifacts when they want to
- compliance stays visible when it matters and quiet when it does not
- the UX feels closer to a modern agent product without giving up scientific rigor

## Research Inputs

- `.omx/research/claw-code-ux-benchmark-2026-04-01.md`
- `.omx/research/frontend-compliance-ux-2026-04-01.md`
- `.omx/research/claw-code-bioapex-architecture-map-2026-04-01.md`
