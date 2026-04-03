# P5 Slice 4 Chat-Only API Surface Cull

Date: 2026-04-02

## Goal

Trim the public backend down to the chat-engine-adjacent HTTP surface by keeping only the routes that still directly support chat execution and session/file access, and deleting unrelated API modules plus their dedicated route tests.

## Scope

This slice removes non-chat API surfaces and their route-level tests. It intentionally keeps:

- `backend/api/chat.py`
- `backend/api/access.py`
- `backend/api/sessions.py`
- `backend/api/files.py`

It removes public API modules that no longer belong in a chat-engine-only backend.

## Files

- `backend/app.py`
- deleted API modules:
  - `backend/api/artifact_registry.py`
  - `backend/api/audit.py`
  - `backend/api/compress.py`
  - `backend/api/config_api.py`
  - `backend/api/connectors.py`
  - `backend/api/observability.py`
  - `backend/api/skills_registry.py`
  - `backend/api/studies.py`
  - `backend/api/tokens.py`
- deleted or reduced tests:
  - `backend/tests/test_api_health.py`
  - `backend/tests/test_artifact_registry.py`
  - `backend/tests/test_connectors.py`
  - `backend/tests/test_observability.py`
  - `backend/tests/test_studies_api.py`
  - `backend/tests/test_chat_engine_health.py`
  - `backend/tests/test_audit_logging.py`

## Must Do

1. Keep only chat-engine-adjacent routers in `backend/app.py`.
2. Delete unrelated API route modules rather than merely leaving them unregistered.
3. Replace the old broad API health suite with a minimal health/access/session/file suite for the reduced backend.
4. Keep focused chat-path and audit-store verification green after the route cull.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_audit_logging.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "from api\\.(artifact_registry|audit|compress|config_api|connectors|observability|skills_registry|studies|tokens)" backend/tests -S`

## Exit Conditions

- the app exposes only chat-engine-adjacent routers
- deleted route modules are gone from the backend tree
- route-level tests for deleted APIs are gone
- focused chat-engine verification remains green
