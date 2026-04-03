# P4 Slice 2 Tool Contract Becomes Harness Contract

Date: 2026-04-02

## Goal

Promote the tool manifest from coarse policy metadata into the execution contract that the BioAPEX harness, planner, and verifier all rely on directly.

## Scope

This slice is limited to manifest semantics, policy-wrapper propagation, and helper-agent tool cataloging. It does not yet add planner/verifier SSE events or the repair loop.

## Files

- `backend/tools/registry.py`
- `backend/tools/policy.py`
- `backend/tools/policy_wrappers.py`
- `backend/runtime/helper_agent_runner.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_tool_policy.py`
- `context/current-feature.md`

## Must Do

1. Extend the manifest with harness-facing semantics beyond access/evidence/compliance flags.
2. Include explicit contract fields for:
   - interrupt behavior
   - whether the tool validates its own input
   - user-facing activity summary guidance
   - user-facing result summary guidance
   - helper-agent exposure behavior
3. Make helper-agent catalog output use those richer manifest fields.
4. Preserve policy annotation behavior for wrapped tools.
5. Add focused tests proving the richer manifest is typed, propagated, and visible to helper agents.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tools.py tests/test_tool_policy.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`

## Exit Conditions

- manifests encode the new harness-facing semantics
- helper-agent catalog output reflects the richer contract
- policy-wrapped tools still behave and annotate correctly
- focused backend tests and frontend typecheck stay green

## Execution Note

Slice 2 is now implemented.

- `backend/tools/registry.py` now encodes interrupt behavior, input-validation presence, and user-facing activity/result summary hints in the tool manifest.
- `backend/tools/policy.py` now propagates the manifest contract into wrapped-tool result metadata so downstream runtime consumers can inspect the same semantics the harness uses.
- `backend/runtime/helper_agent_runner.py` now exposes the richer contract fields in planner/verifier tool catalogs.
- Focused contract tests, frontend typecheck, and a full backend suite rerun all passed.
