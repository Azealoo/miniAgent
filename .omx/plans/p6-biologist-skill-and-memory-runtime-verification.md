# P6 Biologist Skill And Memory Runtime Verification Map

Date: 2026-04-02

## Verification Policy

- Every slice must leave the backend green before the next slice starts.
- Prefer focused suites that cover the touched contracts instead of one giant late-phase test run only.
- Keep compatibility checks explicit while old and new skill or memory behavior coexist.

## Slice Matrix

### Slice 1: Skill Catalog Foundation

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py -q`
- Required sweeps:
  - `cd /gpfs/projects/hrbomics/miniAgent && rg -n "category: bio/scRNA|category: bio/perturbation|category: bio/calculations|category: bio/hpc|slurm_tool" backend/skills -S`
- Review focus:
  - normalized taxonomy values
  - valid tool names
  - visible `stable` versus `experimental` split

### Slice 2: Memory Directory Foundation

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_tools.py tests/test_audit_logging.py -q`
- Secondary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py -q -k "files or session_tokens"`
- Review focus:
  - compatibility for `memory/MEMORY.md`
  - rebuild behavior for writes anywhere under `memory/`
  - truthful instructions about memory versus knowledge

### Slice 3: Relevant Memory Selection

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_prompt_builder.py tests/test_chat_streaming.py -q`
- Review focus:
  - per-file memory sources
  - bounded retrieval size
  - no regression in streamed retrieval or persisted blocks

### Slice 4: Runtime Skill Registry Foundation

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_chat_engine_health.py -q`
- Review focus:
  - runtime registry precedence
  - enable or disable behavior
  - `/api/skills` truthfulness
  - snapshot no longer being the only source of truth

### Slice 5: Skill Routing And Prompt Integration

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- Review focus:
  - deterministic relevant-skill selection
  - explicit skill-name invocation still working
  - prompt size and relevance improving together

### Slice 6: Core Biologist Workflow Hardening

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_chat_streaming.py -q`
- Required sweeps:
  - `cd /gpfs/projects/hrbomics/miniAgent && rg -n "stability: stable" backend/skills/*/SKILL.md -S`
- Review focus:
  - stable skills are truly tool-backed
  - outputs are evidence-aware and biologist-native
  - promoted skills no longer look like thin prototypes

### Slice 7: Final Surface And Regression Closeout

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_memory_indexer.py tests/test_chat_streaming.py tests/test_runtime_query_engine.py tests/test_chat_engine_health.py -q`
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m compileall -q .`
- Review focus:
  - one coherent story for skills and memory
  - no backslide into snapshot-only or single-file-only assumptions
  - engine-first runtime still intact

## Phase Completion Check

Before calling `P6` done, confirm all of the following:

- `backend/skills/` has a stable subset with normalized metadata and no stale tool references.
- runtime skill selection is in use for ordinary turns
- memory retrieval is source-aware across a directory, not just one file
- `memory/MEMORY.md` compatibility is either preserved intentionally or removed with explicit replacement
- focused backend verification for skills, prompt building, memory, chat streaming, and engine health is green
