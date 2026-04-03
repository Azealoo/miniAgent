# Harness-First General Agent Slice 3

Date: 2026-04-03

## Goal

Simplify the ordinary chat loop so it behaves more like `ponponon/claude_code_src`:

- no universal per-turn approval replay branch
- no universal compliance-preflight gate ahead of normal answering
- tool execution driven by tool-contract metadata instead of a biology-specific chat fork

## Why this slice

The current runtime already has a `QueryEngine` boundary, but `backend/runtime/query_engine.py` still forces every turn through `compliance_preflight`, and the frontend still keeps a dedicated approval replay path. That keeps the product farther from the reference repo than the remaining helper-agent/runtime differences do.

## Slice scope

### Backend

- `backend/api/chat.py`
- `backend/runtime/chat_runtime.py`
- `backend/runtime/query_engine.py`
- `backend/tools/policy.py`
- `backend/tools/policy_types.py`
- `backend/tools/registry.py`

### Frontend

- `frontend/src/lib/api.ts`
- `frontend/src/lib/store.tsx`
- `frontend/src/components/chat/ChatMessage.tsx`
- any direct callers/tests that still depend on approval replay

## Must do

1. Remove `approval_override` from the ordinary `/api/chat` request path.
2. Remove the backend query-engine preflight branch from ordinary turns so `QueryEngine.run_turn(...)` goes straight into the harness turn path after persistence.
3. Keep tool-policy annotations and tool metadata intact, but stop blocking ordinary execution just because a global preflight did not run.
4. Remove the inline approval replay UI in chat so assistant turns no longer ask the user to re-run the same request under message-scoped approval.
5. Keep the rest of the harness behavior intact:
   - streamed tokens
   - plan/verification helper-agent events
   - session persistence
   - observability/finalization

## Non-goals

- deleting the standalone compliance or evidence-review modules
- redesigning the full frontend shell
- removing inspector/reporting surfaces in this slice
- rewriting the full tool catalog to match Claude Code exactly

## Done when

- ordinary chat requests no longer accept or depend on `approval_override`
- ordinary turns no longer emit `compliance_preflight` tool events before the main agent loop
- execution tools still run under the simplified runtime
- chat UI no longer renders the inline “Proceed with approval” replay affordance
- targeted backend/frontend verification passes
