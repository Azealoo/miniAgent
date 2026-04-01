# P0 Stabilize Trust - Slice 4 - Human-Facing BioAPEX Naming Cleanup

## Goal

Finish P0 by replacing the remaining user-facing `miniOpenClaw` / `Claw` branding in docs and prompt-facing identity copy with `BioAPEX`, while explicitly preserving machine-facing compatibility points such as the health payload, package names, and fetch-tool user agent.

## Why This Final Slice Is Narrow

- The remaining naming drift is concentrated in two human-facing surfaces: the top-level README and the assistant identity prompt.
- The remaining legacy names in `backend/app.py`, `frontend/package.json`, `frontend/package-lock.json`, and `backend/tools/fetch_url_tool.py` are compatibility-sensitive machine-facing identifiers or protocol-adjacent values.
- Keeping this slice to docs and prompt copy closes the visible naming drift without risking silent contract changes.

## Exact Files / Prompts / Docs To Touch

- `README.md`
- `backend/workspace/IDENTITY.md`

## Protected Compatibility Surfaces (Do Not Change In This Slice)

- `backend/app.py`
  Keep `health()` returning `{"status": "ok", "service": "miniOpenClaw"}`.
  Keep FastAPI app metadata unchanged in this slice to avoid altering machine-consumed OpenAPI info.
- `frontend/package.json`
- `frontend/package-lock.json`
  Keep the package name `mini-openclaw-frontend` unchanged.
- `backend/tools/fetch_url_tool.py`
  Keep the existing `miniOpenClaw/1.0` user-agent unchanged.
- `backend/tests/test_api_health.py`
- `backend/tests/test_tools.py`
  Existing compatibility assertions remain the guardrails; do not rewrite them to a new brand.

## Slice Must Do

1. Update `README.md` so the project is presented to humans as BioAPEX instead of miniOpenClaw.
2. Update `backend/workspace/IDENTITY.md` so the assistant identifies itself as BioAPEX rather than Claw / miniOpenClaw.
3. Preserve the scientific/lab-specific positioning already present in the identity prompt.
4. Avoid broad copy rewrites; this is a naming cleanup pass, not a documentation restructure.
5. Leave all compatibility-sensitive runtime strings untouched.

## Non-Goals In This Slice

- changing backend health payloads, service names, or API response fields
- changing FastAPI `title` / `description` metadata
- renaming package metadata or lockfile package names
- changing fetch-tool headers or other network protocol strings
- widening into frontend UI copy beyond what is sourced from the identity prompt or README

## Done Means

- the touched human-facing docs/prompt no longer use `miniOpenClaw` or `Claw`
- the preserved machine-facing compatibility surfaces still intentionally carry their legacy identifiers
- focused compatibility verification passes
- P0 naming cleanup is complete without widening into runtime contract churn

## Dependencies

- depends on completed P0 slices 1-3; no new backend or frontend contract work is required

## Serial Or Parallel

This slice should remain serial.

Why:
- it is the final P0 cleanup pass and needs one consistent naming decision across the visible docs/prompt surfaces
- parallelizing this small copy cleanup would add coordination overhead and increase the risk of accidental contract edits
- the protected compatibility boundaries are easier to enforce in one narrow handoff

## Follow-On

After this slice, P0 Stabilize Trust should be complete.
