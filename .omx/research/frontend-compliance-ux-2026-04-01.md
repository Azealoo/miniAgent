# Frontend Compliance UX Recommendation

Date: 2026-04-01
Analyst: Codex
Question: Should BioAPEX show compliance in the main frontend if the goal is to feel closer to modern agent UX patterns like `Azealoo/claw-code`?

## Unknowns

- Does a modern agent-style UI normally keep compliance visible in the main transcript?
- Is `claw-code` actually a good frontend reference for this decision?
- What does BioAPEX's own product contract require?

## Repo Truth

### BioAPEX product contract

- `context/project-overview.md` says BioAPEX must "enforce safety and compliance gates" and must not treat biosafety, privacy, or human-subject concerns as optional warnings.
- The same file says the assistant should stream retrieval events, tool calls, workflow progress, and final outputs, but BioAPEX is still expected to be safe by default and auditable.

### BioAPEX current frontend shape

- `frontend/src/components/chat/ChatMessage.tsx` now shows live retrieval/workflow/tool trace while a response is streaming, then removes that noise from the final transcript.
- The same component still renders a compact `ComplianceSummaryCard` after completion when a compliance report exists.
- Richer compliance detail also already exists outside the primary chat surface:
  - `frontend/src/components/editor/InspectorPanel.tsx`
  - `frontend/src/components/layout/WorkspacePanel.tsx`
  - `frontend/src/components/compliance/ComplianceSummaryCard.tsx`

## External Truth

### `Azealoo/claw-code`

Source repo inspected:

- `README.md`
- `rust/crates/claw-cli/src/render.rs`
- `rust/crates/claw-cli/src/main.rs`
- `rust/crates/runtime/src/session.rs`
- `rust/crates/runtime/src/conversation.rs`

Observed patterns:

- `claw-code` is primarily a CLI/runtime reference, not a polished browser chat product.
- `render.rs` has a terminal spinner and compact status rendering, which supports the "show current work while running" pattern.
- `main.rs` tests show tool rendering is compact and display-oriented, and long tool output is truncated for presentation while the full result remains preserved in session state.
- `main.rs` also contains a test that raw `Thinking` blocks are ignored in rendered output, while final text and tool/session structure remain.
- `runtime/src/session.rs` and `runtime/src/conversation.rs` keep typed `text`, `tool_use`, and `tool_result` blocks as durable session truth.
- Repository-wide inspection did not surface a first-class compliance UI concept comparable to BioAPEX's compliance reports, approval states, or blocked scientific workflows.

## Assumptions

- `claw-code` is useful as a runtime/interaction-style reference, but not as a product-boundary reference for scientific safety UX.
- A generic coding harness can omit visible compliance because its product promise is different from BioAPEX's.

## Risks

1. Hiding compliance completely from the frontend would violate BioAPEX's stated product boundary, especially for blocked or approval-required turns.
2. Showing compliance on every successful turn in the main transcript makes BioAPEX feel heavier than modern agent products and dilutes the signal.
3. Copying `claw-code` too literally would optimize for coding-harness aesthetics over scientific safety and auditability.

## Recommendation

Do not treat compliance as a permanent default card in the main transcript for every turn.

Do keep compliance in the frontend, but make it severity-based:

1. `allow`
   - Do not show a main-chat compliance card by default.
   - Keep the full report in inspector/workspace/artifact surfaces.

2. `allow_with_warning`
   - Show a small inline warning chip or compact banner linked to details.
   - Avoid a large card unless the warning changes user action.

3. `require_approval`
   - Show a prominent inline gate or approval UI in the main surface before continuing.
   - This is core product behavior, not optional metadata.

4. `block`
   - Show a clear blocking state in the primary surface with the reason and next step.
   - Do not bury this only in a side panel.

## Decision

If the goal is "modern agent UX," BioAPEX should copy the live activity pattern from systems like `claw-code`, but not the absence of compliance.

The right frontend rule is:

- live execution detail during the turn
- clean final transcript after the turn
- compliance only escalates into the main surface when it materially changes what the user can do
- complete compliance detail stays available in secondary inspection surfaces and durable artifacts

## Open Questions

- Should `allow_with_warning` use a tiny badge under the final answer, or a top-of-turn banner above it?
- Should approvals happen inline in chat, or in a dedicated right-panel action card?
