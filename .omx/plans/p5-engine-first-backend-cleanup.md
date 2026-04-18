# P5 Engine-First Backend Cleanup

Date: 2026-04-02

## Goal

Keep `QueryEngine` as the clear center of ordinary chat, trim code that no longer belongs on the engine-first path, and leave the backend shaped more like the strongest structural ideas in `ponponon/claude_code_src`: thin entrypoints, one obvious runtime boundary, explicit tool/helper-agent contracts, and as little compatibility scaffolding as possible.

## Why This Phase Comes Next

- `P4 Backend Harness-First Redesign` already landed the important runtime behavior: accepted-turn lifecycle ownership, richer tool manifests, helper-agent artifacts, bounded repair, runtime finalization, and legacy dispatch quarantine.
- The remaining work is no longer “build the harness.” It is “clean the codebase around the harness” so the engine-first design is obvious in the source tree and easier to maintain.
- The user later narrowed the backend goal further: keep the chat engine and delete workflow/protocol execution surfaces that no longer belong in the backend.

## Phase Rules

1. Mimic `claude_code_src` structurally, not cosmetically.
2. Keep `backend/runtime/query_engine.py` as the main ordinary-chat runtime boundary.
3. Preserve compatibility only where it prevents avoidable client breakage; otherwise prefer deleting obsolete workflow/protocol runtime code.
4. Remove duplicate or dead code only after import/test evidence shows it is safe.
5. Keep team/review artifacts honest for every cleanup slice.

## Keep / Move / Remove Principles

### Keep

- Engine core and runtime helpers:
  - `backend/runtime/query_engine.py`
  - `backend/runtime/turn_ledger.py`
  - `backend/runtime/helper_agent_runner.py`
- Tool execution contract and scoped helper agents:
  - `backend/tools/registry.py`
  - `backend/tools/policy.py`
  - `backend/tools/policy_wrappers.py`
  - `backend/tools/plan_agent_tool.py`
  - `backend/tools/verification_agent_tool.py`
- Remaining product surfaces:
  - `backend/api/chat.py`
  - `backend/api/access.py`
  - `backend/api/files.py`
  - `backend/api/sessions.py`

### Move Or Isolate

- Remaining chat-route concerns that are still transport-adjacent but not engine-owned:
  - `backend/api/chat.py`

### Remove When Proven Safe

- Dead public engine aliases or compatibility wrappers that are no longer called by product code.
- Duplicate chat/runtime orchestration that survives only because older tests or compatibility helpers still reference it.
- Compatibility-specific tests that no longer match the intended engine-first public surface.

## Planned Slices

### Slice 1: Engine Boundary And Pruning Map

- Produce an exact keep/move/remove map for backend orchestration code.
- Identify which `QueryEngine` methods are truly public, which are compatibility-only, and which are dead.
- Inventory import-level references to workflow/protocol compatibility code so later deletions stay safe.

### Slice 2: Slim The Public Engine Surface

- Make the engine’s intended API obvious.
- Remove or demote legacy helper entrypoints that product code no longer uses.
- Keep tests focused on the real public runtime boundary.

### Slice 3: Isolate Legacy Compatibility

- Move workflow/protocol compatibility helpers behind a smaller, named boundary so `QueryEngine` reads like the normal engine path first.
- Preserve valid legacy behavior without letting those imports and helpers dominate the engine file.

### Slice 4: Route And Test Cleanup

- Remove stale route-local duplication and tests that only protect deleted compatibility shapes.
- Keep the final route thin and the runtime-centered architecture easy to follow.

### Slice 5: Chat-Only Runtime Cull

- Delete workflow and protocol execution from the live backend runtime.
- Keep only the ordinary chat engine path plus lightweight compatibility shims where the frontend still expects a read.
- Remove the dedicated workflow/protocol backend suites and modules once imports prove they are dead.

### Slice 6: Chat-Only Frontend Cull

- Remove flow-mode UI, selected-workflow state, and the frontend compatibility reads that only existed for the deleted backend workflow surfaces.
- Stop sending `selected_workflow` from chat requests and delete the matching backend compatibility route.
- Update shell and contract tests so they assert the reduced chat-only payload and quick-start behavior.

## Exit Conditions

- `QueryEngine` is the obvious ordinary-chat center in both code and tests.
- Workflow/protocol execution no longer exists in the live backend runtime.
- The frontend shell no longer exposes a flows workspace or selected-workflow chat path.
- `backend/api/chat.py` stays thin and transport-oriented.
- The backend tree is smaller or clearer while still supporting the chat surface cleanly.
