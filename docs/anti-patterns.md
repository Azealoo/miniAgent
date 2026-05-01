# BioAPEX Anti-Patterns

A short list of approaches that look tempting but have been explicitly
rejected for BioAPEX. Each entry names a concrete anchor in the current
codebase so reviewers can spot regressions. If you find yourself moving
toward one of these, stop and raise it before the PR — the project has
already picked a different shape, and drifting back costs more than it
saves.

## 1. Regex-only permissions

**What it looks like.** Gating tool calls by matching command strings
against a regex allowlist (e.g. "allow anything matching `^git (status|diff)`").
Policy becomes a pile of patterns: fast to prototype, hostile to audit,
and trivially bypassed by argument rearrangement or shell quoting.

**Why it is rejected.** BioAPEX already carries a structured policy
model in `backend/tools/policy.py` and `backend/tools/registry.py`. Every
tool has a typed `ToolManifestEntry` with `access_scope`,
`evidence_requirement`, `read_only`/`destructive`/`concurrency_safe`
flags, planner/verifier exposure, a `SandboxSpec` with
`allowed_file_roots`/`network_scope`/`allowed_hosts`, and an optional
`requires_approval` gate. `evaluate_pre_tool_policy` and
`evaluate_sandbox_arguments` decide allow / needs-approval / blocked
from those fields; runtime results are annotated with the same metadata
via `annotate_tool_result`. Skills narrow the surface further through
the `tools_allowed` union enforced in
`_first_skill_tools_allowed_violation`.

**Do instead.** Extend the manifest. New constraints belong as new
fields on `ToolPolicyMetadata` / `SandboxSpec` with explicit checks in
`policy.py`, so the decision is typed, auditable, and visible in the
`policy` block attached to every tool result. If a string-level check is
genuinely needed, it lives as one field inside a manifest entry — never
as the sole gate.

## 2. Single-phase compaction

**What it looks like.** One threshold, one rewrite. When the session
history nears the token budget, hand the whole transcript to the LLM and
ask for a summary. Cheap turns pay a full round-trip; every compaction
costs the same regardless of pressure.

**Why it is rejected.** `backend/runtime/compaction.py` implements a
four-rung progressive ladder (issue #82): **snip** (≥0.60, no LLM,
drops the oldest exchange), **microcompact** (≥0.75, no LLM, drops the
oldest ~25%), **collapse** (≥0.85, LLM rewrite of the oldest ~50%),
**autocompact** (≥0.95, LLM rewrite of the entire live history).
`PHASE_ORDER` is evaluated descending so the most aggressive qualifying
phase wins, `PHASE_MIN_MESSAGES` keeps tiny sessions from thrashing, and
the chosen phase is persisted as `context_compression_phase` and
emitted on `compaction_event`. A single-threshold design discards that
graduated cost curve and the observability it produces.

**Do instead.** Tune the existing ladder. Add or adjust rungs by
editing `PHASE_THRESHOLDS`, `PHASE_MIN_MESSAGES`, `PHASE_ORDER`, and
`_messages_to_archive` — and keep `session_manager.compress_history`
(`compressed_context` + `compressed_archive_index`) in sync so
`load_archived_history` stays recoverable. New phases should declare
whether they use the LLM and emit their phase name on the compaction
event.

## 3. `bash` / `python_repl` as default execution

**What it looks like.** Treating `python_repl` (or a generic shell tool)
as the primary way to "get things done" — running file I/O, HTTP,
migrations, or data transforms through arbitrary Python strings because
it is the path of least resistance.

**Why it is rejected.** `backend/tools/python_repl_tool.py` exists as a
defence-in-depth escape hatch, not a front door. It carries its own
pre-execution scanner (`_BLOCKED_NATIVE_MODULES`, `_BLOCKED_OS_PROCESS_FUNCTIONS`,
`is_secret_like_path`, sensitive-path lists), output truncation at
`_MAX_OUTPUT`, and `scoped_environment` masking — all of which exist
*because* arbitrary code execution has none of the guarantees a
typed, policy-wrapped tool provides. The comment at the top of the file
states it plainly: "not a complete sandbox; use it alongside the other
tool safeguards." The surrounding registry publishes purpose-built
tools (file read/write, artifact I/O, memory, skills, workflow runners
— see `README.md` "Tools") with explicit `access_scope`,
`evidence_requirement`, `artifact_refs`, and planner/verifier visibility.

**Do instead.** Reach for the purpose-built tool first. If none fits,
add one: a small module under `backend/tools/` with a proper manifest
entry is almost always cheaper to review, test, and trace than a block
of REPL code that performs the same work. Use `python_repl` only for
genuinely ad-hoc exploration the user has asked for, and never as the
default execution surface inside an automated plan.
