# Coding Standards

## Core Principles

- Optimize for reproducibility, provenance, transparency, and safety.
- Prefer explicit structured data over hidden runtime assumptions.
- Preserve file-first workflows whenever practical.
- Make scientific and operational behavior inspectable on disk.
- Favor deterministic behavior over clever but opaque abstractions.
- Do not introduce architecture that conflicts with BioAPEX’s mission as a transparent biologist-assistant system.

## Python

- Use clear, explicit typing where it improves correctness and maintainability.
- Avoid untyped dict-shaped data for durable artifacts when a schema or typed structure is more appropriate.
- Keep business logic separated from HTTP transport, UI concerns, and prompt wording.
- Prefer small, testable functions for parsing, validation, artifact generation, workflow state changes, and compliance logic.
- Do not rely on hidden mutable global state for workflow execution.
- Treat file paths, identifiers, run records, and compliance objects as structured data, not ad hoc strings.

## FastAPI and Backend Design

- Keep API routes thin and focused on validation, request shaping, and response formatting.
- Put workflow, artifact, provenance, compliance, and execution logic in backend modules rather than route handlers.
- Preserve backward compatibility for existing APIs unless a feature spec explicitly changes the contract.
- Keep SSE event contracts explicit and version-conscious.
- When adding new event types, define payload structure clearly and avoid ambiguous free-text parsing.
- Validate all request inputs before execution-capable tools or workflow steps run.
- Prefer fail-fast validation for malformed, incomplete, or unsafe inputs.

## Frontend and React

- Use functional components only.
- Keep components focused and readable.
- Preserve the existing frontend architecture unless a feature spec requires a change:
  - App Router structure
  - React Context state management
  - custom SSE streaming flow
- Do not add new client-side state libraries unless there is a strong architectural reason.
- Keep workflow, tool, and compliance state explicit in UI models instead of inferring them from rendered text.
- When a backend feature introduces new structured events or artifact states, update frontend types first or alongside the UI logic.

## TypeScript

- Prefer strict, explicit types for API responses, streaming events, artifact models, workflow records, and compliance objects.
- Avoid `any`. Use specific interfaces, discriminated unions, or `unknown` with narrowing.
- Model long-lived backend contracts directly in types instead of loosely typed objects.
- Use discriminated unions for event streams and state transitions when possible.
- Keep shared type definitions consistent with backend payload shapes.

## Files, Artifacts, and Schemas

- Every durable scientific output should have a clear on-disk representation.
- Prefer machine-readable artifacts for:
  - workflow runs
  - dataset manifests
  - evidence cards
  - compliance reports
  - QA reports
  - protocol runs
- Use versioned schemas for durable artifact types.
- Do not hide critical run state only in chat history or transient memory.
- Preserve stable naming, paths, and references once artifact conventions are established.
- Any file-writing feature should define:
  - where files live
  - how names are generated
  - how collisions are handled
  - how the artifact is referenced later

## Runtime Configuration

- Treat runtime configuration as frozen for the duration of a turn. The query
  engine captures a `RuntimeConfigSnapshot` at turn entry
  (`backend/config.py::snapshot_runtime_config`) and stamps the corresponding
  `_loaded_at` timestamp onto session metadata.
- Do not rewrite `backend/config.json`, `backend/config.local.json`, or
  `backend/runtime/hooks.py` while a turn is in flight. The file API
  (`backend/api/files.py`) rejects these writes with an explicit 403 so tool
  policy, hardening posture, and hook configuration cannot drift mid-turn.
- Operators who need to reload config during development can set
  `BIOAPEX_ALLOW_CONFIG_RELOAD=1` in the backend environment. The override is
  intentionally dev-only — production postures must never enable it.
- Treat `.env`-style files as always frozen. They remain off-limits to the
  file API regardless of the override.

## Workflow and Execution

- Prefer explicit workflow steps over free-form multi-tool behavior for repetitive scientific tasks.
- Make prerequisites, inputs, outputs, QC gates, and failure states explicit.
- Never rely on hidden REPL state as the source of truth for a workflow outcome.
- Execution-capable code must record enough context to reproduce or audit what happened later.
- Long-running work should emit structured state transitions, not only final summaries.

## Provenance and Evidence

- Any feature that produces analysis results, claims, or recommendations should preserve provenance.
- Scientific claims should be linked to evidence artifacts whenever the feature scope includes literature or biological interpretation.
- Store identifiers, versions, parameters, and source paths explicitly.
- Prefer normalized entity IDs over unstable free-text naming when integrating biology APIs or evidence layers.

## Safety and Compliance

- Compliance and safety checks must not be implemented only as prompt instructions when deterministic rules or structured review are more appropriate.
- Block or escalate risky actions before execution, not after.
- Treat privacy, human-subject, biosafety, and dangerous-procedure concerns as first-class engineering constraints.
- Prefer conservative defaults when the system cannot establish that an action is safe.

## Testing and Verification

- Add or update tests when changing backend logic, workflow behavior, validation rules, file-access rules, or artifact generation.
- Favor tests that verify behavior from artifacts and structured outputs, not only implementation details.
- For frontend changes, verify the build and any relevant state transitions.
- For backend changes, verify route behavior, workflow state handling, and compatibility with existing session and tool flows.
- When adding a new schema or artifact type, include validation examples or fixtures.

## Error Handling

- Return errors that are actionable and precise.
- Distinguish clearly between:
  - invalid input
  - blocked action
  - transient failure
  - execution failure
  - empty but valid result
- Do not swallow errors that matter for provenance, compliance, or workflow correctness.
- If a failure is intentionally non-fatal, document why and preserve enough context to debug it later.

## Code Quality

- Make minimal, targeted changes.
- Do not refactor unrelated code unless necessary for correctness or requested explicitly.
- Keep naming clear and domain-accurate.
- Remove dead code and unused imports.
- Do not leave commented-out code unless there is a documented short-term reason.
- Prefer readability over cleverness, especially in safety, workflow, and provenance logic.

## Project-Specific Guidance

- Respect the current backend/frontend split.
- Preserve compatibility with:
  - session files
  - skill loading
  - file API boundaries
  - current streaming chat flow
- Use existing biology-facing tools and skills as integration points before inventing parallel mechanisms.
- When extending the system, prefer building on:
  - `backend/api/`
  - `backend/graph/`
  - `backend/tools/`
  - `backend/skills/`
  - `backend/knowledge/`
  - `frontend/src/lib/`
- If a feature affects mission-critical behavior, update the corresponding spec in `context/features/` as part of the work.
