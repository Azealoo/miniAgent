# P7 Conditional Skills And Typed Memory Lifecycle

Date: 2026-04-02

## Goal

Leverage the finished `P6 Biologist Skill And Memory Runtime` work by:

- adding path-aware conditional skill activation on top of the runtime registry and routed prompt subset
- extending the supported skill contract with a narrow, safe execution-hint subset that BioAPEX can actually honor
- turning `memory/MEMORY.md` into a concise compatibility index backed by typed scoped memory files
- making retrieval and non-RAG prompting respect typed memory instead of relying on a long compatibility document
- adding a lightweight, additive memory distillation path that reuses existing turn and session artifacts instead of reopening the harness

## Why This Phase Comes Next

- `P6` already landed the key structural prerequisites:
  - `backend/tools/skills_scanner.py` is a runtime registry
  - `backend/graph/skill_router.py` already narrows ordinary-turn skill context
  - `backend/graph/memory_indexer.py` already discovers nested memory files and retrieves section-scoped sources
  - `backend/api/files.py` and `backend/tools/write_file_tool.py` already refresh memory for writes anywhere under `memory/`
- The current research summary now identifies a narrower remaining gap:
  - path-scoped skill activation
  - a slightly richer but still disciplined skill contract
  - typed memory discipline
  - background memory distillation
- The current runtime already has seams that can support this without another redesign:
  - `backend/runtime/chat_runtime.py` already manages background tasks
  - `backend/runtime/turn_ledger.py` already accumulates structured retrieval, plan, verification, and tool blocks
  - `backend/graph/session_manager.py` already persists typed session blocks that a distillation path can reuse

## Must-Have End State

- Runtime-selected skills can be activated by both user intent and relevant file paths.
- The supported skill contract explicitly includes a small BioAPEX-native extension set, starting with `paths` and `effort`.
- `memory/MEMORY.md` is a compact human-readable index and compatibility entrypoint, not the primary long-form storage surface.
- Durable memory files use typed frontmatter so retrieval and future automation can distinguish user preferences, project facts, workflow heuristics, and scientific references.
- Typed memory retrieval stays bounded, source-aware, and compatible with the existing chat transcript contract.
- Memory distillation is additive, gated, and skips turns that already wrote memory files directly.
- The engine-first chat runtime remains intact.

## Phase Rules

1. Do not reopen the harness redesign. Treat `QueryEngine`, `ChatRuntime`, and `TurnLedger` as stable foundations.
2. Keep `SKILLS_SNAPSHOT.md` and `/api/skills` compatibility truthful while the richer runtime contract lands.
3. Keep legacy freeform memory files readable during migration. Typed memory is additive first, then tightening can follow.
4. Do not copy slash-command unification, plugin-marketplace loading, or shell-executing skill bodies from `claude_code_src`.
5. Keep activation and distillation deterministic enough to test and explain.
6. Reuse persisted turn and session artifacts instead of inventing a second transcript format for memory extraction.

## Slice 1: Skill Contract Extension Foundation

### Goal

Extend the runtime skill contract with the smallest useful execution-hint subset needed for `P7`.

### Likely File Targets

- `backend/tools/skills_scanner.py`
- `backend/knowledge/skill-authoring-guide.md`
- `backend/workspace/AGENTS.md`
- `backend/api/files.py`
- `backend/tests/test_skills_scanner.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_chat_engine_health.py`

### Must Do

- Add first-class support for a narrow optional metadata subset:
  - `paths`
  - `effort`
- Keep broader reference-repo contract features explicitly out of scope for now:
  - hooks
  - shell execution from skill bodies
  - plugin-only or MCP-only loading behavior
- Surface the new metadata through the runtime registry and authoring docs.
- Keep scanner validation backward compatible for existing `P6` skills that do not define the new optional fields.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_chat_engine_health.py -q`

### Done When

- The runtime registry can expose `paths` and `effort` cleanly.
- Authoring guidance names the supported subset and the explicit non-goals.
- Existing stable skills remain valid without surprise breakage.

### Depends On

- none

## Slice 2: Conditional Skill Activation And Routed Merge

### Goal

Make path-scoped skills activatable from real BioAPEX context instead of user-intent text alone.

### Likely File Targets

- `backend/graph/skill_router.py`
- `backend/graph/agent.py`
- `backend/runtime/query_engine.py`
- `backend/runtime/turn_ledger.py`
- `backend/graph/session_manager.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_skills_scanner.py`
- new focused router test if needed under `backend/tests/`

### Must Do

- Define a bounded activation context built from repo-real signals, at minimum:
  - explicit file-path mentions in the current user message
  - recent session blocks or tool traces that already carry touched file paths
- Match that activation context against `paths` metadata.
- Merge path-activated skills with the existing metadata-scored router deterministically.
- Preserve explicit skill-name invocation as the highest-priority selection path.
- Keep the activation logic inspectable enough that a failed or surprising selection can be reproduced in tests.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_skills_scanner.py -q`

### Done When

- File-specific tasks can surface matching skills even when the skill name is not written verbatim in the user prompt.
- Explicit skill requests still win.
- The routed prompt subset remains bounded and deterministic.

