# Backend Plan Execute Verify Runtime Verification

Date: 2026-04-02
Phase: backend-plan-execute-verify-runtime

## Verification Map

### Slice 1

- Run backend chat streaming regression tests covering normal turns, blocked turns, and tool traces.
- Confirm SSE event ordering is unchanged for legacy behavior.
- Confirm session history still persists user and assistant messages correctly.

### Slice 2

- Add planner unit tests for:
  - valid plan generation
  - invalid plan rejection
  - planning bypass for trivial turns
- Add streaming test proving `plan_created` occurs before execution-phase tool calls.

### Slice 3

- Add executor tests for:
  - step progression
  - off-plan deviation handling
  - controlled replan request
- Add chat integration test proving tool order follows the active plan.

### Slice 4

- Add verifier tests for:
  - passing verification
  - repair-required outcome
  - replan-required outcome
  - loop-limit exhaustion
- For biology-answer turns, confirm evidence-dependent verification still behaves safely.

### Slice 5

- Add regression tests showing ordinary chat no longer branches through workflow-specific routing.
- If workflow compatibility remains, add dedicated tests proving the compatibility adapter still works.

## Done Criteria

- the plan artifact is visible in persisted turn data
- executor tool use can be mapped to plan steps
- verifier outcomes are persisted and inspectable
- one controlled repair loop works end to end
- backend tests cover the new runtime stages directly instead of only route-level behavior
