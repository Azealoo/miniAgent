# P4 Backend Harness-First Redesign

Date: 2026-04-02

## Goal

Recenter BioAPEX ordinary chat around a harness-first runtime modeled after the strongest backend ideas in `ponponon/claude_code_src`: a central query engine, a rich tool execution contract, and scoped helper agents for planning and verification.

## Why This Phase Comes Next

- The current branch already contains seed work for a `QueryEngine`, runtime helper-agent support, and richer tool manifests.
- The user explicitly chose to pivot now and treat the backend redesign as the active program.
- BioAPEX still needs to preserve its own identity: scientific, file-first, auditable, and safety-gated rather than a hidden autonomous swarm.

## Phase Rules

1. Copy the runtime boundary and tool-contract ideas from the reference repo, not its CLI/TUI product surface.
2. Keep the main chat route thin and transport-focused.
3. Preserve safety, provenance, and explicit session artifacts through every slice.
4. Land one backend slice at a time with explicit verification and review.
5. Keep workflow compatibility during migration, but do not let workflow-first routing stay the center of ordinary chat.

## Slice 1 - Turn Runtime Lifecycle

### Why This Slice Comes First

- `backend/api/chat.py` still owns too much of the conversation lifecycle.
- The strongest reference-repo lesson is to make a central runtime own the turn, not the route.
- Planner/verifier loops will stay awkward until the runtime boundary is authoritative.

### Files Likely To Change

- `backend/api/chat.py`
- `backend/runtime/query_engine.py`
- `backend/runtime/__init__.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- optional supporting changes:
  - `backend/graph/session_manager.py`

### Slice Must Do

1. Move more of the accepted-turn lifecycle behind the runtime boundary:
   - early user-message persistence
   - compliance/evidence gate orchestration ownership
   - post-gate dispatch ownership
   - final `turn_status` normalization
2. Keep `/api/chat` focused on:
   - request validation
   - SSE serialization
   - observability and final response transport
3. Keep compatibility with current session history and SSE consumers.
4. Preserve workflow/protocol behavior behind compatibility adapters instead of route-local branching.

### Done Means

- the route is materially thinner
- the runtime owns the main turn path
- interrupted turns still keep the accepted user message
- current frontend/backend streaming contracts still compile and pass
