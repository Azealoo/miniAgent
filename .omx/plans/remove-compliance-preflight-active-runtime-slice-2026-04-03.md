# Remove Compliance Preflight Active Runtime Slice

Date: 2026-04-03

## Goal

Make the agent runtime feel more like `claude_code_src` by removing compliance-preflight as an active runtime/tool-policy concept instead of merely skipping it in the ordinary `/api/chat` path.

## Scope

- `backend/tools/policy.py`
- `backend/tools/policy_types.py`
- `backend/tools/registry.py`
- targeted backend tests that still assert `compliance_preflight_required`
- generic frontend stream fixtures/tests that still use `compliance_preflight` as the canonical tool event
- generic chat activity copy that still special-cases `compliance_preflight`

## Must do

1. Remove `compliance_preflight_required` from the active tool manifest/policy contract.
2. Stop carrying compliance preflight state in `ToolPolicyExecutionContext` and result annotations.
3. Keep access-scope enforcement and contract metadata intact.
4. Update generic frontend stream tests/fixtures so ordinary tool activity is modeled with a normal tool such as `read_file`.
5. Preserve legacy compliance-report artifact rendering support for historical sessions in this slice.

## Non-goals

- deleting every historical compliance artifact or report surface
- rewriting study dossier compliance views
- removing evidence review tooling in the same slice

## Verify

- backend targeted pytest for runtime policy/registry/chat loop paths
- frontend targeted vitest for stream parsing, reducer behavior, and app-shell contract flow
