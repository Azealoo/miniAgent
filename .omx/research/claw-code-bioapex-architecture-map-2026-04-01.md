# Claw Code -> BioAPEX Architecture Map

Date: 2026-04-01
Analyst: Codex
Source repo: https://github.com/Azealoo/claw-code
Source commit inspected: `7030d26e7a9ca7fef5c74f463eede01a59403847`

## Scope

Review `Azealoo/claw-code` for backend and runtime ideas that BioAPEX can reuse safely and productively.

This note focuses on:

- agent runtime structure
- prompt construction
- session schema
- tool registry and permissions
- config loading
- streaming/server boundaries

This note does not treat `claw-code` as a one-to-one blueprint for BioAPEX. BioAPEX is a scientific workflow product with evidence, provenance, and compliance requirements that are stricter than a general coding harness.

## Executive Summary

`Azealoo/claw-code` has two very different layers:

- The Python `src/` tree is mostly a mirrored porting scaffold. It is useful as a cataloging or parity-audit idea, but it is not the part to copy for BioAPEX runtime architecture.
- The Rust workspace contains the real architectural value. Its strongest patterns are a typed conversation schema, an explicit conversation runtime loop, a config hierarchy, a prompt builder that discovers repo instructions, and a manifest-driven tool registry with permissions.

For BioAPEX, the best ideas to borrow are not "generic agent tricks." The best ideas are the ones that make BioAPEX more inspectable, more policy-aware, and more reproducible.

## What To Reuse First

### 1. Prompt context discovery and budgeting

Borrow from:

- `rust/crates/runtime/src/prompt.rs`

Why it matters:

- It discovers instruction files along the directory ancestry chain.
- It deduplicates repeated instruction content.
- It enforces per-file and total prompt budgets.
- It includes a git status and diff snapshot.
- It renders runtime config into the prompt context.

Why this is valuable for BioAPEX:

- BioAPEX already uses file-first instructions, but prompt assembly is static and only reads a fixed set of components.
- BioAPEX would benefit from project-local scientific instructions, experiment-specific rules, and repo-local overrides without hardcoding every path.
- Git snapshots would improve provenance for code and workflow turns.

BioAPEX adaptation:

- Extend prompt building to scan project-level instruction files in a bounded way.
- Add optional git status/diff injection for developer or workflow-debug turns.
- Keep strict character budgets so evidence or workflow context does not get crowded out.

### 2. Typed session message blocks

Borrow from:

- `rust/crates/runtime/src/session.rs`

Why it matters:

- The session format distinguishes `text`, `tool_use`, and `tool_result` blocks.
- Usage is attached to assistant messages.
- The schema is explicit, versioned, and serializable.

Why this is valuable for BioAPEX:

- BioAPEX already has structured tool-result envelopes, but session history is still stored as role/content messages with optional sidecar arrays.
- A block-based session schema would make replay, export, audit, and UI rendering simpler and more truthful.
- It would fit BioAPEX's provenance-first model well.

BioAPEX adaptation:

- Add a new session schema version that stores assistant text and tool activity as ordered blocks.
- Keep backward compatibility with current session files and current frontend traces.
- Preserve current `tool_result.v1` payloads inside the new block format instead of replacing them.

### 3. Manifest-driven tool registry with explicit permission contracts

Borrow from:

- `rust/crates/tools/src/lib.rs`

Why it matters:

- Every tool has a name, schema, description, and required permission level.
- Allowed-tool filtering is normalized centrally.
- Plugin-provided tools are validated against built-ins.

Why this is valuable for BioAPEX:

- BioAPEX already has strong domain tools, but their runtime policy surface is more implicit than declarative.
- Scientific workflows need more than "can this tool run?" They need "under what compliance state may this tool run?"
- A manifest layer would improve inspection, testing, and future UI visibility.

BioAPEX adaptation:

- Add a typed registry wrapper around existing tools.
- Extend the manifest to include:
  - access scope
  - evidence requirement
  - compliance preflight requirement
  - artifact/output contract
  - reproducibility expectations

### 4. Pre-tool and post-tool policy hooks

Borrow from:

- `rust/crates/runtime/src/conversation.rs`
- `rust/crates/runtime/src/config.rs`

Why it matters:

- Tool execution runs through an explicit permission decision.
- Pre-tool hooks can deny or rewrite behavior.
- Post-tool hooks can annotate or block outputs.

Why this is valuable for BioAPEX:

- BioAPEX already has compliance and evidence gates, but those are still feature-specific rather than a generalized runtime policy layer.
- A hook pipeline would let BioAPEX enforce scientific policy consistently across tools.

BioAPEX adaptation:

- Do not copy the generic hook model verbatim.
- Recast it as policy middleware:
  - pre-tool: biosafety, privacy, sample-metadata completeness, provenance readiness
  - post-tool: artifact validation, evidence sufficiency, QA summary injection

