# Backend Plan Execute Verify Runtime

Date: 2026-04-02
Mode: ultrawork + plan + architect

## Goal

Refactor the backend so the main conversational path is an explicit:

1. planner
2. executor
3. verifier

loop, where the agent:

- decides on a plan before broad tool use
- chooses an ordered tool strategy
- executes against that plan
- verifies whether the result satisfies the request
- can replan or repair when verification fails

## Must-Haves

- planning must be explicit and inspectable, not hidden inside free-form tool calling
- execution must be guided by a structured plan artifact
- verification must be explicit and able to trigger repair or replan
- workflow execution must stop being the center of the main chat path
- current safety policy and tool transparency must be preserved

## Non-Goals

- do not build a hidden swarm of many background agents
- do not remove current tool traces or typed session blocks
- do not rewrite the whole frontend before the backend contract is stable
- do not require separate models for planner/executor/verifier in the first slice

## Target Runtime Contract

### Turn lifecycle

1. `PolicyStage`
2. `PlannerStage`
3. `ExecutorStage`
4. `VerifierStage`
5. `FinalizeStage`

### Planner artifact

Add a structured per-turn plan object, for example:

- `goal`
- `assumptions`
- `constraints`
- `steps[]`
- `success_criteria[]`
- `verification_checks[]`
- `current_step_index`
- `status`
- `revision`

Each step should include:

- `step_id`
- `intent`
- `allowed_tools`
- `preferred_tool_order`
- `exit_criteria`
- `status`

### Executor behavior

- executor consumes the current plan
- executor works one step at a time
- tool use should be explainable as satisfying the active step
- if the executor wants to deviate materially, it must trigger a replan or plan patch

### Verifier behavior

- verifier checks the final answer against the plan's success criteria
- verifier checks whether required evidence or tool outputs were actually obtained
- verifier can return:
  - `pass`
  - `repair_required`
  - `replan_required`

### Loop limits

- allow at most one planned repair loop per turn at first
- allow at most one replan per turn at first
- when limits are hit, return a transparent partial answer with failure reason

## Wave Plan

### Wave 1: Extract runtime boundary without changing behavior

#### Slice 1: Introduce `ChatTurnEngine`

Likely files:

- `backend/api/chat.py`
- `backend/runtime/chat_turn_engine.py`
- `backend/runtime/events.py`
- `backend/tests/test_chat_streaming.py`

Must do:

- move turn orchestration out of the route into a dedicated engine
- keep current SSE event surface stable
- keep current persistence and policy behavior stable

Done when:

- `chat.py` becomes a thin request/SSE adapter
- the engine owns turn state and event emission
- no intentional behavior changes yet

Verify:

- backend chat streaming tests pass
- session persistence tests pass

Depends on:

- none

### Wave 2: Add explicit planning before execution

#### Slice 2: Add planner contract and plan persistence

Likely files:

- `backend/runtime/planner.py`
- `backend/runtime/plan_models.py`
- `backend/runtime/chat_turn_engine.py`
- `backend/tools/registry.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_tools.py`

Must do:

- add structured plan models
- run a planner pass before free tool execution
- persist plan data in typed session blocks
- emit `plan_created` and `plan_updated` events

Done when:

- each eligible turn has a visible plan artifact before tool-heavy execution
- plan steps include allowed tools and preferred order
- the frontend transcript can at least preserve the plan block even if it does not render it richly yet

Verify:

- unit tests for plan model validation
- streaming test proving a plan event is emitted before executor tool calls
- regression test proving simple chit-chat can bypass heavy planning when appropriate

Depends on:

- Slice 1

### Wave 3: Make execution step-aware

#### Slice 3: Step-bound executor loop

Likely files:

- `backend/runtime/executor.py`
- `backend/runtime/chat_turn_engine.py`
- `backend/graph/agent.py`
- `backend/tools/policy.py`
- `backend/tools/registry.py`
- `backend/tests/test_chat_streaming.py`

Must do:

- make executor aware of active plan step
- attach active-step context to the model/tool loop
- track which tools were used for which step
- support controlled plan patch or replan requests

Done when:

- tool use can be traced back to an active plan step
- executor completes or blocks steps explicitly
- major deviations require plan update rather than silent drift

Verify:

- test with a mocked multi-step request showing ordered tool use
- test that off-plan tool use is rejected or forces a plan update
- regression test that existing direct-tool turns still work under step-aware execution

Depends on:

- Slice 2

### Wave 4: Add explicit verification and repair

#### Slice 4: Verifier stage with repair loop

Likely files:

- `backend/runtime/verifier.py`
- `backend/runtime/chat_turn_engine.py`
- `backend/evidence/review_gate.py`
- `backend/tools/evidence_review_tool.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_evidence_review.py`

Must do:

- turn current review logic into a verifier result instead of only a gate
- compare answer/output against plan success criteria
- support `repair_required` and `replan_required`
- run at most one repair loop initially

Done when:

- verification becomes a first-class stage with a typed result
- a failing answer can trigger one transparent repair pass
- biology evidence requirements can be enforced through verifier outcomes rather than route-only branching

Verify:

- test pass case
- test repair-required case
- test replan-required case
- test loop-limit behavior

Depends on:

- Slice 3

### Wave 5: Quarantine workflow-specific routing

#### Slice 5: Remove workflows from the main conversational hot path

Likely files:

- `backend/api/chat.py`
- `backend/runtime/chat_turn_engine.py`
- `backend/workflow_chat.py`
- `backend/tests/test_chat_streaming.py`

Must do:

- stop making `selected_workflow` the main branch inside the default agent turn
- either move workflows to a separate endpoint or expose them as specialized tools
- keep backward compatibility while the frontend transitions

Done when:

- planner/executor/verifier is the primary runtime shape
- workflows no longer dominate the main turn architecture

Verify:

- regression tests for plain chat
- compatibility tests for legacy workflow entry if retained

Depends on:

- Slice 4

## Tool Contract Changes Needed

To support planned execution cleanly, extend the tool manifest with fields like:

- `read_only`
- `destructive`
- `concurrency_safe`
- `interrupt_behavior`
- `planner_hint`
- `verification_relevant`
- `artifact_outputs`
- `validate_input`

This is the part most worth learning from `claude_code_src`'s `Tool.ts`.

## Main Design Choice

Use one model in staged roles first.

- planner prompt
- executor prompt
- verifier prompt

Do not start with separate long-lived planner and verifier agents. Make the behavior explicit first, then split models or agents later if needed.

## Exit Condition For This Phase

This phase is done when:

- a normal turn can produce a structured plan
- execution follows ordered plan steps
- verification can force one repair or replan
- workflows are no longer architecturally central to ordinary chat turns
