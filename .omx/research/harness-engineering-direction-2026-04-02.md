# Harness Engineering Direction

Date: 2026-04-02

## Question

If BioAPEX should follow the architecture of `ponponon/claude_code_src`, what is the right backend lesson to copy?

## Short Answer

Copy the harness, not just the prompts.

The strongest pattern in `claude_code_src` is:

- one central conversation runtime (`QueryEngine`)
- one rich tool contract (`Tool.ts`)
- optional specialized subagents (`Plan`, `verification`, `general-purpose`) launched through an agent tool

That means the right BioAPEX direction is:

- a query/turn engine as the core harness
- explicit tool semantics and permission behavior
- planner and verifier as scoped helper agents or harness roles
- execution still centered on one main runtime

## What The Reference Repo Actually Does

### `QueryEngine`

`src/QueryEngine.ts` is the center of gravity.

It owns:

- turn lifecycle
- session state
- prompt/context assembly
- transcript persistence
- tool-call loop handoff to `query()`
- metrics and retry/error accounting

It also persists accepted user messages before the main model loop, which improves resumability.

### `Tool.ts`

`src/Tool.ts` is not a thin registry.

Tools expose rich runtime semantics, including:

- validation
- permission checks
- read-only vs destructive behavior
- concurrency safety
- interrupt behavior
- deferred loading
- result persistence/display rules

This is the main harness advantage. The model is not trusted to infer tool risk from names alone.

### `AgentTool`

`src/tools/AgentTool/runAgent.ts` shows that specialized agents are layered on top of the core runtime, not baked into the transport layer.

The harness gives each subagent:

- scoped tools
- scoped permissions
- scoped transcript handling
- optional isolated MCP/tool context
- tailored system prompts

### Built-in agents

`builtInAgents.ts` exposes:

- `general-purpose`
- `Plan`
- optional `verification`

The built-in `Plan` agent is explicitly read-only and uses exploration/search tools only.
The `verification` agent is also non-editing in the project directory and returns a concrete verdict.

## BioAPEX Implication

The previous backend recommendation should be refined:

- yes, BioAPEX still needs a central turn engine
- but the better match to the reference repo is not only stage-based orchestration
- it is a harness-first runtime where planning and verification are specialized capabilities living on top of the harness

## Recommended Backend Shape

### Core harness

- `backend/runtime/query_engine.py`
- owns the turn lifecycle, persistence, streaming, and tool/model coordination

### Rich tool contract

- replace the thin tool manifest with richer semantics
- planner and verifier should consume those semantics

### Agent tool / subagent runner

- add a BioAPEX equivalent of `AgentTool`
- allow the main runtime to invoke:
  - `plan`
  - `verification`
  - optionally `explore`

### Main execution path

- main general-purpose agent remains the executor
- it can call the planner first when the task is complex
- it can call the verifier after execution
- repair/replan loops can be driven by verifier output

## Concrete Recommendation

If choosing between:

1. a monolithic planner-executor-verifier pipeline entirely inside one route/runtime
2. a harness-first runtime with optional planner and verifier subagents

the reference repo argues for option 2.

That is the cleaner architecture to copy.
