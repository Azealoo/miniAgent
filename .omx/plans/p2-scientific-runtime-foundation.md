# P2 Scientific Runtime Foundation

## Goal

Adapt the strongest runtime patterns from `Azealoo/claw-code` into BioAPEX so the product becomes more explicit, policy-aware, and reproducible without regressing its scientific workflow, evidence, compliance, or observability behavior.

## Why This Phase Comes Next

- The research note in `.omx/research/claw-code-bioapex-architecture-map-2026-04-01.md` identified high-value runtime ideas worth borrowing.
- BioAPEX already has stronger scientific logic than `claw-code`, but its runtime contracts are still more implicit than they should be.
- The highest-value work is not a rewrite. It is a staged hardening pass that upgrades prompt assembly, tool metadata, session structure, policy enforcement, and config layering.

## Phase Rules

1. Use the Rust runtime ideas from `claw-code`, not the Python parity scaffold.
2. Keep all changes additive or backward-compatible unless an explicit migration is landed in the same slice.
3. Do not weaken BioAPEX's safety posture to mimic a generic coding harness.
4. Do not pause scientific product work for a full runtime rewrite.
5. Preserve these existing truths:
   - `tool_result.v1` remains the canonical tool-output contract
   - workflow events remain typed and inspectable
   - audit and observability records remain intact
   - access control remains conservative

## OMX Execution Order

1. Start a fresh OMX session for this phase and review the research note plus this plan.
2. Execute Slice 1 with `$executor`.
3. Run review on Slice 1 before opening Slice 2.
4. Repeat the same executor -> reviewer loop for Slices 2 through 5.
5. Use `$team` only if a slice cleanly splits into disjoint write sets.

## Slice 1 - Prompt Context And Tool Manifest Foundation

### Why This Slice Comes First

- It is the highest-leverage steal from `claw-code`.
- It improves transparency immediately.
- It does not require replacing LangChain or session storage.
- Later slices depend on a clearer prompt and tool metadata surface.

### File Ownership

- `backend/graph/prompt_builder.py`
- `backend/tools/__init__.py`
- `backend/tools/contracts.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_tool_output_contracts.py`
- optional new file:
  - `backend/tools/registry.py`

### Must Do

1. Extend prompt assembly beyond the current fixed six-component read so BioAPEX can discover bounded project instruction context without hardcoding every path.
2. Keep current prompt components intact while adding a safe discovery layer for project-scoped instruction files and optional git-state context.
3. Add a typed manifest or registry wrapper for existing tools that records:
   - tool name
   - short description
   - access scope
   - compliance/evidence requirements
   - output contract version
4. Keep `get_all_tools(...)` working while making manifest metadata inspectable in code and tests.
5. Do not change tool behavior yet beyond the metadata and prompt-context plumbing needed for later slices.

### Done Means

- prompt building remains backward-compatible for current BioAPEX workspace files
- bounded discovery exists for project instruction context
- tool metadata is explicit and typed instead of implicit list assembly only
- tests cover prompt discovery/budget behavior and tool-registry invariants

### Verification

- run the slice-specific verification commands in `p2-scientific-runtime-foundation-verification.md`

### Dependencies

- none

## Slice 2 - Session Schema vNext With Typed Content Blocks

### Why This Slice Comes Second

- BioAPEX already emits typed tool results and workflow events, but session persistence still stores flat role/content messages with sidecar arrays.
- A block-structured session shape will make replay, export, and inspection more truthful.

### File Ownership

