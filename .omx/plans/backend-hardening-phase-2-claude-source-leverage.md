# Backend Hardening Phase 2: Claude Source Leverage

Date: 2026-04-02

## Goal

Leverage the remaining hardening-engineering patterns from `ponponon/claude_code_src` that still fit BioAPEX's chat-only backend.

When this phase is done, BioAPEX should have:

- an explicit hardening posture/profile instead of hidden development-first defaults
- a typed execution sandbox policy contract for network and filesystem restrictions
- high-risk tools enforcing that contract
- one reusable safety contract surface that runtime policy, helper agents, and audits can all read consistently

## Why This Phase Exists

- The engine-first cleanup already delivered most of the harness-side structure worth copying.
- Planner and verifier scoping are already substantially landed through:
  - `backend/runtime/helper_agent_runner.py`
  - `backend/tools/plan_agent_tool.py`
  - `backend/tools/verification_agent_tool.py`
  - `backend/tests/test_tools.py`
- The remaining leverage is mostly on the hardening side:
  - `backend/hardening.py` is still mostly boolean-oriented
  - `backend/runtime_config.py` has strong layering but no operator-facing provenance surface
  - `backend/tools/registry.py` is richer than before, but safety semantics are still partly central-override driven
  - BioAPEX still has no typed execution-policy contract comparable to `src/entrypoints/sandboxTypes.ts`

## Out Of Scope

- copying Claude Code's CLI/TUI command system
- adding feature-flag sprawl
- building a full OS sandbox implementation in one pass
- expanding the user-facing product surface beyond chat/files/sessions/access
- redesigning the existing planner/verifier helper-agent architecture unless a hardening slice directly requires it

## Must-Haves

- operators can inspect the effective hardening posture and config provenance
- shared or hosted posture is explicit rather than inferred from hidden defaults
- unsupported hardening guarantees fail closed instead of being silently accepted
- tool-safety semantics stay consistent across runtime policy, helper-agent scoping, and audit metadata

## Slice 1: Hardening Profile And Provenance Surface

### Likely Files

- `backend/hardening.py`
- `backend/config.py`
- `backend/runtime_config.py`
- `backend/runtime_config_types.py`
- `backend/api/access.py`
- `backend/tests/test_config.py`
- `backend/tests/test_chat_engine_health.py`
- `backend/docs/production-hardening.md`

### What This Slice Must Do

- add explicit hardening posture/profile semantics on top of the existing layered config system
- make the effective hardening posture and active config layers inspectable through a read-only backend surface
- keep local development behavior explicit rather than accidental
- keep malformed or partial hardening-profile config fail-closed

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_config.py tests/test_chat_engine_health.py -q`
- add focused assertions that the inspection surface reports active config layers and effective posture truthfully
- update `backend/docs/production-hardening.md` so the docs describe the actual resolved posture model

### Exit Criteria

- a caller can inspect the effective hardening posture
- config-layer provenance is surfaced somewhere truthful and stable
- config parsing fails closed on invalid posture/profile input

### Dependencies

- none

## Slice 2: Typed Execution Sandbox Contract

### Likely Files

- `backend/hardening.py`
- `backend/config.py`
- `backend/runtime_config.py`
- `backend/runtime_config_types.py`
- `backend/tools/policy_types.py`
- `backend/tools/registry.py`
- `backend/tests/test_config.py`
- `backend/tests/test_tool_policy.py`
- `backend/docs/production-hardening.md`

### What This Slice Must Do

- introduce a typed execution sandbox policy modeled after the useful parts of Claude Code's `sandboxTypes.ts`
- cover only guarantees BioAPEX can honor now, such as:
  - allowed domains
  - denied and re-allowed read paths
  - allowed and denied write paths
  - whether unsandboxed command execution is allowed
  - whether unavailable guarantees should fail closed
- reject or fail closed on policy fields that BioAPEX cannot yet enforce
- thread one normalized execution-policy object into the tool/runtime policy layer

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_config.py tests/test_tool_policy.py -q`
- add validation tests for accepted policy shapes, rejected policy shapes, and strict fail-closed behavior
- ensure existing manifest and policy annotation tests still pass

### Exit Criteria

- execution restrictions parse as a typed contract rather than ad hoc booleans
- the runtime exposes one normalized execution-policy object
- unsupported strict guarantees are not silently ignored

### Dependencies

- Slice 1

## Slice 3: Enforce The Contract On High-Risk Tools

### Likely Files

- `backend/tools/terminal_tool.py`
- `backend/tools/python_repl_tool.py`
- `backend/tools/write_file_tool.py`
- `backend/tools/fetch_url_tool.py`
- `backend/tools/http_json_tool.py`
- `backend/tools/policy.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_tool_policy.py`
- `backend/tests/test_audit_logging.py`
- `backend/docs/production-hardening.md`

### What This Slice Must Do

- enforce the new execution-policy contract on the highest-risk tools first
- cover:
  - domain restrictions for network-fetch tools
  - read/write path overlays for execution-capable and file-mutating tools
  - explicit allow/deny behavior for unsandboxed command execution
- preserve existing secret-path guards and session-scoped Python REPL isolation
- surface blocked decisions through the existing tool-result contract and audit metadata

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tools.py tests/test_tool_policy.py tests/test_audit_logging.py -q`
- add targeted domain/path/unsandboxed-policy tests for the affected tools
- keep the current chat/runtime/compliance sweep green after enforcement lands

### Exit Criteria

- the typed execution-policy contract materially changes runtime behavior on the targeted high-risk tools
- blocked attempts are visible in both result metadata and audit output
- existing hardening and runtime regressions remain green

### Dependencies

- Slice 2

## Slice 4: Consolidate The Tool-Native Safety Contract

### Likely Files

- `backend/tools/registry.py`
- `backend/tools/policy.py`
- `backend/runtime/helper_agent_runner.py`
- `backend/tools/contracts.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`

### What This Slice Must Do

- consolidate the current safety metadata into one reusable contract surface that stays close to tool definitions
- make runtime annotation, helper-agent catalogs, and future operator inspection read from that same contract snapshot
- preserve current planner/verifier scoping and keep destructive/read-only semantics consistent everywhere
- avoid copying Claude Code's rendering-heavy `Tool.ts` surface; keep only the hardening and execution semantics that benefit BioAPEX

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tools.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`
- keep helper-agent exposure tests green
- add or update contract-shape assertions so policy annotations and helper-agent catalogs cannot drift

### Exit Criteria

- one contract definition drives registry, policy, and helper-agent safety semantics
- planner/verifier scoping remains explicit and green
- contract metadata is no longer duplicated across loosely coupled tables and wrappers

### Dependencies

- Slice 2
- Slice 3

## Recommended Order

1. Slice 1: make posture and provenance explicit
2. Slice 2: define the typed execution-policy contract
3. Slice 3: enforce that contract on the highest-risk tools
4. Slice 4: consolidate the shared safety contract after enforcement proves the useful shape

## Done Means

- BioAPEX has copied the strongest remaining hardening ideas from `claude_code_src`
- the backend stays chat-engine-only and inspectable
- hosted/shared posture becomes clearer and safer without breaking local development by accident
- the plan/verifier helper architecture stays intact and is not needlessly reworked
