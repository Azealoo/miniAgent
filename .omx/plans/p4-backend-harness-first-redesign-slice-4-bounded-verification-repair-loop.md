# P4 Slice 4 Bounded Verification Repair Loop

Date: 2026-04-02

## Goal

Make planner/verifier artifacts operational by letting the harness run one bounded repair pass when the latest verifier verdict is `repair_required` or `fail`, using the saved plan and verifier findings to guide a second executor attempt.

## Scope

This slice is limited to turn-level repair orchestration in the harness runtime. It does not force planner/verifier use on every turn, does not add replanning, and does not add new frontend UX beyond preserving compatibility with the existing transcript surfaces.

## Files

- `backend/runtime/query_engine.py`
- `backend/graph/agent.py`
- `backend/api/chat.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `context/current-feature.md`

## Must Do

1. Track the latest helper-agent artifacts produced during an executor pass:
   - latest `plan_created` / `plan_updated`
   - latest `verification_result`
   - latest streamed assistant draft content for the pass
2. When the first executor pass ends and the latest verifier verdict is `repair_required` or `fail`, do not finalize immediately:
   - emit `new_response`
   - start one repair pass through the same runtime
   - preserve the first pass transcript instead of hiding it
3. Build explicit repair context for the second pass from:
   - the original user task
   - the latest plan artifact, if present
   - the latest verifier summary, issues, and repair instructions
   - the first-pass draft answer
4. Keep the repair loop bounded:
   - maximum one repair retry
   - if the second pass still ends non-pass or does not improve, finalize without a third pass
5. Keep the route transport-focused and preserve current transcript/session compatibility:
   - existing tool traces still round-trip
   - existing `done` / `new_response` behavior remains additive
   - no hidden background worker or unbounded swarm behavior is introduced

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- optional confidence sweep after landing:
  - `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest -q`

## Exit Conditions

- a non-pass verifier verdict can trigger one runtime-managed repair retry
- the repair pass receives explicit plan + verifier + prior-draft context
- no more than one repair retry can happen in a turn
- first-pass and repair-pass transcript artifacts both remain visible and auditable
- existing session history and SSE consumers remain compatible
