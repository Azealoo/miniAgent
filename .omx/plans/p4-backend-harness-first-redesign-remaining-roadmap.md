# P4 Backend Harness-First Redesign Remaining Roadmap

Date: 2026-04-02

## Goal

Finish `P4 Backend Harness-First Redesign` in the fewest slices that still keep the work explicit, verifiable, and aligned with the strongest structural lessons from `ponponon/claude_code_src`.

## Current Program Truth

- Slice 1 is complete: the runtime owns accepted-turn persistence signaling, preflight/evidence gate orchestration, and post-gate dispatch.
- Slice 2 is complete: the tool manifest is now a richer harness contract.
- Slice 3 is complete: helper-agent artifacts stream and persist as typed `plan` / `verification` blocks.
- Slice 4 is already planned but not yet implemented: one bounded verifier-driven repair retry.

## Locked Remaining Slices

### Slice 4: Bounded verification repair loop

Reference plan:
- `.omx/plans/p4-backend-harness-first-redesign-slice-4-bounded-verification-repair-loop.md`

Why it stays next:
- The runtime already emits verifier artifacts, but they are still decorative unless they can alter control flow.
- This is the smallest slice that makes planning/verification operational without introducing hidden swarms or unbounded retries.

### Slice 5: Runtime turn ledger and finalization

Reference plan:
- `.omx/plans/p4-backend-harness-first-redesign-slice-5-runtime-turn-ledger-and-finalization.md`

Why it comes after Slice 4:
- The bounded repair loop creates the real multi-pass behavior the runtime must preserve.
- Once repair exists, transcript assembly and assistant-turn persistence should move behind the runtime boundary instead of staying route-local in `backend/api/chat.py`.

### Slice 6: Legacy workflow/protocol quarantine

Reference plan:
- `.omx/plans/p4-backend-harness-first-redesign-slice-6-legacy-dispatch-quarantine.md`

Why it comes last:
- Workflow/protocol demotion is safest after the runtime already owns the ordinary harness loop and multi-pass transcript/finalization behavior.
- This slice should finish the architectural shift so default chat is unmistakably harness-first rather than branch-heavy.

## Why This Is The Right Endgame

This sequence finishes the phase without introducing extra speculative infrastructure:

1. make verifier output actionable
2. move turn assembly/finalization where the harness belongs
3. move legacy workflow/protocol behavior out of the ordinary chat hot path

That matches the reference-repo lesson more closely than adding more route-local logic or prematurely rewriting persistence/storage.

## Phase Exit Condition

`P4 Backend Harness-First Redesign` is done when:

- the runtime can run one bounded repair retry after a non-pass verifier result
- `backend/runtime/query_engine.py` owns ordinary-chat pass orchestration plus transcript/finalization inputs
- `backend/api/chat.py` is reduced to validation plus SSE serialization and light transport glue
- workflow/protocol compatibility no longer dominates the default chat path
- current session blocks, legacy `tool_calls` / `workflow_events`, and existing frontend consumers still round-trip

## Explicit Non-Goals For The Remaining Program

- do not rewrite the JSON session store into append-log/snapshot storage in P4
- do not add a large frontend redesign before the backend contract is settled
- do not remove safety/compliance/evidence gates in the name of mimicry
- do not make planner/verifier mandatory hidden subagents for every turn
