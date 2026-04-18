# Claude Code Source Harness Skills Memory Refresh

Date: 2026-04-02
Mode: ultrawork + research

## Question

Given the current BioAPEX backend state, what is still worth leveraging from `ponponon/claude_code_src` in three areas:

- harness engineering
- skills
- memory

Treat the reference repo as the gold standard, but adapt it in a BioAPEX-native way.

## Sources Reviewed

### Current BioAPEX backend

- `backend/runtime/query_engine.py`
- `backend/runtime/chat_runtime.py`
- `backend/graph/agent.py`
- `backend/graph/prompt_builder.py`
- `backend/graph/memory_indexer.py`
- `backend/graph/skill_router.py`
- `backend/tools/skills_scanner.py`
- `backend/tools/registry.py`
- `backend/api/files.py`
- `context/current-feature.md`

### Reference repo

- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/QueryEngine.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/utils/queryContext.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools/AgentTool/loadAgentsDir.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/skills/loadSkillsDir.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/utils/markdownConfigLoader.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/memdir.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/paths.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/memoryScan.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/services/extractMemories/extractMemories.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools/AgentTool/agentMemory.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/utils/plugins/pluginLoader.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/utils/hooks/hooksConfigManager.ts`
- `https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/utils/hooks/sessionHooks.ts`

## Executive Verdict

- Harness: BioAPEX is already close enough that another core runtime refactor would be low leverage.
- Skills: BioAPEX now matches the reference on registry-first loading and turn-time routing, but still trails on conditional activation and richer skill contracts.
- Memory: BioAPEX now matches the reference on multi-file retrieval basics, but still trails on memory taxonomy, lifecycle, and scoped persistence.

The biggest remaining leverage is:

1. keep the current engine-first harness
2. add path-aware and richer-contract skill activation
3. finish the memory model as typed artifacts plus retrieval, not just a directory scan

## Comparison

### 1. Harness Engineering

#### Where the reference repo is stronger

`claude_code_src` still has a broader outer harness:

- `src/QueryEngine.ts` owns more of the end-to-end query lifecycle, including cache-safe prompt assembly, budget tracking, plugin and skill loading, and session mutation.
- `src/utils/queryContext.ts` centralizes reusable system-prompt cache-prefix assembly.
- `src/utils/markdownConfigLoader.ts` gives instruction and config discovery a clear precedence model across managed, user, project, worktree, and extra directories.
- `src/utils/hooks/hooksConfigManager.ts` and `src/utils/hooks/sessionHooks.ts` provide a rich hook/event plane around tool calls, subagents, setup, config changes, and working-directory changes.
- `src/utils/plugins/pluginLoader.ts` and `src/tools/AgentTool/loadAgentsDir.ts` add trust-boundary-aware plugin and agent loading instead of treating all extensions as one flat source.

#### Where BioAPEX is already strong

The core turn runtime is already in the right place:

- `backend/runtime/query_engine.py` is the ordinary-turn boundary for preflight, evidence gating, helper-agent extraction, and repair retry.
- `backend/runtime/chat_runtime.py` is the transport and persistence shell.
- `backend/tools/registry.py` already has meaningful manifest fields for `read_only`, `destructive`, `concurrency_safe`, helper exposure, and interrupt behavior.
- `backend/graph/prompt_builder.py` already does ancestor instruction discovery and additive project-context loading, which is closer to the reference repo than the older BioAPEX harness was.

#### What to leverage

- Add a small reusable prompt-context assembly seam behind `QueryEngine` instead of spreading more prompt concerns across `agent.py`, `prompt_builder.py`, and runtime entrypoints.
- Borrow the reference repo's instruction precedence and session-hook ideas if BioAPEX needs more operator or plugin lifecycle control.
- Keep BioAPEX's compliance and evidence gating as first-class runtime behavior. That is already stronger than the reference repo for this product.

#### What not to copy

- plugin marketplace complexity
- mobile or bridge transport behavior
- hook sprawl before there is a clear product need
- CLI or TUI-specific runtime machinery

### 2. Skills

#### Where the reference repo is stronger

`src/skills/loadSkillsDir.ts` still has the richer skill model:

- multiple skill sources including managed, user, project, additional dirs, plugin, bundled, and MCP
- deduplication by canonical file identity
- path-scoped conditional skills via `paths` frontmatter
- dynamic activation from touched files
- richer frontmatter for model, effort, hooks, shell execution, execution context, and agent handoff

#### Where BioAPEX is already strong

BioAPEX has already closed much of the earlier gap:

- `backend/tools/skills_scanner.py` is now a real runtime registry with source precedence, enablement, shadowing metadata, and validation.
- `backend/graph/skill_router.py` routes a turn to a bounded skill subset by metadata and preserves explicit skill invocation.
- `backend/graph/prompt_builder.py` injects the routed subset rather than the whole catalog.
- `backend/api/files.py` exposes both the active skill list and the richer runtime registry.

#### What to leverage

- Add optional path-scoped activation to BioAPEX skills so relevant workflows appear when touched files or domains make them relevant.
- Expand the skill contract beyond taxonomy metadata into execution hints such as effort, preferred runtime lane, or bundled helper assets.
- Support skill-local assets or scripts in a disciplined way for richer biologist workflows.
- Only add plugin or MCP skill sources if BioAPEX truly needs external skill distribution.

#### What not to copy

- the slash-command and skills unification
- command-surface growth for its own sake
- plugin-origin skills unless there is a trust and provenance model ready for them

### 3. Memory

#### Where the reference repo is stronger

The reference repo still has the more complete memory lifecycle:

- `src/memdir/memdir.ts` treats `MEMORY.md` as an index and gives the model strong instructions about what memory is for.
- `src/memdir/memoryTypes.ts` constrains memories to typed categories with explicit save and recall rules.
- `src/memdir/paths.ts` clearly separates auto-memory behavior, overrides, and scope resolution.
- `src/services/extractMemories/extractMemories.ts` adds background extraction and avoids double-writing when the main agent already saved memories.
- `src/tools/AgentTool/agentMemory.ts` supports explicit agent memory scopes.

#### Where BioAPEX is already strong

BioAPEX has already gone beyond the old single-file model:

- `backend/graph/memory_indexer.py` now scans multiple files under `memory/`, splits markdown into section-level sources, and supports hybrid retrieval.
- `backend/api/files.py` refreshes memory state for any `memory/` write, not just `memory/MEMORY.md`.
- current P6 work has already established `memory/project/`, `memory/user/`, and `memory/agent/` as a directory layout.

#### Remaining BioAPEX gaps

- `backend/graph/prompt_builder.py` still falls back to injecting only `memory/MEMORY.md` when RAG mode is off, so the compatibility file still acts too much like the primary memory surface.
- Memory files are not yet treated as typed artifacts with frontmatter and durable retrieval semantics.
- There is no automatic extraction or distillation path from session history into durable memory.
- There is no deliberate scoped-memory contract beyond directory naming.

#### What to leverage

- Make `memory/MEMORY.md` a concise compatibility index, not the main memory body.
- Introduce typed frontmatter for durable memory files so BioAPEX can distinguish user preferences, project facts, scientific references, and workflow heuristics.
- Add a light file-selection stage ahead of or on top of section retrieval so prompt injection stays small and source-aware.
- Consider scoped memory deliberately: user plus project first, helper-agent memory only where persistent specialization is genuinely useful.
- Reuse BioAPEX's existing `SessionManager` and `TurnLedger` outputs as future inputs to memory distillation rather than copying the reference repo's exact extraction flow.

## Priority Order

If BioAPEX wants the highest-value next leverage from the gold-standard repo:

1. do not reopen the core harness
2. add path-aware skill activation and richer skill contracts
3. finish the memory model as typed files plus an index and selective recall
4. only then consider hook or plugin-extension surfaces

## Bottom Line

Treat `claude_code_src` as the gold standard mostly for outer-harness ergonomics and memory discipline, not for BioAPEX's core turn engine.

BioAPEX should leverage:

- its existing `QueryEngine` and `ChatRuntime` for harness work
- its current runtime skill registry and router for skill evolution
- its current multi-file memory indexer as the base for typed memory artifacts

BioAPEX should still borrow:

- conditional skill activation
- typed memory taxonomy and lifecycle guidance
- optional scoped memory contracts
- hookable extension seams only when product pressure justifies them
