# Claude Code Src Streaming Runtime Comparison

Date: 2026-04-02
Analyst: Codex
Source repo: https://github.com/ponponon/claude_code_src
Source commit inspected: `adb321f6a3af4e0b76a1e076168bd521e9ba20af`

## Question

How does `ponponon/claude_code_src` stream output compared with BioAPEX, and what should BioAPEX actually learn from it?

## Executive Summary

BioAPEX and `claude_code_src` both stream structured events, but they optimize for different transport boundaries.

- BioAPEX is browser-first: one `POST /api/chat` request returns `text/event-stream`, the frontend parses SSE lines, and the backend emits BioAPEX-specific runtime events such as `retrieval`, `tool_start`, `plan_created`, and `verification_result`.
- `claude_code_src` is SDK-first: the core stream is newline-delimited JSON over stdout or remote transport, with transport adapters for WebSocket or SSE+POST, and strict protections to keep the stream parseable.

The strongest leverage is not "switch to their transport". It is:

1. separate message schema from transport more aggressively
2. harden the stream against framing corruption
3. support resumable / replay-safe delivery semantics where sessions matter
4. make live clients consume the full structured event set, not just text and tool rows

## BioAPEX Current Streaming Shape

### Backend

- `backend/api/chat.py` is a thin HTTP transport adapter that declares the SSE event contract and returns `StreamingResponse(..., media_type="text/event-stream")`.
- `backend/runtime/chat_runtime.py` converts runtime events into SSE `data:` frames, adds `request_id`, records first-visible latency, persists assistant segments on completion, and emits `title` after the turn when available.
- `backend/runtime/query_engine.py` owns the turn lifecycle before transport:
  - compliance preflight
  - evidence-review gate
  - ordinary harness streaming
  - helper-agent extraction into `plan_created` / `verification_result`
  - one bounded repair retry via `new_response`
- `backend/runtime/turn_ledger.py` is the persistence boundary. It consumes stream events and materializes assistant `segments`, `tool_calls`, `retrievals`, and typed `blocks`.

### Frontend

- `frontend/src/lib/api.ts` performs a `POST` fetch, reads `response.body` directly, and manually parses SSE by splitting on blank lines and `data: ` prefixes.
- `frontend/src/lib/store.tsx` maps live events into the optimistic assistant message:
  - retrieval replaces retrieval block content
  - token appends text
  - tool_start / tool_end build transcript blocks
  - `new_response` starts a second assistant message
  - `done` closes streaming state

### Important BioAPEX gap

The backend emits `plan_created` and `verification_result`, but the live frontend parser currently ignores them. The UI can render persisted `plan` and `verification` blocks later, yet the live stream path does not surface them during the turn.

## What `claude_code_src` Does Differently

### 1. Its primary stream is NDJSON, not app-specific SSE

- `src/cli/structuredIO.ts` treats the stream as newline-delimited JSON messages and writes outbound messages with `ndjsonSafeStringify(message) + "\n"`.
- `src/utils/stream.ts` provides a single-consumer async queue abstraction used to order outbound structured messages.
- `src/bridge/sessionRunner.ts` spawns the child CLI with `--input-format stream-json` and `--output-format stream-json`.

Implication:

- Their canonical event model is transport-agnostic JSON messages.
- SSE is only one adapter layer, not the primary public contract.

### 2. They explicitly guard the stream against corruption

- `src/utils/streamJsonStdoutGuard.ts` wraps `process.stdout.write` in stream-json mode.
- Valid JSON lines stay on stdout.
- Stray non-JSON output is diverted to stderr with a sentinel marker instead of corrupting the NDJSON stream.

Implication:

- They treat framing integrity as a first-class runtime concern.
- BioAPEX currently assumes nobody writes malformed bytes into the SSE response stream.

### 3. They separate transport from message schema

- `src/cli/remoteIO.ts` extends `StructuredIO` and swaps transport beneath the same structured message flow.
- `src/cli/transports/SSETransport.ts` reads SSE frames, unwraps `client_event`, then re-emits newline-delimited JSON payloads upward.
- `src/cli/transports/WebSocketTransport.ts` sends the same structured messages over WebSocket and supports buffered replay.

