# Backend Hardening Slice 1: Python REPL Session Isolation

## Goal

Remove the shared Python REPL state leak so BioAPEX no longer reuses one persistent interpreter across unrelated chat sessions.

## Why This Slice Exists

- Research on 2026-04-02 identified a real backend flaw: the Python REPL tool stores mutable interpreter state on a globally shared runtime tool instance.
- That can leak variables/imports across sessions and creates unsafe concurrency behavior.
- This is the smallest high-value hardening slice before broader backend-runtime refactors.

## Scope

In scope:

- make Python REPL state resolve per session key
- preserve persistence within a single session
- preserve predictable persistence for direct non-session calls used by tests
- add regression coverage proving session isolation

Out of scope:

- hosted-default hardening profile changes
- broader `backend/api/chat.py` runtime extraction
- redesigning the full tool contract
- changing other tools to per-session state

## Likely Files

- `backend/tools/python_repl_tool.py`
- `backend/tests/test_tools.py`
- `backend/api/sessions.py` only if session cleanup is wired in this slice
- `backend/graph/agent.py` only if tool-runtime cleanup helpers are needed

## Implementation Requirements

1. The Python REPL tool must not store one interpreter that is shared across all sessions.
2. When a `session_id` is available in tool policy context, REPL state must be isolated to that session.
3. Within the same session, repeated REPL calls must still see prior variables/imports.
4. When no session context is available, direct calls should still use a stable fallback state for that tool instance so current tests and non-chat usage remain functional.
5. The existing runtime guards and secret/process blocking behavior must remain intact.

## Verification Map

- unit test: same-session persistence still works
- unit test: different session ids do not share REPL variables
- unit test: no-session direct usage still persists within one tool instance
- unit test: existing blocked secret/process behavior still passes in the targeted suite

## Exit Criteria

- Python REPL state is keyed by session rather than one shared `_repl` field
- regression coverage exists for session isolation
- targeted backend verification passes
- verification evidence is recorded in the paired verification note
