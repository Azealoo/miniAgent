# Harness-First General Agent Slice 2

Date: 2026-04-02

## Goal

Strengthen the `QueryEngine` boundary so ordinary chat routing depends less on `backend/api/chat.py` and more on a reusable runtime object, in the style of `claude_code_src`.

## Landed changes

1. `backend/runtime/query_engine.py` now owns a unified turn dispatcher with:
   - protocol-request routing
   - selected-workflow routing
   - normal agent-stream routing

2. The runtime now emits a consistent `turn_status` field on `done` events so the route can finalize turns without mode-specific branching.

3. `backend/api/chat.py` now consumes `QueryEngine` turn events with the post-gate path going through `submit_turn(...)` instead of directly owning workflow/agent dispatch details.

4. Added runtime routing coverage in `backend/tests/test_runtime_query_engine.py`.

5. Fixed the package boundary in `backend/runtime/__init__.py` so helper-agent imports do not create a circular import through `query_engine.py`.

## Notes

- This slice keeps the current protocol and workflow behavior intact.
- The route still owns preflight, evidence-gate, SSE shaping, persistence, and observability.
- The next structural step would be reducing the remaining pre-gate branching in `backend/api/chat.py`.
