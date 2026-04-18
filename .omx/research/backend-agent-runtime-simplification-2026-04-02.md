# Backend Agent Runtime Simplification

Date: 2026-04-02
Mode: ultrawork + architect

## Goal

Refocus BioAPEX from a workflow-first backend into a general-purpose tool-using agent that can:

- respond broadly to arbitrary user requests
- explicitly plan, execute, and verify
- keep tool use transparent
- preserve safety without making workflows the center of the runtime

## Current Shape

The current backend logic is coherent, but the center of gravity is still in the chat route:

- `backend/api/chat.py` orchestrates compliance preflight, protocol routing, evidence review gate, workflow execution, normal agent streaming, transcript assembly, and finalization.
- `backend/graph/agent.py` owns one main agent runtime and rebuilds the prompt per request.
- `backend/workflow_chat.py` and `backend/workflow_runner.py` are still first-class branches of the conversational path.

This works, but it is not the cleanest shape for a general-purpose planner/executor/verifier agent.

## What To Learn From `claude_code_src`

The strongest ideas to borrow are structural:

1. A central conversation runtime
   - `src/QueryEngine.ts` owns per-conversation state and the turn lifecycle.
   - The API or UI layer stays thinner.

2. A richer tool contract
   - `src/Tool.ts` gives tools stronger runtime semantics than a simple registry.
   - Important metadata includes validation, read-only vs destructive behavior, concurrency safety, interrupt behavior, and summarization/display hooks.

3. Optional specialized agents layered on top
   - Planner/verifier behavior should be added as explicit scoped workers or stages, not hidden branches spread through the HTTP layer.

## Recommended Target Shape

### 1. Make chat a thin transport layer

Move almost all turn logic out of `backend/api/chat.py` into a dedicated engine such as:

- `backend/runtime/chat_turn_engine.py`

That engine should own:

- input normalization
- risk/policy evaluation
- planner stage
- executor stage
- verifier stage
- persistence/finalization

`chat.py` should mostly:

- validate request/auth
- load session identity
- call the turn engine
- stream engine events to SSE

### 2. Remove workflow execution from the main conversational hot path

For the general-purpose agent product:

- selected workflows should not be a first-class branch in the main turn engine
- protocol execution should not be a dedicated shortcut in the main chat path

If workflows remain in the repo, move them behind:

- a separate endpoint
- or a dedicated tool family callable by the planner/executor

This keeps the main runtime simple:

- user request
- plan
- execute with tools
- verify
- finalize

### 3. Replace ad hoc gates with explicit stages

Instead of:

- compliance preflight
- evidence review gate
- workflow branch
- normal agent branch

Use a staged runtime like:

1. `TurnPolicyStage`
2. `PlannerStage`
3. `ExecutorStage`
4. `VerifierStage`
5. `FinalizeStage`

This keeps behavior explicit while making the logic easier to test and reason about.

### 4. Treat planner and verifier as first-class runtime components

Add explicit structured components:

- `backend/runtime/planner.py`
- `backend/runtime/executor.py`
- `backend/runtime/verifier.py`

Planner responsibilities:

- classify the request
- decide whether tools are needed
- produce a short structured plan
- choose tool strategy

Executor responsibilities:

- run the main tool-using loop
- emit tool events
- track execution artifacts

Verifier responsibilities:

- check whether the answer satisfies the request
- detect unsupported claims or missing evidence
- request one retry or one repair loop when needed

This is cleaner than burying verification logic inside the route or relying only on tool policy.

### 5. Upgrade the tool registry into a real tool contract

The current registry is useful but too thin for the target runtime.

Add fields like:

- `is_read_only`
- `is_destructive`
- `is_concurrency_safe`
- `interrupt_behavior`
- `validate_input`
- `summarize_use`
- `summarize_result`
- `open_world`
- `requires_verification`

This follows the spirit of `claude_code_src/src/Tool.ts` and makes planning/verifying much easier.

### 6. Keep persistence file-first, but change the write pattern

The current session manager rereads and rewrites full JSON sessions too often.

Prefer:

- append-only message/event log
- periodic compacted session snapshot
- derived summaries/indexes written separately

This preserves transparency and makes replay/resume easier while avoiding repeated whole-file rewrites.

### 7. Persist accepted user turns before the model loop

Borrow this behavior from `QueryEngine.ts`:

- once a user turn is accepted, persist it immediately
- do not wait for the assistant response to finish before writing durable state

This improves resumability and avoids losing turns when execution stops mid-stream.

## Proposed Runtime Modules

- `backend/api/chat.py`
  - thin SSE adapter only
- `backend/runtime/chat_turn_engine.py`
  - canonical turn lifecycle
- `backend/runtime/turn_context.py`
  - request/session/tool/model context
- `backend/runtime/policy_stage.py`
  - risk and permission evaluation
- `backend/runtime/planner.py`
  - structured plan generation
- `backend/runtime/executor.py`
  - model + tool loop
- `backend/runtime/verifier.py`
  - answer verification and retry policy
- `backend/runtime/tool_catalog.py`
  - rich tool manifest + lookup
- `backend/runtime/session_store.py`
  - append log + snapshots
- `backend/runtime/events.py`
  - typed runtime events for SSE and persistence

## Recommended Migration Order

1. Extract `ChatTurnEngine` without changing behavior.
2. Move workflow and protocol routing out of the main chat turn path.
3. Introduce explicit planner/executor/verifier stages.
4. Enrich the tool contract.
5. Replace full-session rewrites with append log + snapshot persistence.

## Verdict

For the new product goal, the cleanest backend is:

- one conversation engine
- one tool catalog with strong semantics
- one staged plan/execute/verify lifecycle
- workflows as optional tools or separate endpoints, not core routing branches

That is the main lesson worth borrowing from `claude_code_src`.
