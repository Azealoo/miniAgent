# P0 Stabilize Trust - Slice 2 - Usage Honesty UI

## Goal

Make the Usage inspector tell the truth about token precision by surfacing exact-vs-approximate status from the new backend metadata, without reopening backend token logic or folding in unrelated cleanup.

## Why This Slice Comes Next

- P0 acceptance is still incomplete until the UI distinguishes exact vs approximate counts.
- Slice 1 already landed the additive `tokenizer_backend` and `tokenizer_accuracy` contract needed for this surface.
- This is the highest-leverage remaining P0 item because it closes the trust gap at the point scientists actually read token usage.

## Files Likely To Change

- `frontend/src/components/editor/InspectorPanel.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `frontend/e2e/app-shell.e2e.spec.ts`
- optional `frontend/src/test/fixtures.ts` only if a dedicated approximate-usage fixture improves clarity

## Slice Must Do

1. Update the Usage tab so exact counts are labeled as model-aligned or exact in a compact, always-visible way.
2. Update the Usage tab so fallback counts are labeled as approximate and clearly tied to the local deterministic fallback tokenizer.
3. Keep the current Usage layout compact and screenshot-aligned; do not turn the panel into a verbose explainer.
4. Preserve the existing no-session, loading, error, streaming, and no-context-window states.
5. Add focused frontend assertions for both exact and approximate usage payloads so the honesty labels are covered in contract and browser-level flows.

## Non-Goals In This Slice

- backend token counting changes in `backend/api/tokens.py`
- `.next-e2e-build` ignore cleanup
- human-facing `miniOpenClaw`/`Claw` to `BioAPEX` naming cleanup

## Done Means

- the Usage tab visibly distinguishes exact/model-aligned counts from approximate/fallback counts
- approximate counts no longer read like exact model-token totals
- exact counts keep a concise provenance cue instead of silently implying precision
- existing Usage states still behave as before outside the new honesty cue
- targeted frontend contract and browser checks pass

## Dependencies

- depends on completed P0 slice 1 token metadata (`tokenizer_backend`, `tokenizer_accuracy`)

## Serial Or Parallel

This slice should remain serial.

Why:
- it directly consumes slice 1 metadata and closes the main remaining P0 acceptance gap
- it touches one concentrated frontend surface plus its tests
- parallelizing `.next-e2e-build` cleanup or naming cleanup would add coordination overhead without increasing trust value for the next landing

## Follow-On Slice

The remaining P0 cleanup after this should be a small final serial slice for `.next-e2e-build` ignore hygiene and the human-facing BioAPEX naming cleanup.