### 5. Typed config hierarchy

Borrow from:

- `rust/crates/runtime/src/config.rs`

Why it matters:

- It merges user, project, and local settings with clear precedence.
- It parses typed config for hooks, plugins, MCP, OAuth, permissions, and sandboxing.
- It records which config files were loaded.

Why this is valuable for BioAPEX:

- BioAPEX currently has a narrower config surface centered around `backend/config.json`.
- Scientific deployments will likely need per-project policy, connector, and execution settings that are not global.

BioAPEX adaptation:

- Introduce a layered config model for project, workstation, and local overrides.
- Prioritize:
  - execution permissions
  - connector access
  - workflow execution backends
  - compliance defaults
  - evidence-review behavior

### 6. Compact explicit conversation runtime tests

Borrow from:

- `rust/crates/runtime/src/conversation.rs`

Why it matters:

- The file contains tight end-to-end tests for tool-use loops, denied tools, hooks, restored sessions, and compaction.
- The runtime loop is explicit and easy to reason about.

Why this is valuable for BioAPEX:

- BioAPEX uses LangChain's agent loop, which is productive but less explicit.
- More direct runtime-level tests would harden the most sensitive scientific behaviors.

BioAPEX adaptation:

- Keep LangChain if it is helping velocity.
- Add more runtime-shape tests around:
  - compliance blocking
  - evidence review requirements
  - workflow artifact emission
  - session replay and summary compaction

## What Not To Copy Directly

### Python `src/` runtime scaffold

Why not:

- It is mostly a clean-room parity workspace and inventory mirror.
- `src/query_engine.py` and `src/runtime.py` simulate routing and summaries rather than running a real production-grade agent backend.

Use only for:

- parity reporting ideas
- backlog/coverage tracking
- migration dashboards

### Default danger-full-access posture

Why not:

- BioAPEX should be conservative by default.
- Scientific execution often touches regulated data, HPC systems, or compliance-sensitive workflows.

### Generic plugin breadth before scientific core contracts

Why not:

- BioAPEX's immediate leverage comes from artifacts, evidence, and workflow gating.
- A plugin marketplace or broad extensibility layer is lower priority than making scientific runs inspectable and safe.

### Minimal session SSE server shape

Why not:

- BioAPEX already has a richer FastAPI streaming endpoint with observability and workflow events.
- The server crate is a useful simplification reference, but not a priority transplant.

## Best Mapping To Current BioAPEX

BioAPEX already has strong foundations that `claw-code` does not:

- domain-specific evidence and compliance tools
- structured tool output contracts
- workflow events
- audit and observability plumbing
- scientific product direction

The real opportunity is to combine BioAPEX's domain rigor with `claw-code`'s runtime explicitness.

That means:

- keep BioAPEX's scientific logic
- steal the runtime discipline
- avoid inheriting the generic coding-assistant defaults

## Recommended Order

1. Prompt builder upgrade
2. Tool registry manifest and permission/compliance surface
3. Session schema v2 with typed content blocks
4. Policy hook middleware for pre/post tool execution
5. Layered runtime config
6. Runtime-level end-to-end tests for tool/compliance/session loops

## Concrete First Slice

The best first implementation slice for BioAPEX is:

`Prompt Context + Tool Manifest Foundation`

That slice would:

- extend prompt assembly with bounded context discovery and optional git snapshotting
- define a typed manifest for every existing tool
- expose permission/compliance metadata for inspection and tests

Why start there:

- it is high leverage
- it does not require replacing LangChain
- it improves transparency immediately
- it sets up the later session-schema and hook work cleanly

## Local Comparison Notes

Current BioAPEX files inspected:

- `backend/graph/prompt_builder.py`
- `backend/graph/session_manager.py`
- `backend/graph/agent.py`
- `backend/api/chat.py`
- `backend/tools/__init__.py`
- `backend/tools/contracts.py`
- `backend/config.py`
- `backend/access_control.py`

Most notable current-vs-source gaps:

- BioAPEX prompt assembly is static where `claw-code` runtime prompt assembly is discovery-based.
- BioAPEX session storage is message-list based where `claw-code` Rust runtime uses typed blocks.
- BioAPEX has richer domain tool contracts than `claw-code`, but it lacks a central manifest-driven permission/config layer of the same clarity.
- BioAPEX already has stronger API streaming and observability than the simplified `claw-code` server crate.

## Bottom Line

If you want to "strictly use" ideas from `Azealoo/claw-code`, use the Rust runtime ideas, not the Python mirroring layer.

The highest-value steals for BioAPEX are:

- prompt discovery and budgeting
- typed session blocks
- manifest-driven tool metadata
- policy hooks around tool execution
- layered config loading

Those changes would make BioAPEX feel less like a chat app with scientific features attached and more like a true scientific runtime with an agent interface on top.
