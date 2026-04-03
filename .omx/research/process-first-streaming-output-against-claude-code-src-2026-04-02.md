# Process-First Streaming Output Against Claude Code Src

Date: 2026-04-02
Mode: plan + research

## Question

After `P7`, what is the best BioAPEX-native way to stream output when comparing the current frontend and backend interaction against `ponponon/claude_code_src` as the gold standard?

Constraint:

- keep the current BioAPEX process-first display policy:
  - show thinking or process activity first
  - stream the answer below it
  - keep the completed process trail visible rather than collapsing it away

## Sources Reviewed

### Current BioAPEX frontend and runtime

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/types.ts`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/editor/TurnDetailsPanel.tsx`
- `.omx/plans/p3-modern-agent-ux-slice-21-live-sequence-clean-final-answer.md`
- `.omx/plans/p3-modern-agent-ux-slice-22-persistent-process-first-transcript.md`
- `.omx/research/claude-code-src-streaming-runtime-comparison-2026-04-02.md`

### Gold-standard reference repo

- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/QueryEngine.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/cli/structuredIO.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/cli/remoteIO.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/cli/transports/SSETransport.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/utils/streamlinedTransform.ts`

## Executive Verdict

Do not copy the gold standard's transport stack wholesale.

The best next BioAPEX move is:

1. keep browser SSE
2. define one explicit typed stream-event contract across backend and frontend
3. make the frontend consume the full event set live
4. keep the process-first rail above the answer
5. centralize optimistic stream-state reduction so persisted and live rendering use the same block model
6. optionally add monotonic event indexes after the contract is stable

## Current BioAPEX Strength

BioAPEX already has the right display policy for this product.

- `frontend/src/components/chat/ChatMessage.tsx` keeps process activity above the answer.
- `frontend/src/components/chat/TurnActivityFeed.tsx` already knows how to summarize `retrieval`, `plan`, `verification`, and tool blocks.
- `frontend/src/components/editor/TurnDetailsPanel.tsx` already understands the same persisted block families.
- Earlier UX work explicitly established the process-first transcript contract in `P3` slice 22.

This means the desired output style is not the problem.

## Current BioAPEX Gap

The real problem is stream-contract mismatch and duplicated frontend state logic.

### Gap 1: frontend parser ignores live backend events it should understand

`frontend/src/lib/api.ts` currently handles:

- `retrieval`
- `token`
- `tool_start`
- `tool_end`
- `new_response`
- `done`
- `title`
- `error`

But the backend already emits richer events such as:

- `plan_created`
- `plan_updated`
- `verification_result`

The stream test already includes those events, but the parser callback contract still does not surface them.

### Gap 2: the store uses ad hoc callback wiring instead of a real stream-event reducer

`frontend/src/lib/store.tsx` maps each callback separately into optimistic message state.

That is workable for a small event surface, but it is brittle now that the backend event grammar is larger and more structured.

### Gap 3: live and persisted block shaping are still too spread out

`ChatMessage`, `TurnActivityFeed`, and `TurnDetailsPanel` all reconstruct or derive blocks in slightly different ways.

That duplication makes the frontend feel "weird" because the same turn can be represented differently depending on whether it is:

- live
- freshly persisted
- reloaded from history

### Gap 4: transport and schema are too tightly coupled in the frontend

The frontend parser in `api.ts` understands raw SSE framing and directly dispatches UI callbacks.

The gold-standard repo is stronger because it treats:

- message schema as primary
- transport as an adapter

BioAPEX does not need NDJSON stdout, but it does need that same separation of concerns.

## What The Gold Standard Gets Right

`claude_code_src` is stronger here because:

- it has one canonical structured message grammar
- transport adapters sit under that grammar
- replay and reconnect semantics are easier because messages are first-class
- output views are transformed from the same underlying event stream

That is the right lesson to borrow.

## Best BioAPEX-Native Streaming Shape

### Transport

Keep SSE for the browser.

Reasons:

- it already fits the current browser-first app
- the backend already emits SSE through `ChatRuntime`
- moving to WebSocket now would increase complexity without solving the main UX mismatch

### Event contract

Define one explicit `ChatStreamEvent` union on the frontend that covers every backend event BioAPEX expects to stream live, including:

- `retrieval`
- `token`
- `tool_start`
- `tool_end`
- `plan_created`
- `plan_updated`
- `verification_result`
- `new_response`
- `done`
- `title`
- `error`

Optionally reserve room for:

- `review_state`
- monotonic `event_index`

### State management

Replace callback-by-callback optimistic mutations with a single reducer-like path:

- parse SSE frame into `ChatStreamEvent`
- pass the event into one `applyStreamEvent()` state transition
- update the current optimistic assistant turn in one place

This gives BioAPEX the same big benefit the gold-standard repo gets from a primary message grammar, without copying its full transport stack.

### Rendering policy

Keep the current process-first transcript policy.

Do not switch to a single interleaved chronological stream if that would weaken the current product feel.

The right model is:

- process rail first
- streamed answer markdown below
- completed process rail still visible above the final answer

That means `plan`, `verification`, `retrieval`, and tool activity should appear in `TurnActivityFeed` live as soon as they arrive, while answer text continues to stream in the markdown area below.

### Backend touchpoint

The backend can stay mostly as-is.

The only backend-side improvement worth planning soon is:

- optional `event_index` or monotonic sequence numbers on streamed payloads
- possibly a serializer seam so `ChatRuntime` emits typed events before converting them to SSE

Those are nice follow-ups, not prerequisites for the next frontend phase.

## Recommended Post-P7 Phase

The best post-`P7` phase is a focused frontend/backend stream-alignment pass:

1. normalize the live event contract
2. make the frontend consume all live backend events
3. centralize optimistic stream reduction
4. remove block-derivation duplication across display components
5. keep the process-first visual contract intact
6. only then add event-index hardening if needed

## Bottom Line

The best way to stream BioAPEX output is not to imitate `claude_code_src` visually or transport-for-transport.

It is to copy its architectural lesson:

- one primary structured event grammar
- transport adapter second
- UI views derived from that grammar

For BioAPEX specifically, that should power a process-first transcript:

- thinking or process first
- answer second
- persisted and live turns rendered from the same block model
