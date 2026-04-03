# Claw Code UX Benchmark For BioAPEX

Date: 2026-04-01
Analyst: Codex
Source repo: https://github.com/Azealoo/claw-code
Source commit inspected: `7030d26e7a9ca7fef5c74f463eede01a59403847`

## Question

If `claw-code` is the UX gold standard Johnny wants to move toward, what should BioAPEX actually borrow from it?

## Executive Summary

BioAPEX should borrow the interaction contract from `claw-code`, not the literal terminal look.

The strongest pattern in `claw-code` is:

1. show compact, honest live activity while a turn is running
2. keep the final answer clean once the turn is done
3. preserve full structured truth in a secondary inspectable surface
4. make agent capabilities and session state discoverable on demand

For BioAPEX, that becomes:

- a compact live turn-activity feed in chat while streaming
- a quiet final transcript after completion
- a block-driven turn-details surface in inspector/workspace history
- severity-based compliance visibility instead of always-on compliance cards
- better quick-action and status discoverability without weakening scientific rigor

The key implementation insight is that BioAPEX already has much of the required data model. The main gap is UX composition, not missing runtime structure.

## Evidence From Claw Code

### 1. Live turn telemetry is explicit and compact

Relevant files:

- `rust/crates/claw-cli/src/app.rs`
- `rust/crates/claw-cli/src/render.rs`

What it does:

- opens a visible stream state immediately
- shows tool execution as a first-class event
- renders tool completion separately from the final assistant text
- uses compact progress affordances instead of flooding the final transcript

What BioAPEX should learn:

- live activity should feel like a running process, not like permanent chat clutter
- tool activity deserves a stable visual grammar of its own

### 2. Session truth is block-structured

Relevant files:

- `rust/crates/runtime/src/session.rs`
- `rust/crates/runtime/src/conversation.rs`

What it does:

- stores assistant output as ordered content blocks
- distinguishes `text`, `tool_use`, and `tool_result`
- keeps the runtime loop event-oriented instead of reducing everything to plain text

What BioAPEX should learn:

- the transcript is only one projection of a turn
- the real source of truth should be a structured turn model that can drive transcript, inspector, export, and replay views differently

### 3. Older context is compacted without losing continuity

Relevant file:

- `rust/crates/runtime/src/compact.rs`

What it does:

- summarizes older conversation into bounded context
- preserves recent messages verbatim
- keeps the resumed conversation feeling continuous instead of bloated

What BioAPEX should learn:

- history surfaces should become denser over time
- old turns should collapse into summaries and counts, while detailed truth remains inspectable

### 4. State and capability discovery are first-class

Relevant files:

- `rust/crates/commands/src/lib.rs`
- `rust/crates/claw-cli/src/input.rs`

What it does:

- gives users clear command discovery
- exposes status, config, memory, agents, skills, plugins, and session operations
- treats operational visibility as part of the product, not a debug-only afterthought

What BioAPEX should learn:

- modern agent UX is not only about thinking indicators
- users trust agents more when they can discover what the system can do and what context it is using

## Current BioAPEX Truth

BioAPEX already has several foundations that make this upgrade easier than it looks.

### 1. Live chat telemetry already exists

Relevant files:

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/ThoughtChain.tsx`

Current behavior:

- live retrieval, workflow, and tool activity can render during streaming
- completed compliance can remain visible after the turn
- the chat is already moving toward a cleaner final transcript

### 2. Additive block-based session history already exists

Relevant files:

- `backend/graph/session_manager.py`
- `backend/api/chat.py`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`

Current behavior:

- BioAPEX already defines session content blocks for:
  - `text`
  - `tool_use`
  - `tool_result`
  - `retrieval`
  - `workflow_event`
  - `usage`
- the backend can derive legacy fields from blocks and validate/load them additively
- the frontend already validates and types those blocks

Implication:

- BioAPEX does not need to wait for a deep session rewrite before improving the UX
- the next UX phase can build on real structured turn data that already exists

### 3. Secondary truth surfaces already exist

Relevant files:

- `frontend/src/components/editor/InspectorPanel.tsx`
- `frontend/src/components/layout/WorkspacePanel.tsx`

Current behavior:

- files, sources, memory, skills, and usage already have inspectable homes
- compliance detail already has richer non-chat surfaces

Implication:

- BioAPEX already has the right product boundary for "clean transcript, deep inspectability"
- it mostly needs a more intentional split between those surfaces

## Gaps Between BioAPEX And The Target UX

### 1. The live turn surface is still fragmented

Today, retrievals, workflow progress, fallback activity, and tool traces are rendered through separate widgets.

This is functional, but it does not yet feel like one coherent "agent is working" timeline.

### 2. The final transcript policy is still evolving

BioAPEX has the right instinct to hide noisy live traces after completion, but the exact rule for what persists in main chat versus secondary surfaces still needs to be formalized.

### 3. Full turn truth is available but not yet productized

The `blocks` data already exists, but the UI does not yet present "turn details" as a first-class inspection surface equivalent to what modern agent users expect.

### 4. Capability and context discoverability are weaker than they should be

`claw-code` makes status, commands, memory, and configuration very discoverable. BioAPEX has some of that information, but it is more dispersed and less intentionally surfaced.

## Recommendation

BioAPEX should adopt a three-layer UX model:

### 1. Turn Surface

Purpose:

- show what is happening right now

Rules:

- show compact live rows for thinking, retrieval, tool execution, and workflow steps
- keep this surface ephemeral by default
- optimize for scanability, not archival completeness

### 2. Answer Surface

Purpose:

- show the user-facing result once the turn completes

Rules:

- persist only the final answer and action-affecting policy states
- remove retrieval/tool/workflow chatter from the main transcript after completion
- keep warning, approval-required, and blocked compliance states visible

### 3. Truth Surface

Purpose:

- preserve the full inspectable record

Rules:

- render the turn from session blocks when available
- include full tool details, retrieval evidence, workflow events, usage, and artifact pointers
- keep this available in inspector/workspace/session history rather than the main transcript

## What Not To Copy Literally

Do not copy these pieces from `claw-code` as-is:

- terminal spinner aesthetics
- developer-heavy slash command breadth
- generic coding-assistant defaults
- relaxed or developer-centric permission posture

BioAPEX should stay visibly scientific, provenance-rich, and safety-aware.

## BioAPEX-Specific UX Rules

1. Live activity is good when it is temporary.
2. Final answers should read like polished collaborator output, not raw telemetry.
3. Compliance belongs in the primary chat only when it changes interpretation or action.
4. Full runtime truth must remain inspectable outside the main transcript.
5. Quick actions should map to BioAPEX concepts like studies, evidence, files, workflows, and exports, not generic coding-only commands.

## Decision-Ready Conclusion

The next BioAPEX UX phase should not be "make the UI look like Claw."

It should be:

- build a unified live turn-activity feed
- make the final transcript cleaner and more rule-driven
- elevate block-driven turn details into a first-class secondary surface
- add better quick actions and status discovery
- keep compliance severity-based and scientific

That is the part of `claw-code` worth treating as the gold standard.
