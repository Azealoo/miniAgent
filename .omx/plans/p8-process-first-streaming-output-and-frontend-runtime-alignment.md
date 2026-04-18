# P8 Process-First Streaming Output And Frontend Runtime Alignment

Date: 2026-04-02
Status: future phase after `P7`

## Goal

After `P7`, upgrade BioAPEX's streaming frontend and backend interaction by:

- aligning the live browser stream contract with the richer backend event set
- keeping the current process-first display policy intact
- centralizing optimistic stream reduction so live and persisted turns share the same block model
- reducing duplicated block-shaping logic across chat and inspector surfaces
- improving transport and schema boundaries without replacing SSE

## Product Constraint

Keep the current showing logic:

- process or thinking first
- answer below it
- completed process trail remains visible

Do not regress to a fully interleaved "terminal log" presentation if it weakens the current BioAPEX chat feel.

## Why This Phase Comes Next

- `P7` is the right semantics pass for skills and memory.
- The next visible product gap is streaming truthfulness and frontend/backend alignment.
- The backend already emits richer stream events than the frontend uses live.
- The frontend already has a strong process-first UI language, but the event plumbing underneath it is incomplete and duplicated.

## Must-Have End State

- The live frontend understands the full streamed event set BioAPEX expects to render.
- SSE framing remains the browser transport, but event parsing is separated from state reduction.
- The optimistic assistant message updates through one stream-event reducer path rather than scattered callbacks.
- `ChatMessage`, `TurnActivityFeed`, and `TurnDetailsPanel` render from the same normalized block semantics.
- `plan` and `verification` artifacts appear live in the process rail, not only after reload.
- The process-first transcript policy survives the refactor unchanged.

## Phase Rules

1. Keep the browser transport as SSE unless a slice proves that transport is the blocker.
2. Treat the event schema as primary and the transport parser as an adapter.
3. Do not regress the existing process-first transcript policy from `P3` slice 22.
4. Prefer one normalized `blocks` model across live and persisted turns instead of parallel frontend-only representations.
5. Keep backend changes narrow and in service of the stream contract, not a new harness redesign.

## Slice 1: Typed Stream Event Contract

### Goal

Make the live event grammar explicit and complete on the frontend.

### Likely File Targets

- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- new stream-event helper under `frontend/src/lib/`
- `frontend/src/lib/api.stream-chat.test.ts`

### Must Do

- Define a typed `ChatStreamEvent` union for the live browser stream.
- Cover all event types the backend already emits and the frontend should handle:
  - `retrieval`
  - `token`
  - `tool_start`
  - `tool_end`
  - `plan_created`
  - `plan_updated`
  - `verification_result`
  - `new_response`
  - `done`
  - `error`
- Convert SSE parsing into typed event emission instead of direct UI callbacks.
- Make `api.stream-chat.test.ts` assert the complete typed event flow instead of silently ignoring unknown events.

### Verification

- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

### Done When

- The frontend parser has one typed live event contract.
- `plan` and `verification` are no longer absent from the frontend event grammar.

### Depends On

- none

## Slice 2: Optimistic Stream Reducer

### Goal

Replace callback-scattered optimistic turn updates with one reducer path for live stream events.

### Likely File Targets

- `frontend/src/lib/store.tsx`
- new reducer/helper under `frontend/src/lib/`
- `frontend/src/lib/types.ts`
- focused store or contract tests under `frontend/src/`

### Must Do

- Introduce one `applyStreamEvent()` or equivalent reducer path for optimistic assistant turns.
- Route typed stream events from `api.ts` through that reducer.
- Keep `new_response` semantics for bounded repair or multi-segment replies.
- Preserve request-id handling, pending tool state, and streaming lifecycle markers.

### Verification

- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts src/test/app-shell.contract.test.tsx`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

### Done When

- Live optimistic state updates happen in one place.
- Adding a new event type no longer requires fragile callback surgery across the store.

### Depends On

- Slice 1

## Slice 3: Live Process Rail Completeness

### Goal

Make the process-first rail live-complete for the backend event surface.

### Likely File Targets

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/components/chat/TurnActivityFeed.test.tsx` if needed

### Must Do

- Render live `plan_created` and `plan_updated` blocks in the process rail.
- Render live `verification_result` blocks in the process rail.
- Keep answer markdown streaming below the rail.
- Preserve approval and evidence-review prompts without disturbing the process-first layout.

### Verification

- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

### Done When

- The live process rail reflects the real backend activity, not just tools and retrievals.
- The current process-first display policy is preserved.

### Depends On

- Slice 2

## Slice 4: Shared Block Normalization Across Surfaces

### Goal

Remove duplicated block derivation so chat and inspector views stay aligned.

### Likely File Targets

- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/editor/TurnDetailsPanel.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`
- new shared block-normalization helper under `frontend/src/lib/`
- `frontend/src/components/editor/TurnDetailsPanel.test.tsx`

### Must Do

- Extract one shared block-normalization or `deriveBlocks()` helper.
- Use the same normalized block model for:
  - live chat display
  - completed chat display
  - turn details
  - reloaded session history
- Reduce special-case divergence between `content`, `tool_calls`, `retrievals`, and `blocks`.

### Verification

- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

### Done When

- The same turn looks structurally consistent whether it is live, completed, or reloaded.
- Frontend block semantics are no longer duplicated across multiple components.

### Depends On

- Slice 2

## Slice 5: Narrow Backend Stream Contract Hardening

### Goal

Tighten the backend-to-frontend stream seam without changing the core transport model.

### Likely File Targets

- `backend/runtime/chat_runtime.py`
- `backend/runtime/query_engine.py`
- `backend/api/chat.py`
- `backend/tests/test_chat_streaming.py`
- `frontend/src/lib/api.stream-chat.test.ts`

### Must Do

- Consider adding optional monotonic `event_index` or similar sequence metadata to streamed payloads.
- Keep typed event names and payload fields stable for frontend parsing.
- Add framing or ordering coverage where the current contract is brittle.
- Avoid introducing a second transport or a large remote-session subsystem.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_runtime_query_engine.py -q`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts`

### Done When

- The stream contract is slightly more robust without becoming more complex than the product needs.
- Frontend parsing has a stable contract to depend on.

### Depends On

- Slice 1
- Slice 2

## Slice 6: Final Polish And Regression Closeout

### Goal

Close the streaming phase with one coherent frontend/backend story.

### Likely File Targets

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/editor/TurnDetailsPanel.tsx`
- `backend/runtime/chat_runtime.py`
- `backend/tests/test_chat_streaming.py`
- focused frontend test files touched by the phase

### Must Do

- Align the parser, reducer, and display layers so they tell the same event story.
- Confirm that the process-first rail remains the stable UI contract.
- Re-run the focused frontend and backend streaming sweeps together.

### Verification

- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
- `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_runtime_query_engine.py -q`

### Done When

- Live and persisted turns share one coherent rendering model.
- The stream contract is complete for the events BioAPEX actually emits.
- The frontend feels less weird because its state model now matches backend truth.

### Depends On

- Slices 1 through 5
