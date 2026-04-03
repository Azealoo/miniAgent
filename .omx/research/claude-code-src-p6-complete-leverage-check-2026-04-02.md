# Claude Code Source P6 Complete Leverage Check

Date: 2026-04-02
Mode: ultrawork + research

## Question

Now that the backend has changed and P6 is marked complete, what is still worth leveraging from `ponponon/claude_code_src` in:

- harness engineering
- skills
- memory

Treat the reference repo as the gold standard, but judge against the current BioAPEX backend rather than the earlier P6-in-progress state.

## Sources Reviewed

### Current BioAPEX backend

- `context/current-feature.md`
- `backend/runtime/query_engine.py`
- `backend/graph/agent.py`
- `backend/graph/prompt_builder.py`
- `backend/graph/memory_indexer.py`
- `backend/graph/skill_router.py`
- `backend/tools/skills_scanner.py`
- `backend/api/files.py`
- `backend/memory/MEMORY.md`
- `backend/tests/test_skills_scanner.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_memory_indexer.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_chat_engine_health.py`

### Reference repo

- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/QueryEngine.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/skills/loadSkillsDir.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/memdir.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/services/extractMemories/extractMemories.ts`

## Verification

Targeted backend verification passed after the latest changes:

- `102 passed, 3 skipped` from:
  - `tests/test_skills_scanner.py`
  - `tests/test_prompt_builder.py`
  - `tests/test_memory_indexer.py`
  - `tests/test_runtime_query_engine.py`
  - `tests/test_chat_streaming.py`
  - `tests/test_chat_engine_health.py`

## Current Verdict

P6 is materially done. The leverage story has narrowed.

- Harness: keep the current BioAPEX runtime shape.
- Skills: leverage conditional activation and richer contracts.
- Memory: leverage the reference repo's discipline much more aggressively.

The biggest remaining gap is no longer "runtime skill registry exists or not." That part is already landed.

## Repo Truth After P6

### Harness

BioAPEX already has a strong engine-first boundary:

- `backend/runtime/query_engine.py` owns turn orchestration, compliance preflight, evidence review gating, helper-agent event extraction, and repair retry.
- `backend/graph/agent.py` rebuilds the agent per request and injects routed skills plus retrieved memory.

Compared with the reference repo, this means BioAPEX does not need another foundational harness rewrite right now.

### Skills

BioAPEX now has the important P6 pieces in place:

- `backend/tools/skills_scanner.py` is a real runtime registry with precedence, enablement, shadowing, and validation.
- `backend/graph/skill_router.py` selects a bounded skill subset per turn.
- `backend/graph/prompt_builder.py` can inject runtime-selected skills instead of trusting `SKILLS_SNAPSHOT.md`.
- `backend/api/files.py` treats `SKILLS_SNAPSHOT.md` as a compatibility artifact and exposes the registry directly.

This closes the earlier "static snapshot only" gap.

### Memory

BioAPEX also moved beyond the old single-file memory model:

- `backend/graph/memory_indexer.py` scans nested files under `memory/`, splits markdown into section-level sources, and supports lexical plus vector retrieval.
- `backend/api/files.py` rebuilds the memory index after any write under `memory/`.
- `backend/memory/` already has scoped directories for `project`, `user`, and `agent`.

This closes the earlier "only `memory/MEMORY.md` matters" implementation gap, but not the memory-discipline gap.

## What Is Still Worth Leveraging

### 1. Skills: path-scoped activation

This is the cleanest next borrow from the gold-standard repo.

`claude_code_src` supports `paths` frontmatter and activates conditional skills when touched files match. BioAPEX still routes only from the user message text and current skill metadata.

That means the next high-value feature is:

- add optional `paths` support to BioAPEX skill frontmatter
- activate those skills from touched files or workspace focus
- merge that with the existing query-time router, not replace it

### 2. Skills: richer skill contracts

The reference repo's skill contract is still richer than BioAPEX's current metadata set.

Worth borrowing:

- `effort`
- execution context or preferred lane
- optional agent handoff hint
- optional hook metadata
- optional skill-local shell or helper-asset contract

Not worth borrowing right now:

- slash-command unification
- plugin-heavy skill loading
- marketplace-style skill distribution

### 3. Memory: make `MEMORY.md` an index for real

This is the biggest remaining delta.

BioAPEX says `memory/MEMORY.md` is a compatibility entrypoint, but the file still contains durable user facts and long-form historical content directly inside the entrypoint. The reference repo is stricter: `MEMORY.md` is an index, and the durable content lives in typed files.

So the next move is:

- move durable facts out of `memory/MEMORY.md`
- keep `MEMORY.md` concise as an index plus short summaries
- store the real content in scoped files under `memory/user/`, `memory/project/`, and `memory/agent/`

### 4. Memory: add typed frontmatter and lifecycle rules

The reference repo's memory system is stronger because it gives the model a taxonomy and save rules, not just directories.

BioAPEX should add:

- typed frontmatter for memory files
- explicit memory categories such as user preference, project fact, workflow heuristic, and scientific reference
- save/update/remove rules
- guidance on what should never become durable memory

### 5. Memory: add extraction or distillation

BioAPEX still has no background extraction or distillation step comparable to `extractMemories.ts`.

That remains worth leveraging, but only after the file format and index discipline are in place.

Recommended order:

1. typed memory files
2. `MEMORY.md` as a concise index
3. optional lightweight background distillation

## What Not To Reopen

Do not reopen the core harness just because the reference repo is broader.

BioAPEX already has product-specific strengths the reference repo does not center:

- compliance preflight
- evidence review gating
- repair-loop semantics
- a bounded turn-runtime contract

Those are stronger leverage points for BioAPEX than copying more CLI-era harness complexity.

## Recommended Next Slice

If there is a P7-style follow-up, the best order is:

1. add `paths`-aware skill activation on top of the existing router
2. expand skill frontmatter with richer execution metadata
3. convert memory to typed files plus a compact `MEMORY.md` index
4. add a lightweight memory distillation path
5. defer hooks and plugin-surface growth until there is real product pressure

## Bottom Line

With P6 complete, BioAPEX has already captured the highest-value structural ideas from `claude_code_src` for skills and basic memory retrieval.

What remains worth leveraging is narrower and more product-specific:

- conditional skill activation
- richer skill contracts
- typed memory discipline
- background memory distillation

The right move now is not another harness refactor. It is a focused leverage pass on skills and memory semantics.
