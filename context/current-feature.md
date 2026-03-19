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
- 2026-03-18: Completed Session Memory Upgrade after review signoff with shared structured session-summary generation, backward-compatible `compressed_context` serialization and parsing, preserved salient IDs/paths/risk context during long-message compression, deferred standalone artifact emission, and passing targeted backend verification via `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest backend/tests/test_session_manager.py backend/tests/test_api_health.py`.
- 2026-03-18: Fixed Session Memory Upgrade review issues by enforcing a hard structured-summary size cap, preserving salient PMIDs/run IDs/paths/risk notes when long archived messages are condensed for summarization, broadening structured heading parsing, and re-verifying with `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest backend/tests/test_session_manager.py backend/tests/test_api_health.py`.
- 2026-03-18: Started Session Memory Upgrade implementation with shared structured summary helpers in `backend/graph/session_summary.py`, unified manual and auto compression generation, legacy-summary parsing plus multi-pass summary support in `SessionManager`, direct `/api/sessions/{id}/compress` coverage, and passing targeted backend verification via `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest backend/tests/test_session_manager.py backend/tests/test_api_health.py`.
- 2026-03-18: Completed Artifact Registry MVP after review signoff, with file-first rebuildable registry storage, reusable `/api/artifacts/registry` lookup and rebuild routes, broader canonical artifact indexing, tracked `RunLayout` incremental refresh, and passing targeted backend verification (`50 passed`).
- 2026-03-18: Fixed review gaps for Artifact Registry MVP by expanding indexing beyond the initial schema-pack root files to cover canonical root records, generated outputs, user inputs, and `ro-crate/` entries; wiring tracked `RunLayout` artifact writes to refresh the registry incrementally; and re-verifying with `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest backend/tests/test_artifact_registry.py backend/tests/test_artifact_naming.py backend/tests/test_artifact_schemas.py backend/tests/test_api_health.py`.
- 2026-03-18: Started Artifact Registry MVP implementation with a persisted backend registry under `backend/storage/artifact_registry/registry.json`, canonical artifact scanning and lookup logic in `backend/artifacts/registry.py`, reusable lookup/rebuild API routes under `/api/artifacts/registry`, compatibility for current minimal `run.json` root records, and passing targeted backend verification via `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest backend/tests/test_artifact_registry.py backend/tests/test_artifact_naming.py backend/tests/test_artifact_schemas.py backend/tests/test_api_health.py`.
- 2026-03-18: Completed Core Schema Pack V1 with typed artifact schema models, implementation-grade JSON/YAML examples on disk and in the feature spec, aligned durable header requirements (`run_id` plus `source_workflow` or `source_tool`), and passing targeted backend verification via `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_artifact_naming.py tests/test_artifact_schemas.py`.
- 2026-03-18: Fixed schema-pack review issues by aligning all artifact schemas with the existing durable header contract (`run_id` plus `source_workflow` or `source_tool`), updating the example artifacts accordingly, adding schema examples directly to `context/features/03-core-schema-pack-v1-spec.md`, and re-verifying with `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_artifact_naming.py tests/test_artifact_schemas.py`.
- 2026-03-18: Started Core Schema Pack V1 implementation with typed artifact schema models under `backend/artifacts/schemas.py`, implementation-grade JSON/YAML examples under `backend/artifacts/examples/`, and passing targeted backend verification via `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_artifact_naming.py tests/test_artifact_schemas.py`.
- 2026-03-18: Completed the Artifact Naming Standard feature after review, with canonical artifact helpers, read-only artifact inspection through `/api/files`, and passing targeted backend verification in the `miniAgent` conda env.
- 2026-03-18: Fixed review blockers by materializing `run.json` and `content_hashes.json` during run setup, enforcing collision-safe artifact path reservation, validating `created_at` against `run_id`, and replacing the hanging API transport test with direct route-level coverage; verified with `pytest tests/test_artifact_naming.py tests/test_api_health.py` in the `miniAgent` conda env.
- 2026-03-18: Verified `backend/tests/test_artifact_naming.py` passes in the `miniAgent` conda env; `backend/tests/test_api_health.py` still times out on the first health test, indicating a separate API test-harness issue to resolve.
- 2026-03-18: Started Artifact Naming Standard implementation with reusable backend naming helpers, read-only `/api/files` artifact access, supporting docs, and focused backend tests plus Python smoke verification.
- 2026-03-18: Set status to In Progress and created `context/baselines/01-baseline-freeze/` with a baseline freeze document plus normal, tool-using, and RAG-enabled trace artifacts.
- 2026-03-18: Added `backend/scripts/capture_chat_baseline.py`, generated raw capture artifacts under `context/baselines/01-baseline-freeze/captures/`, clarified `/api/files` backend-root scope, and recorded actual backend/frontend verification results.
- 2026-03-18: Completed the Baseline Freeze feature after review, with captured chat baselines, verification notes, and reproducible environment/lint setup in place.
