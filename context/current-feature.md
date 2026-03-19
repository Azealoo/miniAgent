# Current Feature

## Status
<!-- Use only one of these values: Not Started, In Progress, Completed -->
Not Started

## Goals
<!-- Write the goals in a direct, implementation-oriented way. -->
<!-- Focus on what should be built, changed, or verified. -->
<!-- Be specific enough that the work can be implemented without guessing the intent. -->

## Notes
<!-- Use this section for important implementation details, constraints, assumptions, file paths, or decisions. -->
<!-- This section should help explain how the feature should be structured, not just what it is called. -->

## History
<!-- Use this section to list completed work related to this feature. -->
<!-- Keep it short and concrete: implemented pieces, verified behavior, follow-up changes, or fixes. -->
- 2026-03-18: Completed the Artifact Naming Standard feature after review, with canonical artifact helpers, read-only artifact inspection through `/api/files`, and passing targeted backend verification in the `miniAgent` conda env.
- 2026-03-18: Fixed review blockers by materializing `run.json` and `content_hashes.json` during run setup, enforcing collision-safe artifact path reservation, validating `created_at` against `run_id`, and replacing the hanging API transport test with direct route-level coverage; verified with `pytest tests/test_artifact_naming.py tests/test_api_health.py` in the `miniAgent` conda env.
- 2026-03-18: Verified `backend/tests/test_artifact_naming.py` passes in the `miniAgent` conda env; `backend/tests/test_api_health.py` still times out on the first health test, indicating a separate API test-harness issue to resolve.
- 2026-03-18: Started Artifact Naming Standard implementation with reusable backend naming helpers, read-only `/api/files` artifact access, supporting docs, and focused backend tests plus Python smoke verification.
- 2026-03-18: Set status to In Progress and created `context/baselines/01-baseline-freeze/` with a baseline freeze document plus normal, tool-using, and RAG-enabled trace artifacts.
- 2026-03-18: Added `backend/scripts/capture_chat_baseline.py`, generated raw capture artifacts under `context/baselines/01-baseline-freeze/captures/`, clarified `/api/files` backend-root scope, and recorded actual backend/frontend verification results.
- 2026-03-18: Completed the Baseline Freeze feature after review, with captured chat baselines, verification notes, and reproducible environment/lint setup in place.
