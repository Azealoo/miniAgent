# AI Interaction Guidelines

## Communication

- Be concise, direct, and scientifically careful.
- Prefer correctness, provenance, and explicit uncertainty over speed or overconfident answers.
- Explain non-obvious implementation decisions briefly, especially when they affect reproducibility, safety, workflow behavior, or artifact structure.
- Ask before large refactors, architectural changes, schema changes, or anything that could alter the long-term direction of BioAPEX.
- Do not add features outside the current spec or current feature scope.
- Never delete files, artifacts, schemas, or workflow definitions without clarification.
- When biological, compliance, or safety assumptions are uncertain, surface the uncertainty explicitly instead of silently guessing.

## Mission Alignment

BioAPEX is not just a chat app. It is a transparent, file-first biologist-assistant system focused on:

- reproducibility
- provenance
- structured workflows
- explicit evidence
- compliance and safety gating
- auditable scientific outputs

When implementing features, optimize for these principles:

- Make the rigorous path the easiest path.
- Prefer structured artifacts over hidden logic or one-off text generation.
- Prefer explicit workflow state over implicit agent behavior.
- Prefer traceable evidence over unsupported synthesis.
- Prefer safe blocking behavior over risky silent execution.

## Prompt Budget and Eviction Policy

The system prompt assembled by `backend/graph/prompt_builder.py` is governed by
explicit per-section character budgets. Each section is truncated in place to
its own cap with a visible truncation marker. When the optional global cap
`prompt_budget.total_max_chars` is set (> 0), sections are dropped wholesale in
the order below — least load-bearing first — until the prompt fits.

| Priority (drop first → drop last) | Section | Source |
|---|---|---|
| 1 | `git_context` | working-tree snapshot (env/runtime gated) |
| 2 | `retrieved_memory` | RAG retrieval block |
| 3 | `scoped_memory` | typed-note index from `memory/{project,user,agent}/` |
| 4 | `memory_index` | curated `memory/MEMORY.md` |
| 5 | `project_instructions` | `AGENTS.md` / `CLAW.md` and referenced files |
| 6 | `skills_snapshot` | available-skills registry snapshot |
| 7 | `user_profile` | `workspace/USER.md` |
| 8 | `agents_guide` | `workspace/AGENTS.md` |
| 9 | `identity` | `workspace/IDENTITY.md` |
| 10 | `soul` | `workspace/SOUL.md` |

`SOUL`, `IDENTITY`, `USER`, and `AGENTS` are evicted only as a last resort.
The static Tool Result Error Contract guidance is pinned and never evicted.

### Configuration

Per-section budgets live under `prompt_budget` in
`backend/config.json` (and merge from any user/local layers). Defaults mirror
the historical hardcoded values, so behavior is unchanged when the block is
absent. Budget fields:

- `component_max_chars` — workspace component truncation cap
  (`SOUL/IDENTITY/USER/AGENTS`, plus the snapshot fallback file).
- `project_instruction_file_max_chars` /
  `project_instruction_total_max_chars` — per-file and combined caps for
  `AGENTS.md`/`CLAW.md` and their `@`-referenced context files.
- `git_context_max_chars` — cap for the working-tree snapshot block.
- `retrieved_memory_block_max_chars` /
  `retrieved_memory_item_max_chars` — outer block and per-item caps for the
  RAG retrieved-memory block.
- `scoped_memory_block_max_chars` — cap for the typed-note listing.
- `memory_index_max_chars` — tight cap for `memory/MEMORY.md`.
- `total_max_chars` — optional global ceiling. `0` disables eviction (only
  per-section caps apply).

Existing env overrides (`BIOAPEX_PROMPT_INCLUDE_GIT_CONTEXT`,
`BIOAPEX_PROMPT_MEMORY_STALE_DAYS`) and the streaming/session contracts are
unchanged.

## Workflow

This is the default workflow for every feature or fix:

1. **Document** - Define the task clearly in `@context/current-feature.md`.
2. **Scope** - Confirm which phase, spec, or feature file in `@context/features/` the task belongs to.
3. **Read Context** - Read the relevant backend, frontend, workflow, and feature-spec files before changing code.
4. **Implement** - Make the smallest complete change that satisfies the current feature.
5. **Preserve Contracts** - Keep existing API behavior, streaming behavior, file layouts, and session compatibility unless the feature spec explicitly changes them.
6. **Verify** - Validate the work using the most relevant checks for the change:
   - backend tests when backend logic changes
   - frontend build/lint when frontend code changes
   - manual flow verification when chat, streaming, workflow, or artifact behavior changes
7. **Review Outputs** - Check that artifacts, logs, and user-visible behavior are understandable and traceable.
8. **Iterate** - Fix issues before proposing completion.
9. **Mark Progress** - Update `@context/current-feature.md` when the work is complete or meaningfully advanced.
10. **Commit Only With Permission** - Never commit unless explicitly asked, and only after verification passes.

Do not commit without permission. If verification fails, fix the issue first or clearly explain the blocker.

## Scientific and Product Rules

- Do not implement biology-facing features as opaque prompt behavior when they should be structured workflows or artifacts.
- Do not bypass compliance, safety, or data-governance checks for convenience.
- Do not present unsupported biological claims as established facts.
- Do not hide important run context in chat text when it should live in a file, artifact, schema, or log.
- Preserve file-first transparency: outputs should be inspectable on disk whenever practical.
- Prefer machine-readable records for workflows, evidence, compliance, and QA whenever the feature touches those areas.

## Branching

- Create a new branch for each feature or fix when asked to use a branch-based workflow.
- Use clear names such as `feature/<name>` or `fix/<name>`.
- Keep branch scope focused to one feature or one fix.
- Do not delete branches automatically after merge unless explicitly requested.

## Commits

- Ask before committing.
- Use conventional commit messages such as `feat:`, `fix:`, `chore:`, `docs:`, or `test:`.
- Keep commits focused and reviewable.
- Never include tool branding or "Generated With Claude" style text in commit messages.

## When Stuck

- If an approach fails after a few grounded attempts, stop and explain the issue clearly.
- Do not keep trying random fixes that weaken the architecture or reduce traceability.
- If requirements are unclear, ask for clarification before making irreversible design choices.
- If a requested change conflicts with reproducibility, safety, or workflow integrity, pause and explain the tradeoff.

## Code Changes

- Make minimal, targeted changes that solve the current problem completely.
- Do not refactor unrelated code unless the refactor is necessary for correctness or the user asks for it.
- Preserve existing codebase patterns unless the feature spec intentionally introduces a new pattern.
- Keep backward compatibility in mind for:
  - session files
  - streaming event contracts
  - artifact paths
  - skill loading behavior
  - file API assumptions
- Prefer explicit schemas and typed structures when the feature introduces new durable outputs.

## Code Review

Review AI-generated code periodically, especially for:

- scientific correctness and unsupported biological claims
- safety and compliance gaps
- provenance completeness and missing audit trails
- security issues such as unsafe execution or weak path validation
- logic errors and edge cases
- workflow determinism and hidden state
- compatibility with the existing backend/frontend architecture
- whether outputs should be artifacts instead of only chat text
