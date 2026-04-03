# Backend Harness Leverage Follow-Up

Date: 2026-04-02
Mode: ultrawork + research

## Question

After the latest backend cleanup, what parts of BioAPEX's harness are now strong enough to leverage harder, and what still looks under-leveraged?

## Repo Truth

- The backend is now intentionally chat-engine-only at the app surface: `backend/app.py` registers only `chat`, `access`, `sessions`, and `files`.
- `backend/runtime/query_engine.py` is now the ordinary chat runtime center for accepted turns: it owns compliance preflight, evidence gating, the harness loop, helper-agent event extraction, and runtime-managed repair retry.
- `backend/runtime/turn_ledger.py` now owns assistant segment assembly and final turn shape, including typed `blocks` for text, tools, retrievals, plans, and verification.
- `backend/api/sessions.py` keeps `/api/sessions/workflows/summary` only as an empty compatibility stub.
- `backend/runtime_config.py` introduces layered runtime config (`defaults`, `user`, `project`, `local`) with provenance available through `config.get_runtime_config_provenance()`.
- `backend/tools/policy.py`, `backend/tools/registry.py`, and `backend/runtime/helper_agent_runner.py` now share a richer manifest and policy surface for access scope, evidence requirements, helper-agent exposure, summary hints, and interrupt metadata.
- `backend/tools/python_repl_tool.py` no longer shares one process-global interpreter state across all chats; it now keys runtime state by session id.

## Best Leverage Points

### 1. Treat `QueryEngine` as the only ordinary-turn contract

This is the strongest cleanup win.

- Add future turn-level behavior in `backend/runtime/query_engine.py` first.
- Keep compatibility branches out of `backend/api/chat.py` unless they are truly transport-only.
- Use `QueryTurnInput` as the place where new turn-wide runtime inputs land.

### 2. Build on `TurnLedger` as the persisted transcript boundary

`backend/runtime/turn_ledger.py` is now the best place to add any new persisted artifact block or turn-level summary.

- If you add new helper artifacts, add them as typed blocks here.
- If you want frontend detail views to stay stable, keep `blocks` authoritative and derive compatibility shapes from them.

### 3. Use layered runtime config as the deployment/profile seam

`backend/runtime_config.py` is currently stronger than the public product surface that uses it.

- It can already support local vs project vs user overrides cleanly.
- The immediate leverage is to expose or log `config.get_runtime_config_provenance()` for inspection and support.
- The next leverage step is to move backend mode toggles and hosted-safe defaults behind named config layers instead of ad hoc env assumptions.

### 4. Lean harder on the manifest-plus-policy contract

The combination of `backend/tools/registry.py`, `backend/tools/policy.py`, and `backend/runtime/helper_agent_runner.py` is now a real harness asset.

- Planner and verifier tool catalogs can stay derived from the same manifest.
- Future interrupt, budgeting, and UI explanation work should reuse manifest metadata instead of inventing route-local logic.
- This is the closest BioAPEX currently gets to the richer `Tool.ts` direction from the reference repo.

### 5. Reuse the session-scoped REPL pattern for other stateful tools

`backend/tools/python_repl_tool.py` now has the right pattern:

- session-derived runtime state
- explicit cleanup hook
- policy-context-based session resolution

If you add other stateful tools later, copy this shape instead of adding more singleton mutable state.

### 6. Keep the lightweight backend health suite as the contract gate

`backend/tests/test_chat_engine_health.py` is a good minimal guardrail for the reduced backend surface.

- Expand this suite only around routes and modules the product still intends to keep.
- Let heavier behavior stay in runtime/tool tests.

## Under-Leveraged Seams

### 1. `backend/api/chat.py` is thinner, but still acts like a second orchestrator

It still owns SSE shaping, pending tool bookkeeping, audit emission, turn persistence, background title generation, and observability.

That means the runtime center of gravity is improved, but not yet singular.

### 2. Runtime config provenance exists, but nothing operational seems to consume it

The layering is useful, but today it mostly helps tests and internal loading.

The obvious next use is a read-only admin/inspection view or startup diagnostics so operators can see what layers are actually active.

### 3. Helper agents are still special-cased to planner and verifier

The harness can run scoped agents, but the exposure model is still effectively hard-coded around two roles.

If BioAPEX later adds exploration, repair, or summarization helpers, it should generalize the same runner rather than cloning new pathways.

### 4. Session runtime ownership is still partly tool-by-tool

`backend/graph/agent.py` still owns one process-wide tool list and clears session runtime by asking each tool whether it has `clear_session_state`.

That is much safer now that REPL state is session-scoped, but it is still not a true harness-owned session runtime store.

## Recommendation

Leverage what is already strong before starting another big refactor.

Priority order:

1. Keep all new ordinary-turn behavior inside `QueryEngine` and `TurnLedger`.
2. Expose runtime-config provenance somewhere inspectable.
3. Push more interrupt/budget/UI behavior to manifest-driven policy semantics.
4. Only then revisit `backend/api/chat.py` and helper-agent generalization.

## Key File Anchors

- `backend/app.py`
- `backend/runtime/query_engine.py`
- `backend/runtime/turn_ledger.py`
- `backend/api/chat.py`
- `backend/api/sessions.py`
- `backend/runtime_config.py`
- `backend/config.py`
- `backend/tools/policy.py`
- `backend/tools/registry.py`
- `backend/runtime/helper_agent_runner.py`
- `backend/tools/python_repl_tool.py`
- `backend/tests/test_chat_engine_health.py`
