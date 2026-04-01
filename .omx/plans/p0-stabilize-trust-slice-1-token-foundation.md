# P0 Stabilize Trust - Slice 1 - Token Foundation

## Goal

Deliver the backend trust fix that removes import-time tokenizer initialization, keeps token counting functional offline through a deterministic fallback, and publishes additive accuracy metadata without changing the Usage UI copy yet.

## Why This Slice Comes First

- `backend/api/tokens.py` currently resolves `tiktoken` at import time.
- `backend/app.py` imports the token router during app import, so the current failure mode can break backend tests before any request is handled.
- The exact-vs-approximate UI labeling depends on backend metadata that does not exist yet.

## Files Likely To Change

- `backend/api/tokens.py`
- `backend/tests/test_api_health.py`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/test/fixtures.ts`
- optional new backend helper for lazy token counting if extracting the resolver keeps `api.tokens` thin

## Slice Must Do

1. Replace module-level exact tokenizer initialization with a lazy resolver that does not run during `api.tokens` import.
2. Add a deterministic local fallback tokenizer path that returns stable counts when exact tokenizer resolution is unavailable.
3. Keep both `/api/tokens/session/{session_id}` and `/api/tokens/files` functional in exact and fallback modes without weakening existing auth or path-guard behavior.
4. Add additive token metadata to the session usage response:
   - `tokenizer_backend`
   - `tokenizer_accuracy`
5. Align frontend token types and fixtures with the additive response contract so the later Usage-tab honesty work can land without another contract change.
6. Add regression coverage for import safety and fallback token counting.

## Non-Goals In This Slice

- Usage-tab copy or badge changes in `frontend/src/components/editor/InspectorPanel.tsx`
- `.next-e2e-build` ignore cleanup
- human-facing `miniOpenClaw`/`Claw` to `BioAPEX` naming cleanup

## Done Means

- importing `api.tokens` no longer resolves the exact tokenizer at module load
- importing `backend/app.py` stays safe when exact tokenizer resolution is unavailable
- session token responses still return counts and now include exact-vs-fallback metadata
- files token counting still returns counts in fallback mode and preserves whitelist/secret blocking
- backend token regressions and frontend contract verification pass

## Dependencies

- none; this slice should unblock the later Usage-tab honesty slice

## Follow-On Slice

P0 slice 2 should update the Usage UI to label exact vs approximate counts honestly using the new backend metadata, plus any related e2e/browser assertions.
