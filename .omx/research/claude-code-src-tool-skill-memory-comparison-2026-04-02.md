# Claude Code Source Tool Skill Memory Comparison

## Date

2026-04-02

## Question

Does BioAPEX already have tool, skill, and memory systems comparable to `ponponon/claude_code_src`, and what should we mimic now that the harness work is already in place?

## External Repo Truth

Inspected `ponponon/claude_code_src` at commit `adb321f6a3af4e0b76a1e076168bd521e9ba20af`.

- `src/Tool.ts` defines a rich per-tool contract with schema, validation, permissions, read-only and destructive classification, concurrency safety, interrupt behavior, deferred loading, render hooks, and classifier input.
- `src/commands.ts` treats commands and skills as one discovery surface and merges built-in commands, bundled skills, plugin skills, workflow commands, and dynamically discovered skills.
- `src/skills/loadSkillsDir.ts` supports multiple skill sources, precedence rules, conditional path-scoped skills, dynamic skill discovery from touched paths, and plugin or MCP supplied skills.
- `src/memdir/memdir.ts` implements a memory directory system rather than a single memory file. It treats `MEMORY.md` as an index, stores individual memory files, supports richer prompt guidance, and includes optional team or agent memory scopes.
- `src/memdir/findRelevantMemories.ts` does model-assisted memory file selection so only a few relevant memory files are surfaced per query.
- `src/tools/AgentTool/agentMemory.ts` gives spawned agents their own persistent memory scopes.

## BioAPEX Truth

BioAPEX already has the same three top-level concepts, but in slimmer forms.

### Tools

- `backend/tools/registry.py` already records typed manifest metadata for access scope, evidence requirement, compliance preflight, read-only, destructive, concurrency safety, helper-agent exposure, interrupt behavior, and summary hints.
- `backend/tools/contracts.py` gives tool results a normalized structured envelope.
- `backend/tools/policy_wrappers.py` enforces policy centrally around wrapped tools.

### Skills

- `backend/tools/skills_scanner.py` scans `SKILL.md` files, parses frontmatter, and writes `SKILLS_SNAPSHOT.md` for prompt inclusion.
- Skill sources are limited to the workspace `skills/`, configured extra dirs, and repo `.agents/skills/`.
- Skill loading is snapshot-based rather than a live dynamic registry.

### Memory

- `backend/graph/prompt_builder.py` injects `memory/MEMORY.md` directly into the system prompt when RAG mode is off.
- `backend/graph/memory_indexer.py` provides hybrid BM25 plus vector retrieval over only `memory/MEMORY.md`.
- `backend/graph/session_manager.py` persists rich session transcript blocks for tool use, retrieval, plan, and verification, but that is conversation state rather than durable user or project memory.

### Harness and Helper Agents

- `backend/runtime/query_engine.py` is already the main turn runtime boundary and now owns preflight, evidence gate handling, harness execution, helper-agent event extraction, and one bounded repair retry.
- `backend/runtime/helper_agent_runner.py`, `backend/tools/plan_agent_tool.py`, and `backend/tools/verification_agent_tool.py` already give BioAPEX explicit scoped helper-agent behavior.

## Verdict

BioAPEX is already similar in shape, but not yet in depth.

- Tools: mostly similar conceptually, partially similar in implementation depth.
- Skills: similar in basic file-based idea, not similar in discovery or activation sophistication.
- Memory: only partially similar. BioAPEX has one durable memory file plus optional retrieval, while the reference repo has a broader memory-directory architecture with scoped memory and selective recall.
- Harness: after the harness-first cleanup, BioAPEX is already fairly close to the reference repo's central query-runtime pattern.

## Best Things To Mimic

### 1. Promote tools from manifest metadata to tool-native capability contracts

BioAPEX should keep the current manifest fields, but push more behavior down to each tool so the runtime does not need to infer as much from override tables.

Highest-value additions:

- per-tool validation hooks
- per-tool permission checks
- explicit deferred-load or always-load behavior
- richer user-facing activity and result render hints
- classifier-friendly compact input descriptions

### 2. Upgrade skills from prompt snapshot to runtime registry

BioAPEX should keep `SKILL.md`, but make the system more dynamic.

Best pieces to borrow:

- source-aware skill registration with clear precedence
- dynamic discovery from touched paths or project subtrees
- conditional skills that activate only when matching files are in play
- plugin-provided or MCP-provided skills as first-class entries

### 3. Evolve memory from one file into indexed memory artifacts

The reference repo's biggest advantage here is not \"more memory\" but better structure.

Best pieces to borrow:

- keep `MEMORY.md` as a concise index rather than the full store
- store one memory per file with typed frontmatter
- support query-time selection of a few relevant memory files instead of retrieving only chunks from one long file
- add separate scopes when needed: user memory, project memory, and helper-agent memory

### 4. Keep helper agents explicit and scoped

BioAPEX should continue the current direction rather than copying the external repo's full agent sprawl.

What is worth copying:

- scoped tool exposure
- scoped transcripts or artifacts for helper lanes
- explicit worker roles with durable outputs

What is not worth copying:

- command explosion
- TUI-driven abstractions
- feature-flag sprawl

## Concrete Near-Term Recommendation

Because harness cleanup is already in place, the next useful mimicry order is:

1. Memory restructuring: move from a single `MEMORY.md` body to `MEMORY.md` plus per-memory files.
2. Skill runtime upgrades: conditional and dynamic skill discovery.
3. Tool contract upgrades: move policy and validation semantics closer to each tool implementation.

## Sources

- https://github.com/ponponon/claude_code_src
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/Tool.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/commands.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/skills/loadSkillsDir.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/memdir.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/findRelevantMemories.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools/AgentTool/agentMemory.ts
