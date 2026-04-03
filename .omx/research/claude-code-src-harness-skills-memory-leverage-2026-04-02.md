# Claude Code Source Harness Skills Memory Leverage

## Date

2026-04-02

## Question

Compared with the current BioAPEX backend, what can we learn from `ponponon/claude_code_src` in three areas:

- harness engineering
- skills
- memory

Also, where can we leverage BioAPEX's existing code instead of copying the reference repo literally?

## External Snapshot

Inspected `ponponon/claude_code_src` `master` at commit `adb321f6a3af4e0b76a1e076168bd521e9ba20af`, corresponding to the recovered `2.1.88` source release published on 2026-04-01.

Relevant upstream files:

- `src/QueryEngine.ts`
- `src/Tool.ts`
- `src/tools.ts`
- `src/skills/loadSkillsDir.ts`
- `src/skills/bundledSkills.ts`
- `src/memdir/memdir.ts`
- `src/memdir/findRelevantMemories.ts`

## Current BioAPEX Snapshot

Relevant backend files reviewed:

- `backend/runtime/query_engine.py`
- `backend/runtime/chat_runtime.py`
- `backend/runtime/turn_ledger.py`
- `backend/runtime/helper_agent_runner.py`
- `backend/api/chat.py`
- `backend/graph/agent.py`
- `backend/graph/prompt_builder.py`
- `backend/graph/memory_indexer.py`
- `backend/graph/session_manager.py`
- `backend/tools/registry.py`
- `backend/tools/policy.py`
- `backend/tools/policy_wrappers.py`
- `backend/tools/skills_scanner.py`
- `backend/tools/write_file_tool.py`
- `backend/api/files.py`

## Executive Read

The short answer is:

- harness engineering: BioAPEX is already fairly close in architecture and should continue its current engine-first cleanup rather than reinventing itself
- skills: upstream is materially ahead in discovery and activation behavior
- memory: upstream is materially ahead in structure and selective recall

The best BioAPEX move is not to clone the reference repo. It is to extend the code we already have:

1. keep `QueryEngine` and `ChatRuntime` as the center of the turn harness
2. turn the current skill scanner into a true runtime skill registry
3. turn `memory/MEMORY.md` from the whole memory store into an index over typed memory files

## Area Comparison

### 1. Harness Engineering

#### What upstream does well

`src/QueryEngine.ts` is the true center of the system. It owns:

- turn lifecycle
- accepted-message persistence
- system prompt assembly
- skill and plugin loading
- budget and usage tracking
- permission-denial tracking
- transcript mutation and compaction boundaries
- handoff into the model query loop

`src/Tool.ts` also makes tool behavior part of the contract rather than a side table. Tools can express:

- validation
- permission checks
- read-only vs destructive behavior
- interrupt semantics
- concurrency safety
- deferred or always-loaded visibility
- user-facing summaries and render behavior

#### What BioAPEX already has

BioAPEX is already on the right path:

- `backend/api/chat.py` is now thin transport
- `backend/runtime/chat_runtime.py` owns stream orchestration, persistence timing, observability, and title generation handoff
- `backend/runtime/query_engine.py` owns preflight, evidence gate handling, helper-agent extraction, and bounded repair logic
- `backend/runtime/turn_ledger.py` gives us explicit persisted turn segments and typed blocks
- `backend/runtime/helper_agent_runner.py` already supports scoped helper agents
- `backend/tools/registry.py` already records `read_only`, `destructive`, `concurrency_safe`, `interrupt_behavior`, and helper exposure

#### What to learn

The main upstream lesson is not "make a giant runtime file." The real lesson is:

- keep one clear engine as the owner of turn state
- make tool semantics first-class
- let helper agents be layered roles, not hidden routing magic

#### What BioAPEX can leverage directly

We do not need a harness rewrite. We can build on:

- `ChatRuntime` as the transport-facing shell
- `QueryEngine` as the execution boundary
- `TurnLedger` plus `SessionManager` as durable turn provenance
- existing tool manifest fields in `backend/tools/registry.py`

#### Recommended harness follow-up

Near-term improvement should be evolutionary:

- move more prompt and per-turn runtime assembly behind `QueryEngine`
- keep route logic thin
- migrate more policy behavior from override tables toward tool-native methods
- keep planner and verifier explicit, scoped helper lanes

### 2. Skills

#### What upstream does well

`src/skills/loadSkillsDir.ts` is a real runtime skill system, not just a prompt snapshot. It supports:

- multiple skill sources with precedence
- project, user, managed, plugin, bundled, and MCP-provided skills
- dynamic discovery from touched paths
- conditional activation via path filters
- deduplication by canonical path
- per-skill frontmatter for tools, context, model, effort, hooks, and invocation behavior

