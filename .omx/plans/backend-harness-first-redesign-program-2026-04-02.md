# Backend Harness-First Redesign Program

Date: 2026-04-02

## Goal

Reshape the backend around a `claude_code_src`-style harness: one central turn runtime, a richer tool execution contract, and scoped helper agents for planning and verification, while keeping BioAPEX safety, provenance, and session transparency intact.

## Current repo truth

1. Seed work is already present and should be extended, not discarded:
   - `backend/runtime/query_engine.py`
   - `backend/runtime/helper_agent_runner.py`
   - `backend/runtime/model_factory.py`
   - `backend/tools/registry.py`
   - `backend/tools/plan_agent_tool.py`
   - `backend/tools/verification_agent_tool.py`

2. The main remaining architectural debt is still concentrated in `backend/api/chat.py`, which continues to own:
   - turn acceptance and request bookkeeping
   - preflight and evidence-gate orchestration
   - SSE shaping
   - transcript assembly and finalization

3. OMX runtime state still shows `P3 Modern Agent UX` as the active feature with pending frontend reviews, so this rewrite should either:
   - start after that queue is cleared enough to avoid cross-feature ambiguity, or
   - start immediately only with an explicit user override to pivot the active program.

## Structural direction

Copy the reference repo's harness patterns, not its product shell.

- Copy:
  - a central `QueryEngine` / turn-runtime boundary
  - a richer tool contract used directly by the harness
  - helper-agent invocation as a first-class runtime capability
- Do not copy:
  - CLI/TUI product assumptions
  - feature-flag sprawl
  - hidden mandatory swarms

## Non-goals for this program

- Do not rewrite the session store format in the same program.
- Do not add a large new frontend feature before the backend runtime contract is stable.
- Do not remove safety/compliance/evidence policy gates just to mimic the reference repo.

## Program slices

### Slice 1: Turn runtime owns the lifecycle

Files likely touched:
- `backend/api/chat.py`
- `backend/runtime/query_engine.py`
- `backend/runtime/__init__.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`

Must do:
- Move turn acceptance, early user-message persistence, protocol/workflow compatibility dispatch, preflight/evidence gate orchestration, and final `turn_status` ownership behind the runtime boundary.
- Keep the HTTP route focused on request validation plus SSE transport.
- Persist accepted user turns before the long-running model/tool loop begins.

Done when:
- `backend/api/chat.py` becomes materially thinner.
- The runtime, not the route, decides the main turn path.
- Mid-turn failures still leave the user turn persisted.

### Slice 2: Tool contract becomes harness contract

Files likely touched:
- `backend/tools/registry.py`
- `backend/tools/policy.py`
- `backend/tools/policy_wrappers.py`
- `backend/runtime/helper_agent_runner.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_tool_policy.py`

Must do:
- Extend tool manifests beyond coarse policy metadata.
- Add harness-facing semantics such as interrupt behavior, validation hooks, user-facing activity/result summaries, and helper-agent exposure rules.
- Make helper agents consume the same execution contract the executor uses.

Done when:
- Planner/verifier prompts can rely on manifest semantics instead of ad-hoc heuristics.
- Tool policy annotations survive helper-agent integration.

### Slice 3: Explicit planning and verification events

Files likely touched:
- `backend/runtime/query_engine.py`
- `backend/graph/agent.py`
- `backend/tools/plan_agent_tool.py`
- `backend/tools/verification_agent_tool.py`
- `backend/graph/session_manager.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_session_manager.py`

Must do:
- Add additive runtime outputs: `plan_created`, `plan_updated`, and `verification_result`.
- Persist typed `plan` and `verification` transcript blocks.
- Keep existing `token`, `tool_*`, `workflow_*`, and `done` compatibility during migration.

Done when:
- The runtime can expose planning/verifier artifacts without breaking current clients.
- Session history round-trips the new blocks cleanly.

### Slice 4: Plan-execute-verify loop and workflow demotion

Files likely touched:
- `backend/runtime/query_engine.py`
- `backend/graph/agent.py`
- `backend/tools/plan_agent_tool.py`
- `backend/tools/verification_agent_tool.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_runtime_query_engine.py`

Must do:
- Let the executor deliberately call the planner and verifier within the harness loop.
- Allow one controlled repair/replan cycle.
- Keep workflow routing behind a compatibility adapter so default chat is no longer workflow-first.

Done when:
- Normal chat follows a harness-first path.
- Planner and verifier are additive helpers, not route-local hacks.
- Workflow-specific routing is no longer the center of ordinary chat control flow.

## Verification principle

Every slice must keep backend and frontend compiling, preserve current session-history compatibility for legacy turns, and leave a durable OMX verification note before the next slice starts.

## Start gate

Default recommendation: begin execution after the active `P3 Modern Agent UX` review queue is cleared enough to avoid mixing a backend rewrite into a still-open frontend program.

If the user explicitly chooses to pivot now, treat this backend redesign as the new active program and proceed in team mode with that override recorded in the runtime artifacts.
