# P7 Conditional Skills And Typed Memory Lifecycle Verification Map

Date: 2026-04-02

## Verification Policy

- Keep every slice green before starting the next one.
- Prefer focused suites that match the new contract surfaces rather than relying on one late end-to-end sweep only.
- Make compatibility checks explicit while `SKILLS_SNAPSHOT.md`, `/api/skills`, and `memory/MEMORY.md` continue to exist.

## Slice Matrix

### Slice 1: Skill Contract Extension Foundation

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_chat_engine_health.py -q`
- Review focus:
  - registry serialization of `paths` and `effort`
  - backward compatibility for existing `P6` skills
  - docs that clearly name supported versus unsupported contract extensions

### Slice 2: Conditional Skill Activation And Routed Merge

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_skills_scanner.py -q`
- Review focus:
  - deterministic path-aware activation
  - explicit skill-name invocation still winning
  - routed prompt subsets staying bounded

### Slice 3: Typed Memory Contract And Index Migration

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_tools.py tests/test_audit_logging.py -q`
- Secondary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py -q -k "files or session_tokens"`
- Review focus:
  - typed memory parsing
  - compatibility for older memory files
  - `MEMORY.md` behaving like an index instead of the main durable body

### Slice 4: Typed Retrieval And Non-RAG Prompt Cleanup

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_prompt_builder.py tests/test_chat_streaming.py -q`
- Review focus:
  - typed retrieval metadata
  - compact retrieval blocks
  - non-RAG prompt staying intentionally index-first

### Slice 5: Memory Distillation And Duplicate-Write Guard

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_runtime_query_engine.py tests/test_memory_distillation.py -q`
- Review focus:
  - gated post-turn distillation
  - duplicate-write avoidance when memory was already written directly
  - additive updates rather than silent rewrites

### Slice 6: Final Surface And Regression Closeout

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_memory_indexer.py tests/test_chat_streaming.py tests/test_runtime_query_engine.py tests/test_chat_engine_health.py tests/test_memory_distillation.py -q`
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m compileall -q .`
- Review focus:
  - one coherent story across registry, router, index, retrieval, and distillation
  - compatibility artifacts remaining intentional and truthful
  - no accidental harness creep

## Phase Completion Check

Before calling `P7` done, confirm all of the following:

- the runtime skill contract supports a narrow richer subset, starting with `paths` and `effort`
- path-aware activation can influence routed skill selection without breaking explicit invocation
- `memory/MEMORY.md` is concise and index-like rather than a long-form durability dump
- typed memory files exist with a closed initial type set and backward-compatible parsing
- typed memory retrieval is bounded and source-aware
- automatic distillation is gated and skips turns that already wrote memory directly
- focused backend verification and `compileall` are green
