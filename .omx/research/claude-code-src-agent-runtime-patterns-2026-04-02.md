# Claude Code Source Agent Runtime Patterns

## Question

What does `ponponon/claude_code_src` do around planning, execution, verification, and agent orchestration that BioAPEX should learn from?

## External Repo Truth

Primary-source inspection of `ponponon/claude_code_src` on 2026-04-02 shows:

- `src/QueryEngine.ts` is the central conversation runtime.
  - It owns per-conversation state, prompt assembly, transcript recording, budget checks, and stream normalization.
  - It persists accepted user messages before the main query loop, which improves resumability if a run dies mid-turn.
- `src/Tool.ts` defines a much richer runtime tool contract than BioAPEX currently has.
  - Tools declare schema, concurrency safety, read-only/destructive hints, permission checks, validation, rendering hooks, and auto-classifier input.
- `src/commands.ts` treats commands and skills as a first-class discovery layer.
  - Prompt-invocable skills are loaded from bundled, plugin, and directory sources and exposed through filtered skill registries.
- `src/tools/AgentTool/AgentTool.tsx`, `runAgent.ts`, and `builtInAgents.ts` show an explicit subagent runtime.
  - The repo can launch specialized agents such as `Explore`, `Plan`, and an optional `Verification` agent.
  - Spawned agents get scoped tools, scoped permissions, sidechain transcripts, cleanup hooks, and optional additive MCP servers.

## BioAPEX Truth

BioAPEX is not structured as explicit planner/executor/verifier agents today.

- `backend/api/chat.py` owns most turn orchestration directly.
- `backend/graph/agent.py` exposes one main conversational agent runtime.
- Planning-like behavior exists in deterministic routing and workflow preparation.
- Verification-like behavior exists in compliance preflight, evidence review gating, tool policy, QA outputs, and workflow publication blockers.

So BioAPEX already has planner/executor/verifier functions, but mostly as gates around one main runtime rather than as separate runtime workers.

## Recommendation

Borrow the shape, not the product surface.

1. Extract a central BioAPEX turn runtime.
   - Move more orchestration out of `backend/api/chat.py` and into a reusable `ChatTurnEngine` or equivalent.
   - Make the route a thin HTTP/SSE adapter rather than the place where all lifecycle logic lives.

2. Enrich the tool contract.
   - Extend BioAPEX tool metadata beyond access scope and evidence/compliance requirements.
   - Add concurrency-safety, read-only/destructive hints, validation hooks, normalized output contracts, and stronger user-facing summaries.

3. If BioAPEX adds explicit planner or verifier agents, copy the `AgentTool` boundary style.
   - Give spawned workers their own transcript/artifact namespace.
   - Scope their tools and permissions explicitly.
   - Keep lifecycle cleanup explicit.
   - Keep outputs inspectable and artifact-backed.

4. Do not copy the full command/feature-flag/TUI sprawl.
   - Claude Code's codebase is optimized for a coding-assistant shell product.
   - BioAPEX should preserve its scientific workflow, provenance, and inspectability boundary instead.

## Best Concrete Improvements For BioAPEX

- Highest value: extract the chat turn lifecycle from `backend/api/chat.py` into a central runtime object.
- Next highest value: make BioAPEX tools declare richer execution behavior so orchestration and safety can become less ad hoc.
- Optional later value: add explicit `planner` and `verifier` worker roles only for cases where they create durable artifacts or QA outputs.

## Caution

BioAPEX should not adopt hidden autonomous swarms as a default interaction model.

- The repo mission prefers structured workflows over hidden agent behavior.
- Any future planner or verifier worker should emit durable, reviewable artifacts rather than invisible intermediate reasoning.

## Sources

- https://github.com/ponponon/claude_code_src
- https://github.com/ponponon/claude_code_src/blob/master/src/QueryEngine.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/Tool.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/commands.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/tools/AgentTool/AgentTool.tsx
- https://github.com/ponponon/claude_code_src/blob/master/src/tools/AgentTool/runAgent.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/tools/AgentTool/builtInAgents.ts