- `backend/graph/session_manager.py`
- `backend/api/chat.py`
- `backend/api/sessions.py`
- `backend/tests/test_session_manager.py`
- `backend/tests/test_chat_streaming.py`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/test/app-shell.contract.test.tsx`

### Must Do

1. Introduce a new additive session format that supports ordered assistant blocks such as:
   - text
   - tool use
   - tool result
   - optional usage metadata
2. Keep existing session files loadable and preserve current history endpoints unless a compatible additive field is introduced.
3. Preserve `tool_result.v1` as the embedded tool-result payload instead of inventing a parallel output contract.
4. Keep streaming output and session history UI behavior compatible while enabling richer inspection later.
5. Ensure compression and archived-message behavior still work with the new schema.

### Done Means

- old sessions still load
- new sessions can persist typed blocks
- chat streaming and history retrieval do not regress
- frontend session/history consumers remain type-safe

### Verification

- run the slice-specific verification commands in `p2-scientific-runtime-foundation-verification.md`

### Dependencies

- Slice 1 should land first so the prompt and tool metadata surfaces are stable.

## Slice 3 - Tool Policy Middleware

### Why This Slice Comes Third

- Once tool metadata is explicit and session storage is richer, BioAPEX can add a real runtime policy layer rather than scattering special-case checks.

### File Ownership

- `backend/graph/agent.py`
- `backend/api/chat.py`
- `backend/tools/__init__.py`
- optional new files:
  - `backend/tools/policy.py`
  - `backend/tools/policy_types.py`
  - `backend/tools/policy_wrappers.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_compliance_preflight.py`
- `backend/tests/test_evidence_review.py`
- optional new file:
  - `backend/tests/test_tool_policy.py`

### Must Do

1. Add a pre-tool and post-tool policy layer around tool execution.
2. Use BioAPEX-native policy checks instead of generic coding-assistant hooks:
   - compliance preflight requirements
   - evidence-review requirements
   - provenance/artifact expectations
   - access-scope enforcement
3. Allow policy middleware to:
   - block execution before tool run
   - annotate results after tool run
   - surface warnings or structured policy outcomes in a stable way
4. Keep the existing streaming contract usable by the frontend, with additive policy metadata only.
5. Do not introduce hidden agent behavior; blocked or annotated tool outcomes must stay inspectable.

### Done Means

- tool policies are explicit middleware, not scattered special cases
- blocked or annotated outcomes are visible in stream events and stored history
- evidence/compliance gates remain truthful and testable

### Verification

- run the slice-specific verification commands in `p2-scientific-runtime-foundation-verification.md`

### Dependencies

- Slices 1 and 2

## Slice 4 - Layered Runtime Config

### Why This Slice Comes Fourth

- BioAPEX currently centers most runtime configuration in a single backend config file.
- The research pass showed that per-user, per-project, and local override layers are the right next step once runtime policy is explicit.

### File Ownership

- `backend/config.py`
- `backend/access_control.py`
- `backend/tests/test_config.py`
- `backend/tests/test_api_health.py`
- optional new files:
  - `backend/runtime_config.py`
  - `backend/runtime_config_types.py`

### Must Do

1. Add a layered config model with clear precedence, such as:
   - user
   - project
   - local override
2. Keep the existing `backend/config.json` behavior compatible while introducing the new config-reading path.
3. Make the new config capable of carrying:
   - prompt-context options
   - tool-policy settings
   - connector settings
   - access defaults
   - execution backend settings
4. Keep loaded-config provenance inspectable so BioAPEX can explain where a runtime setting came from.

### Done Means

- config precedence is explicit and tested
- current config behavior is not broken
- new runtime options can be introduced without turning `config.py` into an untyped catch-all

### Verification

- run the slice-specific verification commands in `p2-scientific-runtime-foundation-verification.md`

### Dependencies

- Slice 3 should define the first real policy/config consumers.

## Slice 5 - Runtime Verification And Hardening Sweep

### Why This Slice Comes Last

- The earlier slices add the new foundations.
- This slice proves the new foundations work together and closes the loop with explicit regression coverage.

### File Ownership

- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_tool_output_contracts.py`
- `backend/tests/test_session_manager.py`
- `backend/tests/test_chat_streaming.py`
- `backend/tests/test_config.py`
- `backend/tests/test_api_health.py`
- `frontend/src/test/app-shell.contract.test.tsx`
- `.omx/research/claw-code-bioapex-architecture-map-2026-04-01.md`
- `context/current-feature.md`

### Must Do

1. Add or tighten end-to-end regressions that cover the full runtime path:
   - prompt assembly
   - tool metadata
   - policy enforcement
   - session persistence
   - config precedence
2. Confirm frontend inspection paths stay truthful after the backend runtime changes.
3. Record the final verification verdict and any residual risk in the current feature log or follow-on plan notes.

### Done Means

- the verification suite proves the new runtime foundations work together
- no fake “done” state exists
- any deferred work is explicit

### Verification

- run the full verification set in `p2-scientific-runtime-foundation-verification.md`

### Dependencies

- Slices 1 through 4

## Non-Goals In This Phase

- replacing LangChain with a brand-new hand-written runtime loop
- building a generic plugin marketplace
- copying `claw-code`'s Python parity scaffold into BioAPEX
- changing BioAPEX into a generic coding assistant
- weakening execution protections to match danger-full-access defaults

## Suggested OMX Prompts

1. Slice 1 executor prompt:
   `Use $executor to implement Slice 1 from .omx/plans/p2-scientific-runtime-foundation.md. Keep the change additive, land prompt-context discovery plus a typed tool manifest foundation, and run the listed verification before handoff.`

2. Slice 2 executor prompt:
   `Use $executor to implement Slice 2 from .omx/plans/p2-scientific-runtime-foundation.md. Add a backward-compatible block-structured session format, preserve tool_result.v1, and verify session/chat/frontend contracts before handoff.`

3. Slice 3 executor prompt:
   `Use $executor to implement Slice 3 from .omx/plans/p2-scientific-runtime-foundation.md. Add explicit pre/post tool policy middleware using BioAPEX compliance and evidence rules, keep stream contracts additive, and run the required verification before handoff.`

4. Slice 4 executor prompt:
   `Use $executor to implement Slice 4 from .omx/plans/p2-scientific-runtime-foundation.md. Add layered runtime config with clear precedence while preserving existing config.json behavior, and verify the config/access paths before handoff.`

5. Slice 5 reviewer/hardening prompt:
   `Use $reviewer to verify Slices 1-4 against .omx/plans/p2-scientific-runtime-foundation-verification.md, identify any residual gaps, and only mark the phase ready when the runtime foundations are proven end-to-end.`