`src/skills/bundledSkills.ts` also supports bundled skills with reference files that are extracted on first use, which lets skills carry durable helper material instead of only prompt text.

#### What BioAPEX already has

BioAPEX has a simpler but solid base:

- `backend/tools/skills_scanner.py` scans `SKILL.md` trees and parses frontmatter
- it already supports workspace skills, configured extra dirs, and repo `.agents/skills/`
- `backend/graph/prompt_builder.py` injects `SKILLS_SNAPSHOT.md` into the system prompt
- `backend/api/files.py` already exposes collected skill metadata
- `backend/tools/write_file_tool.py` already rescans skills automatically after skill writes

#### What to learn

The upstream advantage is runtime activation, not the markdown format itself. The useful lessons are:

- treat skills as registry entries, not only prompt text
- allow source precedence and deduplication
- activate skills conditionally when file context makes them relevant
- support skill-local assets or scripts without bloating the system prompt

#### What BioAPEX can leverage directly

We can evolve the current scanner into a registry instead of replacing it:

- keep `SKILL.md`
- keep existing frontmatter parsing
- keep `SKILLS_SNAPSHOT.md` as a rendered artifact for prompt inclusion
- use `collect_skill_entries()` as the seed for a live registry object

#### Recommended skills follow-up

Best next slice:

1. add optional `paths` or similar path-scoping frontmatter to backend skills
2. activate matching skills when touched files or directories intersect those scopes
3. preserve `SKILLS_SNAPSHOT.md` as the prompt-facing summary, but generate it from the runtime registry
4. optionally support skill-local `scripts/` or `assets/` directories so skills can point to reusable materials

### 3. Memory System

#### What upstream does well

Upstream's memory system is materially richer:

- `src/memdir/memdir.ts` treats `MEMORY.md` as an index, not the full memory store
- memories live as individual files with typed frontmatter
- memory directories are created by the harness so the model does not waste turns checking for them
- optional scopes exist for auto memory, team memory, and agent memory
- `src/memdir/findRelevantMemories.ts` selects only a few relevant memory files per query instead of dumping all memory into context

That gives it better structure, better recall control, and better room for scoped persistence.

#### What BioAPEX already has

BioAPEX has useful primitives but a much flatter model:

- `backend/graph/prompt_builder.py` injects the full `memory/MEMORY.md` when RAG mode is off
- `backend/graph/memory_indexer.py` builds hybrid retrieval over only `memory/MEMORY.md`
- `backend/tools/write_file_tool.py` already rebuilds the index after `memory/MEMORY.md` changes
- `backend/graph/session_manager.py` stores rich session continuity, summaries, and typed blocks that could feed future memory extraction

#### What to learn

The strongest lesson is structural:

- `MEMORY.md` should become an index
- durable memories should become separate typed files
- recall should select a few files or snippets, not only chunks from one large markdown document
- scopes matter: user memory, project memory, and helper/runtime memory should not all be the same thing

#### What BioAPEX can leverage directly

This is the area where we can reuse more than it first appears:

- keep `backend/graph/memory_indexer.py`, but teach it to scan many files instead of one file
- keep `prompt_builder`, but inject an index plus retrieval guidance rather than the whole memory body
- use `write_file_tool`'s existing memory write path and rebuild hook
- use `SessionManager` summaries and block history as candidate inputs for future memory distillation

#### Recommended memory follow-up

Best next slice:

1. redefine `memory/MEMORY.md` as a concise index
2. add a `memory/entries/` or scoped tree like `memory/user/`, `memory/project/`, `memory/reference/`
3. store one memory per file with frontmatter
4. extend `MemoryIndexer` to index those files and return file refs plus snippet text
5. add a lightweight relevance selector before retrieval injection so only a few memory files are surfaced per turn

## Adopt Adapt Skip

### Adopt

- engine-first ownership of turn state
- runtime skill registry with precedence
- indexed memory files with selective recall

### Adapt

- tool-native contracts, but built on top of our current manifest and wrapper system
- conditional skills, but keep `SKILL.md` and prompt snapshot artifacts
- memory scopes, but ground them in BioAPEX provenance and file-first artifacts

### Skip

- CLI and TUI-specific abstractions
- feature-flag sprawl
- giant monolithic modules as a style target
- command explosion for its own sake

## Priority Order

If BioAPEX wants the highest-value mimicry order now:

1. memory restructuring
2. runtime skill activation
3. tool-contract deepening inside the harness

Reason:

- harness work is already well underway and mostly aligned
- skills and memory are where the current backend still has the largest structural gap

## Sources

- https://github.com/ponponon/claude_code_src
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/QueryEngine.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/Tool.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/skills/loadSkillsDir.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/skills/bundledSkills.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/memdir.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/memdir/findRelevantMemories.ts
