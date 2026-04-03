# Claude Code Source Hardening Leverage

Date: 2026-04-02

## Question

If BioAPEX's backend is already structurally close to `ponponon/claude_code_src`, what hardening-engineering patterns are still worth copying, and what is already close enough?

## Short Answer

Yes, there is still useful leverage.

The best remaining copy targets are:

- typed hardening profiles
- typed execution sandbox policy
- a more tool-native safety contract

The helper-agent boundary is already close enough that it should not be the next hardening priority.

## External Repo Truth

Primary-source inspection of `ponponon/claude_code_src` on 2026-04-02 showed:

- `src/Tool.ts` makes safety part of each tool contract.
  - tools declare `isConcurrencySafe`, `isReadOnly`, optional `isDestructive`, `interruptBehavior`, `validateInput`, and `checkPermissions`
  - the contract also carries user-facing summaries and deferred-loading semantics
- `src/entrypoints/sandboxTypes.ts` is a single typed schema for sandbox network and filesystem policy.
  - it includes domain allowlists, read/write allow-deny paths, and `failIfUnavailable`
- `src/tools/AgentTool/runAgent.ts` scopes subagent permissions and tool allow-lists explicitly.
  - workers do not just inherit broad parent permissions without a narrowing step
- `src/tools/AgentTool/builtInAgents.ts` keeps built-in `Plan` and optional `verification` agents narrow and feature-scoped rather than exposing the full tool surface everywhere

## BioAPEX Truth

BioAPEX already has meaningful hardening/harness pieces in place:

- `backend/tools/registry.py` already carries `read_only`, `destructive`, `concurrency_safe`, `interrupt_behavior`, `planner_exposed`, and `verifier_exposed`
- `backend/tools/policy.py` already annotates tool results with both policy state and contract metadata
- `backend/runtime/helper_agent_runner.py` already builds scoped planner/verifier catalogs from the same manifest surface
- `backend/tools/plan_agent_tool.py` and `backend/tools/verification_agent_tool.py` already consume those scoped catalogs
- `backend/access_control.py` already protects the loopback trust boundary better than the earlier comparison snapshot by refusing forwarded-header loopback trust unless the operator explicitly opts in
- `backend/runtime_config.py` already has the right layering seam: `defaults`, `user`, `project`, and `local`

## Main Remaining Gaps

### 1. Hardening policy is still mostly boolean-oriented

`backend/hardening.py` is clean, but most controls are still broad booleans:

- `terminal_enabled`
- `python_repl_enabled`
- `slurm_enabled`
- `write_file_enabled`
- `allow_loopback_without_auth`

That is good enough for coarse shutdown, but it is much thinner than the typed policy surface in `sandboxTypes.ts`.

### 2. Runtime config layering exists, but the effective posture is not inspectable

`backend/runtime_config.py` and `backend/runtime_config_types.py` can already tell us:

- which config layers exist
- which ones applied
- which keys came from each layer

But `backend/config.py` does not expose an operator-facing provenance or effective hardening-profile view yet. The config seam is stronger than the inspection surface built on top of it.

### 3. Tool safety semantics are richer, but still partly assembled from central overrides

`backend/tools/registry.py` is closer to Claude Code's `Tool.ts` than BioAPEX used to be, but the safety semantics still live primarily in:

- `_POLICY_OVERRIDES`
- default name-based sets such as `_READ_ONLY_TOOL_NAMES`
- wrapper-time annotation logic

That is useful, but it is not yet a clearly reusable hardening contract that operators, helper agents, audits, and UI inspection all consume as the same first-class object.

### 4. Helper-agent scoping is already good enough to de-prioritize

This part is not the urgent gap anymore.

Evidence:

- `backend/runtime/helper_agent_runner.py` already filters tools by planner/verifier exposure
- `backend/tests/test_tools.py` already verifies that planner/verifier scopes exclude `terminal` and `write_file`
- `backend/tools/plan_agent_tool.py` and `backend/tools/verification_agent_tool.py` already serialize scoped tool catalogs into their prompts

So if the next phase is hardening-oriented, it should not spend its first slice rebuilding planner/verifier scaffolding that is already substantially landed.

## Best Leverage To Copy Next

### 1. Named hardening profiles

BioAPEX should add explicit profile semantics on top of layered runtime config:

- `local_dev`
- `shared_hosted`
- `strict_hosted`

The point is not branding. The point is to make the effective trust posture explicit, inspectable, and testable.

### 2. Typed execution sandbox policy

BioAPEX should copy the `sandboxTypes.ts` idea, not necessarily the full OS-level sandbox implementation.

The immediate value is a typed contract for:

- allowed network domains
- denied and re-allowed read paths
- allowed and denied write paths
- whether unsandboxed command execution is allowed
- whether unavailable guarantees should fail closed

Any field BioAPEX cannot yet enforce should be rejected or treated as unavailable, not silently accepted.

### 3. Tool-native safety contract consolidation

BioAPEX should keep moving safety semantics closer to the tool contract so the same contract can drive:

- runtime policy
- helper-agent tool exposure
- audit annotations
- operator inspection
- future UI explanation

This is the strongest hardening lesson from `Tool.ts`.

## What Not To Copy Next

- the CLI/TUI-heavy product surface
- large feature-flag plumbing
- expansive built-in-agent catalogs
- settings that BioAPEX cannot honestly enforce

## Decision

BioAPEX should schedule a focused hardening phase that copies Claude Code's typed safety-contract ideas, not its shell-product complexity.

Priority order:

1. expose named hardening posture plus config provenance
2. add a typed execution sandbox policy contract
3. enforce that contract on the highest-risk tools
4. consolidate tool safety metadata into one reusable contract surface

## Sources

- https://github.com/ponponon/claude_code_src
- https://github.com/ponponon/claude_code_src/blob/master/src/Tool.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/entrypoints/sandboxTypes.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/tools/AgentTool/runAgent.ts
- https://github.com/ponponon/claude_code_src/blob/master/src/tools/AgentTool/builtInAgents.ts
