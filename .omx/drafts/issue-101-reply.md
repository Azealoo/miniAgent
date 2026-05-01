<!-- Draft reply for Azealoo/miniAgent#101 -->
<!-- URL: https://github.com/Azealoo/miniAgent/issues/101 -->
<!-- Review and adjust before posting. This was NOT auto-posted. -->

Happy to pick this up. Two blockers before I can start, then a concrete design I'd land unless you push back.

**Blockers**

1. **What is A3?** The issue says "Requires A3" but A3 is not defined in this repo, in `.omx/`, or in the open issue list. Prerequisite issue/PR number, a design doc, or a rollout gate?
2. **Buffer bound.** Acceptance says "Resume window is bounded" without units. Proposing `(N events OR M bytes OR T seconds post-completion, whichever hits first)` with defaults `N=512, M=512 KiB, T=120 s`. Fine to pick different numbers — just need a cap.

**Verified on `claude/draft-github-reply-FIILF` (HEAD `5cf97b2`)**

- `api.ts:1205–1211` in the issue body is stale. `frontend/src/lib/api.ts` is 470 lines; the "stream closed before completion" fallback is at `frontend/src/lib/api.ts:459-465`.
- Server-side plumbing for addressable events already exists: `backend/runtime/query_engine.py::stream_turn_sse` mints `request_id` at line 554 and stamps a monotonic `event_index` on every envelope at lines 584-591 (`_sse` closure). `session_id` is in scope on the same call (line 498) so a resume handshake can bind both. No buffer, resume endpoint, or reconnect path exists yet.

**Proposed design (file-first, framework-light, per CLAUDE.md)**

- *Transport:* reuse `POST /api/chat` with a `Last-Event-ID: <event_index>` header plus a `resume_request_id` body field. Avoids a new endpoint and keeps the hand-parsed SSE path in `frontend/src/lib/api.ts` unchanged.
- *Buffer:* in-memory `dict[request_id, deque[Envelope]]` attached to the `_sse` closure in `stream_turn_sse`. Evicted when any cap hits or on session teardown. No DB, no new service.
- *Scope:* resume requires matching `(request_id, session_id)`. Cross-session replay is rejected.
- *Turn lifecycle on drop:* server-side turn continues to completion regardless of client presence — avoids losing verifier/artifact side effects. On reconnect, the server replays buffered events after `Last-Event-ID`, then either tails the live stream if the turn is still in flight or closes with the already-emitted `done`/`error` if it finished.
- *Client:* on stream close before a terminal event, `frontend/src/lib/api.ts` reconnects with exponential backoff (250 ms → 4 s, max 4 attempts) sending `Last-Event-ID`. The existing "stream closed before completion" error remains as the final fallback.

Files most likely to change: `backend/runtime/query_engine.py`, `backend/api/chat.py`, `frontend/src/lib/api.ts`, `frontend/src/lib/chat-stream-reducer.ts`. Tests land under `backend/tests/` (buffer + resume handshake, cross-session rejection, cap eviction) and `frontend/src/test/` (reconnect reducer path, terminal-after-replay, attempt exhaustion).