Implication:

- Their client logic consumes one message grammar across local stdout, WebSocket, and SSE transport modes.
- BioAPEX currently couples the frontend to raw SSE framing and a browser-only parser.

### 4. They design for resumability and reconnects

- `SSETransport.ts` tracks `Last-Event-ID`, sequence numbers, reconnection budgets, liveness timeouts, and POST retries.
- `WebSocketTransport.ts` buffers sent messages, replays unconfirmed messages after reconnect, and tracks last activity for idle-timeout diagnosis.
- `remoteIO.ts` adds keep-alives and CCR session-state reporting.

Implication:

- Their stream is designed for remote, long-lived, failure-prone sessions.
- BioAPEX's current stream is best-effort within one request/response lifecycle.

### 5. They support multiple output views from the same base messages

- `src/utils/streamlinedTransform.ts` converts the base structured messages into a quieter "streamlined" output view.

Implication:

- They preserve one rich message grammar and derive lighter presentations from it.
- BioAPEX already has typed runtime blocks; we could use that to derive multiple browser views without changing the backend transport.

## Direct Comparison

### Where BioAPEX is already strong

- BioAPEX has a cleaner ordinary-turn runtime seam than its previous versions:
  - `QueryEngine` owns decisions
  - `TurnLedger` owns persisted turn assembly
  - `ChatRuntime` owns transport/persistence/observability glue
- BioAPEX's event grammar is already product-shaped for scientific work:
  - retrieval
  - typed tool results
  - evidence-review gating
  - planner/verifier artifacts
  - bounded repair loop

### Where `claude_code_src` is stronger

- transport abstraction
- reconnect and replay semantics
- framing hardening
- ability to carry the same message grammar across terminal, bridge, SDK, and remote session modes

### Where BioAPEX is weaker right now

- frontend live-consumption coverage is incomplete for backend event types
- transport framing is custom and brittle
- no resumable stream semantics if the browser connection drops mid-turn
- no explicit corruption guard at the framing boundary

## What BioAPEX Should Learn

### High-value, low-risk

1. Introduce a transport-neutral event schema.
   Keep emitting SSE for the browser, but define one internal `ChatStreamEvent` union that both SSE and future transports serialize from.

2. Finish the live event surface.
   Extend `frontend/src/lib/api.ts` and `frontend/src/lib/store.tsx` so `plan_created` / `plan_updated` / `verification_result` appear live, not only after persisted reload.

3. Add framing-hardening tests.
   Keep the existing chunked-SSE tests, then add cases for malformed extra output and event-order corruption at the transport boundary.

4. Add resumable request semantics only if product scope needs remote sessions.
   If BioAPEX remains local-browser-first, do not copy all of CCR/WebSocket replay. If remote workers or long-running scientific sessions become important, sequence IDs and reconnect-aware resume are worth adding.

### Medium-value, medium-risk

5. Add sequence numbers or monotonic event indexes to BioAPEX stream payloads.
   This would let the frontend detect dropped or repeated frames and would be a prerequisite for replay-safe resume.

6. Split serializer from HTTP transport.
   Today `ChatRuntime` emits literal SSE strings. A better next seam is:
   - runtime returns typed events
   - serializer converts typed events to SSE
   - future transports can reuse the same event source

### Low-value for BioAPEX right now

- copying their stdout NDJSON contract directly
- copying their full remote bridge stack
- copying transport complexity before we actually need remote-session resilience

## Suggested BioAPEX Next Slice

If we want a practical follow-up, the cleanest streaming slice is:

1. define a typed frontend callback path for `plan_created`, `plan_updated`, and `verification_result`
2. update the live assistant message state to append `plan` and `verification` blocks during streaming
3. add a focused regression test proving those events survive chunked SSE delivery
4. optionally add `event_index` to every backend payload for future resume/debug work

That would let us learn from `claude_code_src` in a BioAPEX-native way without prematurely importing remote-control infrastructure.