### Depends On

- Slice 1

## Slice 3: Typed Memory Contract And Index Migration

### Goal

Turn the memory directory from "multi-file but mostly freeform" into an index-backed typed memory system.

### Likely File Targets

- `backend/graph/memory_indexer.py`
- new helper module for memory metadata parsing if needed under `backend/graph/`
- `backend/memory/MEMORY.md`
- `backend/workspace/AGENTS.md`
- `backend/tools/write_file_tool.py`
- `backend/api/files.py`
- `backend/tests/test_memory_indexer.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_audit_logging.py`

### Must Do

- Define a minimal typed memory frontmatter contract with required fields:
  - `type`
  - `name`
  - `description`
- Enforce a closed initial type set that at minimum covers:
  - user preference
  - project fact
  - workflow heuristic
  - scientific reference
- Keep legacy memory files readable during migration so `P6` compatibility does not break.
- Rewrite `memory/MEMORY.md` into a concise index and compatibility document that points readers toward scoped files instead of carrying the full durable body itself.
- Update write-path guidance so new durable content goes into the most specific typed file first, with `MEMORY.md` acting as index and summary.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_tools.py tests/test_audit_logging.py -q`
- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py -q -k "files or session_tokens"`

### Done When

- New typed memory files can coexist with older freeform notes.
- `memory/MEMORY.md` is clearly an index and compatibility entrypoint instead of the main long-form store.
- Memory-writing guidance becomes type-aware and path-specific.

### Depends On

- none

## Slice 4: Typed Retrieval And Non-RAG Prompt Cleanup

### Goal

Make retrieval and prompt assembly respect typed memory instead of implicitly depending on a long compatibility file.

### Likely File Targets

- `backend/graph/memory_indexer.py`
- `backend/graph/prompt_builder.py`
- `backend/graph/agent.py`
- `backend/tests/test_memory_indexer.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_chat_streaming.py`

### Must Do

- Parse typed memory frontmatter during indexing.
- Carry type-aware metadata through retrieval results.
- Keep retrieval source-aware and compact.
- Make non-RAG prompt behavior intentionally index-first now that `memory/MEMORY.md` is concise, instead of depending on that file to contain the whole durable memory body.
- Avoid any prompt path that silently inlines all typed memory files.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_prompt_builder.py tests/test_chat_streaming.py -q`

### Done When

- Retrieved memories cite typed sources and remain bounded.
- Non-RAG prompt assembly stays compatible while no longer depending on a long-form `MEMORY.md`.
- Streamed retrieval behavior remains green.

### Depends On

- Slice 3

## Slice 5: Memory Distillation And Duplicate-Write Guard

### Goal

Add a lightweight memory distillation path that uses existing session artifacts and does not fight direct memory writes from the main agent.

### Likely File Targets

- `backend/runtime/chat_runtime.py`
- `backend/runtime/turn_ledger.py`
- `backend/graph/session_manager.py`
- new distillation module under `backend/runtime/` or `backend/graph/`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_runtime_query_engine.py`
- new focused distillation tests under `backend/tests/`

### Must Do

- Add a gated post-turn distillation path that reuses persisted structured turn and session data.
- Use typed memory files and the new index contract as the only write targets for automatic distillation.
- Skip distillation when the turn already wrote to `memory/` directly.
- Keep the flow additive and debuggable:
  - no silent rewrite of unrelated user-authored memory files
  - no duplicate memory creation for the same turn
- Keep the distillation path lightweight enough that it does not become a second orchestrator.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_runtime_query_engine.py tests/test_memory_distillation.py -q`

### Done When

- Verified turns can create or update typed memory files automatically.
- Turns that already wrote memory directly do not get a second redundant write pass.
- Distillation remains an optional, explainable runtime behavior rather than a hidden rewrite layer.

### Depends On

- Slice 3
- Slice 4

## Slice 6: Final Surface And Regression Closeout

### Goal

Close `P7` with one coherent story for conditional skills, typed memory, and compatibility surfaces.

### Likely File Targets

- `backend/knowledge/skill-authoring-guide.md`
- `backend/workspace/AGENTS.md`
- `backend/tests/test_skills_scanner.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_memory_indexer.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_engine_health.py`
- any touched runtime files that still need cleanup from earlier slices

### Must Do

- Align docs, runtime behavior, and compatibility surfaces so they tell the same story.
- Verify that `/api/skills`, `/api/skills/registry`, and `memory/MEMORY.md` remain intentionally truthful during the new contract.
- Confirm that the engine-first runtime did not absorb accidental new orchestration complexity.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_memory_indexer.py tests/test_chat_streaming.py tests/test_runtime_query_engine.py tests/test_chat_engine_health.py tests/test_memory_distillation.py -q`
- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m compileall -q .`

### Done When

- The runtime, docs, and compatibility artifacts agree on how skills and memory now work.
- `P7` can be described without hand-waving around `paths`, `MEMORY.md`, or distillation behavior.
- The backend remains green on the focused regression sweep.

### Depends On

- Slices 1 through 5
