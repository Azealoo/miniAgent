# P0 Stabilize Trust - Slice 1 - Verification

## Required Test Coverage Added In The Slice

- backend import-safety regression proving exact tokenizer resolution is not attempted during `api.tokens` import
- backend fallback regression for `session_tokens` proving counts still return with:
  - `tokenizer_backend = "deterministic_fallback"`
  - `tokenizer_accuracy = "approximate"`
- backend fallback regression for `files_tokens` proving allowed files still count while whitelist and secret blocking stay intact

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok or session_tokens or files_tokens'`
Purpose: cover normal app import plus the token endpoint regressions.

2. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
Purpose: confirm the additive token metadata fields are represented in frontend types and API validation.

3. `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/test/app-shell.contract.test.tsx`
Purpose: keep the existing Usage-tab contract coverage green after the token response shape expands.

## Exit Criteria

- all three commands pass
- no import-time tokenizer initialization remains in the backend token path
- fallback counting is explicit and honest in the returned contract, even before the Usage UI copy is updated
