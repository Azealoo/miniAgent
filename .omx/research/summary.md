# OMX Runtime Summary

## 2026-04-02 Process-First Streaming Output Against Claude Code Src

### Question

After `P7`, what is the best BioAPEX-native way to stream output while keeping the current process-first display policy and learning from `ponponon/claude_code_src`?

### Recommendation

Keep SSE, but make the stream contract primary and the transport secondary.

- keep the current process-first rail above the answer
- define one typed live event grammar
- centralize optimistic stream reduction
- make the frontend consume live `plan` and `verification` events
- reduce duplicated block derivation across chat and inspector surfaces
- add event indexes only after the contract is stable

### Most Important Finding

BioAPEX's visual policy is already good; the mismatch is in the stream plumbing.

- `frontend/src/components/chat/ChatMessage.tsx` already preserves the process-first transcript
- `frontend/src/components/chat/TurnActivityFeed.tsx` and `frontend/src/components/editor/TurnDetailsPanel.tsx` already understand `plan` and `verification` blocks
- `frontend/src/lib/api.ts` still ignores live `plan_created`, `plan_updated`, and `verification_result`
- `frontend/src/lib/store.tsx` still updates live turns through callback-scattered logic rather than a stream-event reducer

### Detailed Note

- `.omx/research/process-first-streaming-output-against-claude-code-src-2026-04-02.md`

## 2026-04-02 Claude Code Source P6 Complete Leverage Check

### Question

Now that the backend has changed and P6 is complete, what is still worth leveraging from `ponponon/claude_code_src` in harness engineering, skills, and memory?

### Recommendation

Treat P6 as structurally complete and spend the next leverage pass on skills and memory semantics, not another runtime refactor.

- keep the current harness
- add path-aware skill activation
- expand the skill contract
- convert memory into typed files plus a compact index
- add lightweight memory distillation only after the file model is fixed

### Most Important Finding

The largest old P6 gap is now closed.

- `backend/tools/skills_scanner.py` is a real runtime registry
- `backend/graph/skill_router.py` already narrows skill context per turn
- `backend/graph/memory_indexer.py` already supports nested-file retrieval
- targeted verification passed with `102 passed, 3 skipped`

### Most Important Remaining Gap

BioAPEX still trails the reference repo most in conditional skills and memory discipline.

- BioAPEX still lacks `paths`-scoped skill activation like `src/skills/loadSkillsDir.ts`
- `backend/memory/MEMORY.md` still carries long-form durable content instead of behaving as a concise index
- `backend/graph/prompt_builder.py` still injects only `memory/MEMORY.md` when RAG is off
- there is still no background memory extraction or distillation path

### Detailed Note

- `.omx/research/claude-code-src-p6-complete-leverage-check-2026-04-02.md`

## 2026-04-02 Claude Code Source Harness Skills Memory Refresh

### Question

With the current P6 backend state, what is still worth leveraging from `ponponon/claude_code_src` in harness engineering, skills, and memory?

### Recommendation

Exploit the P6 gains instead of reopening the runtime.

- keep the current engine-first harness
- add path-aware and richer-contract skill activation
- finish memory as typed artifacts plus selective recall
- defer hook and plugin expansion until there is real product pressure

### Most Important Finding

BioAPEX has already reproduced the reference repo's most important P6 mechanics.

- `backend/tools/skills_scanner.py` is now a real runtime registry
- `backend/graph/skill_router.py` already narrows skill context per turn
- `backend/graph/memory_indexer.py` already supports multi-file, source-aware retrieval

### Most Important Remaining Gap

The real remaining delta is memory discipline and conditional activation, not harness architecture.

- `backend/graph/prompt_builder.py` still treats `memory/MEMORY.md` as the non-RAG prompt fallback
- BioAPEX still lacks typed memory artifacts and automatic memory distillation
- BioAPEX still lacks path-scoped conditional skill activation like the reference repo's `paths`-based skill loading

### Detailed Note

- `.omx/research/claude-code-src-harness-skills-memory-refresh-2026-04-02.md`

## 2026-04-02 Claude Code Source Streaming Runtime Comparison

### Question

How does `ponponon/claude_code_src` stream output compared with BioAPEX, and what should BioAPEX actually learn from it?

### Recommendation

Copy the stream architecture lessons, not the whole transport stack.

- keep SSE for the browser for now
- define one transport-neutral event schema behind it
- harden the framing boundary
- finish live handling for plan and verification events
- only add replay/resume transport complexity if remote long-lived sessions become a real product need

### Most Important Finding

`claude_code_src` is not mainly better because it uses SSE or WebSockets. It is stronger because it treats structured messages as the primary contract and transport as an adapter.

- `src/cli/structuredIO.ts` treats newline-delimited JSON as the base stream
- `src/utils/streamJsonStdoutGuard.ts` protects that stream from stdout corruption
- `src/cli/remoteIO.ts` and `src/cli/transports/SSETransport.ts` reuse the same message grammar across remote transports

### Most Important BioAPEX Gap

BioAPEX already emits richer live runtime events than the current browser client consumes.

- `backend/runtime/query_engine.py` emits `plan_created`, `plan_updated`, and `verification_result`
- `frontend/src/lib/api.ts` currently ignores those event types during live streaming
- `frontend/src/lib/store.tsx` therefore cannot show those blocks until after persisted reload

### Detailed Note

- `.omx/research/claude-code-src-streaming-runtime-comparison-2026-04-02.md`

## 2026-04-02 Claude Code Source Hardening Leverage

### Question

Now that the backend is structurally close to `ponponon/claude_code_src`, what hardening-engineering patterns are still worth copying?

### Recommendation

Copy the typed safety contracts, not more shell complexity.

- add explicit hardening posture/profile semantics
- add a typed execution sandbox policy contract
- enforce that contract on the highest-risk tools
- consolidate tool safety metadata into one reusable contract surface

### Most Important Finding

The biggest remaining leverage is hardening contracts, not helper-agent architecture.

- BioAPEX already has scoped planner/verifier tool exposure through `backend/runtime/helper_agent_runner.py`
- `backend/tools/registry.py` already carries read-only/destructive/concurrency and interrupt metadata
- the main remaining gap is that `backend/hardening.py` is still mostly boolean-oriented and `backend/runtime_config.py` provenance is not surfaced to operators

### Detailed Note

- `.omx/research/claude-code-src-hardening-leverage-2026-04-02.md`

## 2026-04-02 Chat-Only Cleanliness Review

### Question

Is the repo clean enough for a narrower product that keeps only chat, its tools, and the memory system?

### Recommendation

Changes requested before the next harness refactor.

- the backend app surface is close to chat-only
- the frontend shell is still multi-workspace and still models deleted backend product areas
- at least one backend read model is now orphaned
- verification is green for the broader shell, not yet for a strict chat-only product boundary

### Most Important Finding

The strongest remaining mismatch is frontend scope drift.

- `WorkspacePanel`, `Sidebar`, `workspace-data`, and `api.ts` still expose docs, studies, ops, artifacts, skills registry, tokens, observability, and connector flows
- `test_chat_engine_health.py` explicitly verifies that many of those backend routes are no longer part of the app surface

### Detailed Note

- `.omx/research/chat-only-cleanliness-review-2026-04-02.md`

## 2026-04-02 Backend Harness Leverage Follow-Up

### Question

After the latest backend cleanup, what should BioAPEX actively leverage from its current harness shape rather than immediately refactoring again?

### Recommendation

Exploit the engine-first seams that already landed.

- treat `QueryEngine` as the only ordinary-turn contract
- treat `TurnLedger` as the persisted transcript boundary
- use layered runtime config as the deployment/profile seam
- build future interrupt, helper-agent, and UI explanation work on the manifest-plus-policy contract

### Most Important Finding

The backend cleanup created a real leverageable center, not just a smaller codebase.

- `backend/app.py` is now chat-engine-only at the public route surface
- `backend/runtime/query_engine.py` owns ordinary turn flow
- `backend/runtime/turn_ledger.py` owns final assistant segment and block assembly
- `backend/tools/python_repl_tool.py` now scopes interpreter state by session instead of sharing one mutable REPL across all chats

### Most Important Remaining Gap

`backend/api/chat.py` is thinner, but it still behaves like a second orchestrator.

- it still owns SSE payload shaping
- it still owns pending-tool bookkeeping and tool audit emission
- it still owns final turn persistence and observability

### Detailed Note

- `.omx/research/backend-harness-leverage-follow-up-2026-04-02.md`

## 2026-04-02 T Cell Session Audit

### Question

Does the pasted `session.v3` history for the T-cell paper recommendation chat align with BioAPEX's intended tool-calling, evidence-review, transcript, and permission behavior?

### Recommendation

Treat the session as mostly correct on transcript structure, but not as a valid evidence-grounded success case.

- keep the current `blocks` plus legacy compatibility shape
- keep the quiet transcript split between live tool activity and final prose
- do not treat this session as proof that evidence-grounded ranking is working
- do not treat this session as a permission-flow validation sample

### Most Important Finding

The second turn's final answer is not actually grounded in the completed evidence review.

- the saved `evidence_review.json` includes only two evidence cards
- the included evidence identifiers do not match the three PMIDs named in the final answer
- the final prose still claims to be "based on my evidence review"

### Secondary Finding

There is a real metadata-ordering bug in the review path.

- `backend/api/chat.py` serializes the `evidence_review` tool result before flipping `review_completed = True`
- that can leave the saved tool result showing stale review state

### Permission Note

This transcript does not exercise approval-required behavior.

- both compliance preflights returned `allow`
- no approval override or access-scope denial occurred

### Detailed Note

- `.omx/research/t-cell-session-audit-2026-04-02.md`

## 2026-04-02 Claude Code Source Backend Comparison

### Question

What should BioAPEX learn from `ponponon/claude_code_src` on the backend/runtime side, and are there backend flaws in BioAPEX that need attention first?

### Recommendation

Borrow the reference repo's structure, not its full implementation.

- copy the narrow bootstrap pattern
- copy the central query-runtime pattern
- copy the richer tool-and-permission contract direction
- do not copy the CLI/TUI-heavy product surface or the feature-flag sprawl

### Most Important Finding

BioAPEX currently has a real backend flaw: Python REPL state is shared across sessions.

- `backend/graph/agent.py` creates the runtime tool list once in the singleton agent manager.
- `backend/tools/__init__.py` constructs one shared `PythonReplTool`.
- `backend/tools/python_repl_tool.py` keeps `_repl` as persistent mutable state.

That means the REPL lifetime is process-global, not session-scoped, so variables and imports can leak across chats and concurrent requests can race on the same interpreter state.

### Secondary Risk

BioAPEX's hardening defaults are still development-first.

- `backend/app.py` documents `--host 0.0.0.0`
- `backend/hardening.py` defaults `allow_loopback_without_auth=True`
- high-risk tools and file/connectors write surfaces are enabled by default

That is acceptable for trusted local use, but it should not be the hosted default posture.

### Detailed Note

- `.omx/research/claude-code-src-backend-comparison-2026-04-02.md`

## 2026-04-02 Claude Code Source Agent Runtime Follow-Up

### Question

Does `ponponon/claude_code_src` implement a stronger planner/executor/verifier pattern than BioAPEX, and what should BioAPEX actually copy?

### Recommendation

Copy the runtime boundaries, not the shell-product complexity.

- extract a central turn runtime from `backend/api/chat.py`
- evolve BioAPEX's tool manifest into a richer execution contract
- if explicit planner or verifier workers are added later, give them scoped tools, scoped permissions, and their own durable transcripts or artifacts

### Most Important Finding

`claude_code_src` is still centered on one core conversation runtime, but it also has a real subagent layer that BioAPEX does not currently expose.

- `src/QueryEngine.ts` owns the conversation lifecycle.
- `src/Tool.ts` defines a rich runtime tool contract.
- `src/tools/AgentTool/*` can launch specialized agents like `Plan`, `Explore`, and an optional `Verification` agent.

### BioAPEX Implication

BioAPEX does not need to become a hidden-swarm system.

- The strongest thing to copy is the central runtime boundary.
- The next strongest thing to copy is the richer tool contract.
- Explicit planner or verifier workers only make sense for BioAPEX if they stay artifact-backed and reviewable.

### Detailed Note

- `.omx/research/claude-code-src-agent-runtime-patterns-2026-04-02.md`

## 2026-04-02 Planner Executor Verifier Runtime Direction

### Question

How should BioAPEX change if the main product goal is an explicit planner -> executor -> verifier loop rather than workflow-centric execution?

### Recommendation

Make planning first-class, not implicit.

- keep a central turn engine
- add a structured plan artifact before broad tool use
- make execution step-aware
- add an explicit verifier that can trigger one repair or replan loop
- keep workflows out of the center of ordinary chat turns

### Most Important Finding

The previous simplification recommendation was too aggressive for this goal.

- The user does not want planning removed or hidden.
- The real target is a governed tool-using loop where execution is accountable to a plan.
- BioAPEX therefore needs a stronger planning contract, not just a thinner route.

### What To Copy From `claude_code_src`

- copy the central runtime idea from `QueryEngine`
- copy the richer tool contract direction from `Tool.ts`
- do not copy hidden complexity or make subagents mandatory in the first pass

### Durable Plan

- `.omx/plans/backend-plan-execute-verify-runtime.md`
- `.omx/plans/backend-plan-execute-verify-runtime-verification.md`

## 2026-04-02 Harness Engineering Direction

### Question

If BioAPEX should more closely follow `ponponon/claude_code_src`, what is the architectural lesson to copy?

### Recommendation

Follow the harness architecture.

- central query engine first
- rich tool contract second
- planner and verifier as scoped helper agents or harness roles
- do not make planner/verifier only a route-local control flow pattern

### Most Important Finding

The real strength of the reference repo is not just staged orchestration.

- `QueryEngine.ts` owns the full turn lifecycle
- `Tool.ts` defines strong tool semantics
- `runAgent.ts` lets the harness launch scoped specialist agents
- built-in `Plan` and `verification` agents are layered on top of that harness

### BioAPEX Implication

The best match for BioAPEX is a harness-first backend where the main executor can invoke planning and verification helpers, rather than burying all planning logic inside a single route or a purely monolithic stage pipeline.

### Detailed Note

- `.omx/research/harness-engineering-direction-2026-04-02.md`

## 2026-04-02 Access-Control Proxy Trust Follow-Up

### Question

Was the remaining access-control concern only a hosted-deployment recommendation, or was there a concrete backend trust flaw worth fixing now?

### Recommendation

Treat proxied loopback traffic as remote by default.

- keep direct localhost development behavior
- stop granting unauthenticated loopback access when forwarded-client headers are present
- allow operators to opt back in only with an explicit hardening-policy flag

### Most Important Finding

The prior loopback-or-bearer contract had a real same-host proxy trust hole.

- `backend/access_control.py` trusted `request.client.host` alone.
- BioAPEX had no proxy-aware middleware or forwarded-header safety check.
- In a same-host reverse-proxy deployment, remote traffic could appear as loopback to the app and inherit the local bypass unintentionally.

### Landed Mitigation

- Added `production_hardening.api.trust_forwarded_loopback_headers` with a safe default of `false`.
- Requests carrying `Forwarded`, `X-Forwarded-For`, or `X-Real-IP` now fall back to bearer-token auth unless that new flag is explicitly enabled.
- Direct localhost requests without forwarded-client headers still keep the existing loopback development path.

### Residual Risk

- A proxy that hides or strips forwarded-client headers can still make remote traffic look local.
- BioAPEX still needs a later hosted-profile slice to tighten other dev-first defaults more aggressively.

### Verification

- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py tests/test_config.py -q -k "access_probe or production_hardening_policy"`
- Result: `9 passed, 77 deselected`

## 2026-04-02 Frontend Structure And Dead-Code Review

### Question

Is the current BioAPEX frontend in a good structural state, what dead code can be removed safely now, and what should BioAPEX mimic from `ponponon/claude_code_src`?

### Recommendation

Keep this pass targeted, and copy the reference repo's boundaries rather than its file sizes.

- remove confirmed dead code now
- keep composer quick starts draft-based unless workflow preselection is intentionally reintroduced
- treat `WorkspacePanel`, `InspectorPanel`, and `OpsWorkspace` as the next extraction boundaries if a second cleanup pass is wanted

### Most Important Finding

The frontend has a real concentration problem plus some confirmed dead branches.

- `WorkspacePanel`, `InspectorPanel`, `OpsWorkspace`, and `store.tsx` carry too much mixed responsibility
- strict TypeScript checks found stale props, helpers, and imports that were no longer part of the active flow
- four chat components were completely unreferenced and removable without breaking tests or build

### External Comparison Note

`claude_code_src` is useful as a boundary reference, not as a small-file reference.

- its `src` tree is organized around domain folders like `components`, `screens`, `state`, `services`, and `tools`
- it still contains very large entry files
- BioAPEX should mimic the domain split, not the raw file sizes

### Detailed Note

- `.omx/research/frontend-structure-cleanup-2026-04-02.md`

## 2026-04-01 General Biology Agent Direction

### Question

Should BioAPEX keep steering users into named workflows, or shift toward a general biology agent where the user can ask questions directly and the system chooses tools as needed, while still learning from `Azealoo/claw-code`?

### Recommendation

Shift BioAPEX to `general biology agent first, workflow second`.

- Keep workflows as optional structured execution paths.
- Do not rebuild the backend around Claw.
- Do change the frontend so asking a biology question becomes the default path.

### Repo Truth

- `backend/api/chat.py` already supports general chat turns because `selected_workflow` is optional and the generic agent path runs whenever no workflow is selected.
- `frontend/src/components/chat/ChatInput.tsx` and `frontend/src/components/layout/workspace-data.ts` still make workflows feel like the primary product mode through the composer, quick actions, and `Flows` navigation.
- `backend/graph/session_manager.py` already has typed session blocks for text, tool use/result, retrieval, workflow events, and usage.
- `backend/graph/prompt_builder.py` already implements bounded instruction discovery and optional git context.
- `backend/tools/registry.py` already exposes manifest-like tool policy metadata.

### External Truth

Primary-source inspection of the live `Azealoo/claw-code` repo on 2026-04-01 confirmed:

- the Rust workspace is the main architectural value
- the strongest reusable patterns are:
  - typed session blocks
  - explicit conversation runtime
  - permission and hook middleware
  - prompt context discovery and budgeting
  - layered typed config
  - manifest-driven tool registry

### Risk List

1. Overcorrecting away from workflows would weaken reproducibility and durable artifact generation.
2. Copying Claw too literally would drift away from BioAPEX's scientific product boundary.
3. Rewriting the backend first would spend effort on the wrong layer because the biggest problem is current UI emphasis.

### Step-By-Step Plan

1. Write a small product/feature contract that defines BioAPEX as a general biology agent by default with optional workflows.
2. Update the composer and quick actions so they are biology-question-first rather than workflow-first.
3. Reframe `Flows` toward a softer user-facing concept such as `Runs` or `Analysis`.
4. Keep `selected_workflow` optional and only add lightweight intent routing if needed.
5. Preserve workflows as expert-mode execution paths for reproducible analyses and protocol runs.

### Detailed Note

- `.omx/research/general-biology-agent-direction-2026-04-01.md`

## 2026-04-01 Frontend/Backend Recommendation

The current BioAPEX stack is in a good place to hold steady. The least dangerous path is not to reshuffle architecture, but to preserve the existing runtime/session/access boundaries and either:

1. stop here and explicitly treat the current slice-3 dossier surface as the stable product baseline, or
2. move forward with only the already-planned additive `Timeline` slice.

### Evidence

- backend verification sweep passed with `300` tests
- frontend typecheck passed
- frontend contract suite passed with `9` tests
- frontend production build passed
- the codebase still reflects Study Dossier slices 1 through 3, while `context/current-feature.md` now points at the unimplemented slice-4 `Timeline` work

### Recommendation

- Keep the current architecture.
- Avoid broad frontend or backend refactors while the current test/build surface is green.
- Treat the only real open architecture choice as product scope:
  - ship the current slice-3 dossier as the stable stopping point
  - or implement the final additive `Timeline` slice exactly as planned

### Main Risk

- The main residual risk is not current breakage. It is plan/code drift: the repo is healthy, but the active feature contract is already talking about `Timeline`, which is not in the shipped contract yet.

## Question

Is the pasted oh-my-codex demo guide what this workspace is using right now, or is it only a version that could also be used? Also, which OMX features are the most useful in this workspace?

## Recommendation

This workspace is using OMX v2 right now, but the pasted guide is not an exact match for the installed local build.

## Evidence

- Installed CLI:
  - `/gpfs/home/yininz6/.conda/envs/miniAgent/bin/omx`
  - resolves to `/gpfs/home/yininz6/.codex/omx-v2-staticpayload-20260401/packages/cli/dist/bin.js`
- Installed version:
  - `omx version` -> `2.0.0`
- Configured MCP runtime:
  - `~/.codex/config.toml` points the `omx` MCP server at the same `omx-v2-staticpayload-20260401` source tree
- Live team runtime:
  - `.omx/team/team.json` shows an active tmux-backed team
  - `omx team status` returns the same live state
- Guide mismatch signals:
  - installed CLI rejects top-level `omx status`
  - local OMX README says there is no Claude bridge in v2, while the pasted guide describes mixed Codex/Claude team workers

## Practical Interpretation

- Yes: OMX is active in this workspace right now.
- No: the pasted demo guide should not be treated as the exact contract for the currently installed local build.
- Best source of truth for this workspace is the installed CLI plus repo/runtime state, not copied demo text.

## Most Useful Features Here

1. `omx doctor`
   - Best first command after install or when something feels off.
   - In this workspace it confirms the CLI, tmux, MCP config, and repo `.omx/` layout are healthy.

2. `omx hud --json`
   - Best runtime-truth surface.
   - It exposes tasks, reviews, inbox pressure, team health, and stale state that chat memory can miss.

3. `$ultrawork`
   - Best default operating mode for real work.
   - It fits this repo because the work often needs interview -> plan -> execute -> verify rather than a one-shot command.

4. `omx team ...`
   - Most useful when the work splits into backend/frontend/review slices.
   - This repo already has live tmux-backed team state and review artifacts, so the feature is not theoretical here.

5. `omx explore ...`
   - Most useful before risky edits or reviews.
   - Use it to trace references, symbols, and likely blast radius instead of guessing.

6. `omx plugins doctor`
   - Useful because plugin wiring is already healthy here (`github@openai-curated`, `gmail@openai-curated`, `omx-product`).
   - Good for quickly separating plugin problems from general CLI/runtime problems.

## Lower-Priority Right Now

- `omx hooks ...`
  - Useful in general, but not the next feature to lean on here because hook status currently shows:
    - `codexHooksEnabled: false`
    - `repoInstalled: false`
    - `personalInstalled: false`

## Recommendation

For day-to-day use in this repo, the smallest high-value command set is:

- `omx doctor`
- `omx hud --json`
- `$ultrawork "..."` inside Codex
- `omx team status`
- `omx explore search|refs|symbols`

## 2026-04-01 Frontend Compliance UX Recommendation

### Question

If BioAPEX wants a more modern agent-style frontend, should compliance still be shown in the main UI?

### Recommendation

Yes, but only when it materially changes user action.

- Keep live retrieval/tool/workflow activity visible during the turn.
- Keep the final transcript clean after the turn.
- Do not show a default compliance card for every successful low-risk turn.
- Do show compliance prominently in the primary surface for:
  - warnings that affect interpretation
  - approval-required turns
  - blocked turns
- Keep full compliance detail available in inspector/workspace/artifact surfaces even when the main transcript stays minimal.

### Evidence

- BioAPEX's own product contract explicitly requires safety and compliance gates and says they are not optional warnings.
- `Azealoo/claw-code` is a good reference for live activity style, compact tool display, and hiding raw thinking from the final rendered output.
- `Azealoo/claw-code` is not a good reference for compliance visibility because it does not expose a comparable scientific compliance UX surface.

### Practical Rule

Use severity-based compliance disclosure:

1. `allow`: hide from main chat by default
2. `allow_with_warning`: small inline warning affordance
3. `require_approval`: prominent inline gate
4. `block`: explicit blocking state in the primary surface

## 2026-04-01 Claw-Code UX Benchmark

### Question

If `Azealoo/claw-code` is the UX benchmark BioAPEX wants to move toward, what is the right thing to borrow?

### Recommendation

Borrow the interaction contract, not the literal terminal style.

- show compact live activity while the turn is running
- keep the final transcript quiet once the answer is done
- preserve full structured truth in secondary inspectable surfaces
- make actions, session state, and context more discoverable

For BioAPEX specifically:

- use a unified live turn-activity feed in chat
- keep the final transcript focused on the answer plus escalated safety states
- drive turn-details views from existing session `blocks`
- add BioAPEX-specific quick actions instead of a developer-heavy generic command table

### Evidence

- `Azealoo/claw-code` explicitly separates stream events, tool use, tool results, session blocks, and compaction behavior across:
  - `rust/crates/claw-cli/src/app.rs`
  - `rust/crates/claw-cli/src/render.rs`
  - `rust/crates/runtime/src/conversation.rs`
  - `rust/crates/runtime/src/session.rs`
  - `rust/crates/runtime/src/compact.rs`
  - `rust/crates/commands/src/lib.rs`
- BioAPEX already has additive session blocks for `text`, `tool_use`, `tool_result`, `retrieval`, `workflow_event`, and `usage` in:
  - `backend/graph/session_manager.py`
  - `backend/api/chat.py`
  - `frontend/src/lib/types.ts`
  - `frontend/src/lib/api.ts`
- The main gap is UX composition, not absence of structured runtime data.

### Deliverables Written

- benchmark note:
  - `.omx/research/claw-code-ux-benchmark-2026-04-01.md`
- implementation plan:
  - `.omx/plans/p3-modern-agent-ux-from-claw-code.md`

## 2026-04-01 Biology Evidence Answering And Private-Lab Architecture

### Question

The user asked:

- who BioAPEX/Codex is in this workspace
- for three recently published biology papers
- how to reduce "safety issue" friction for a private-lab deployment while still moving toward a modern agent architecture

### Repo Truth

- `backend/evidence/review_gate.py` already requires evidence-review mode for biology questions that ask for papers, evidence, summaries, recommendations, or other substantive factual biology answers.
- `backend/compliance/preflight.py` already implements deterministic preflight instead of relying on prompt-only safety instructions.
- `.omx/research/frontend-compliance-ux-2026-04-01.md` recommends severity-based compliance disclosure:
  - quiet for low-risk allow states
  - visible for warnings
  - prominent for approval-required or blocked states
- `.omx/research/claw-code-bioapex-architecture-map-2026-04-01.md` recommends borrowing modern agent ideas from `Azealoo/claw-code` selectively:
  - prompt context discovery plus budgets
  - typed session message blocks
  - manifest-driven tool permissions
  - pre-tool and post-tool policy middleware
  - layered typed config

### External Truth

As of 2026-04-01, recent example biology papers from primary journal sources include:

1. H. Mathilda Lennartz et al., "Visualizing suborganellar lipid distribution using correlative light and electron microscopy," Nature Cell Biology, published 2026-03-20.
   - Introduces a Lipid-CLEM workflow for nanoscale lipid localization and reports differential sphingomyelin partitioning inside early endosome subcompartments.
   - Source: https://www.nature.com/articles/s41556-026-01915-x

2. Rong Zheng et al., "Improving the efficiency of high-fidelity Cas9 by enhancing PAM-distal interactions," Nature Structural & Molecular Biology, published 2026-03-18.
   - Reports that extending spacer length to 21-22 nt can restore cleavage activity in SuperFi-Cas9 while retaining high-fidelity editing behavior, plus a model for guide-length selection.
   - Source: https://www.nature.com/articles/s41594-026-01753-3

3. Shan He et al., "Kinase KEY1 controls pyrenoid condensate size throughout the cell cycle by disrupting phase separation interactions," Nature Cell Biology, published 2026-03-17.
   - Identifies a kinase-based mechanism regulating pyrenoid condensate size and dissolution in *Chlamydomonas reinhardtii*.
   - Source: https://www.nature.com/articles/s41556-026-01908-w

These are examples of recent primary papers, not a field consensus or a topic-specific curated reading list.

### Risks

1. Treating a private-lab setting as a reason to bypass evidence review would increase the main BioAPEX failure mode: unsupported biology claims with weak provenance.
2. Copying a modern coding-agent UX too literally would hide scientific compliance states that BioAPEX's product contract says must remain auditable and action-affecting.
3. Keeping all safety friction in prompt text instead of deterministic policy layers would make the system harder to test, trust, and later expand beyond the current private deployment.

### Recommendation

Keep the existing deterministic evidence-review and compliance-preflight layers, but make low-risk turns feel lighter.

Concretely:

1. Do not remove evidence-review mode for biology-paper requests.
2. Do make low-risk `allow` outcomes quiet in the main transcript, with richer detail in inspector/artifact surfaces.
3. Borrow modern architecture at the runtime-contract layer, not by weakening policy:
   - typed block-based sessions
   - manifest-driven tool policy metadata
   - prompt context discovery with hard budgets
   - pre-tool and post-tool policy middleware
   - layered project/user/local config

This preserves the scientific contract while reducing "safety issue" annoyance for normal internal use.

### Open Questions

- Should "recent biology papers" default to broad biology, or to the lab's actual domains such as cancer, CRISPR, single-cell, or developmental biology?
- Should private-lab mode only change UI severity and approval ergonomics, or also change any actual compliance dispositions?
- If the team wants a modern-agent pass next, should the first slice target session schema, prompt assembly, or tool policy manifests?

## 2026-04-01 Balance Between Fast Answers And Safety Friction

### Question

What is the best balance if the team still wants users to reliably get an answer, and how does the current `Azealoo/claw-code` repo inform that tradeoff?

## 2026-04-01 Codebase Redundancy Review

### Question

The user asked for a careful pass over the live codebase to find redundant logic or unnecessary code.

### Repo Truth

- Session messages are currently maintained in two parallel shapes:
  - legacy fields: `tool_calls`, `workflow_events`, `retrievals`
  - block fields: `blocks`
- The backend persists both shapes for assistant turns in `backend/api/chat.py` and `backend/graph/session_manager.py`, and the frontend store also keeps both shapes in sync while streaming in `frontend/src/lib/store.tsx`.
- The chat endpoint repeats the same synthetic tool-lifecycle bookkeeping four times:
  - compliance preflight
  - protocol executor
  - evidence-review gate
  - generic streamed tool events
- The frontend has several copy-pasted formatting helpers spread across large surfaces instead of a shared utility layer. The repeated patterns include:
  - `formatWorkflowLabel`
  - `humanizeToken`
  - `compactText`
  - `shortenIdentifier` / `shortIdentifier`
- The knowledge base contains two differently named but semantically overlapping T-cell rejuvenation hypothesis documents:
  - `backend/knowledge/hypotheses/T_cell_rejuvenation_perturbation_hypothesis.md`
  - `backend/knowledge/hypotheses/Tcell_rejuvenation_perturbation_hypothesis.md`
- `backend/tools/search_knowledge_tool.py` indexes the whole `knowledge/` tree recursively, so both documents are eligible retrieval sources at runtime.

### Evidence

- Dual session-shape persistence and normalization:
  - `backend/api/chat.py:351`
  - `backend/graph/session_manager.py:266`
  - `backend/graph/session_manager.py:478`
  - `frontend/src/lib/store.tsx:824`
  - `frontend/src/lib/store.tsx:1262`
  - `frontend/src/components/editor/TurnDetailsPanel.tsx:80`
- Repeated tool lifecycle bookkeeping in the chat route:
  - `backend/api/chat.py:432`
  - `backend/api/chat.py:447`
  - `backend/api/chat.py:517`
  - `backend/api/chat.py:530`
  - `backend/api/chat.py:576`
  - `backend/api/chat.py:589`
  - `backend/api/chat.py:724`
  - `backend/api/chat.py:736`
- Repeated frontend formatting helpers:
  - `frontend/src/components/layout/workspace-data.ts:237`
  - `frontend/src/components/layout/Navbar.tsx:173`
  - `frontend/src/components/chat/ChatInput.tsx:35`
  - `frontend/src/components/editor/InspectorPanel.tsx:186`
  - `frontend/src/components/layout/WorkspacePanel.tsx:109`
  - `frontend/src/components/layout/OpsWorkspace.tsx:232`
  - `frontend/src/components/editor/TurnDetailsPanel.tsx:53`
  - `frontend/src/components/chat/ThoughtChain.tsx:50`
  - `frontend/src/lib/surface-errors.ts:5`
- Duplicate knowledge documents and recursive indexing:
  - `backend/knowledge/hypotheses/T_cell_rejuvenation_perturbation_hypothesis.md`
  - `backend/knowledge/hypotheses/Tcell_rejuvenation_perturbation_hypothesis.md`
  - `backend/tools/search_knowledge_tool.py:38`
  - `backend/tools/search_knowledge_tool.py:77`

### Risk List

1. Dual session representations now create cross-layer drift risk. Any schema change has to be reflected in backend persistence, backend normalization, frontend streaming updates, and frontend history hydration.
2. Repeated tool-start/tool-end handling in `backend/api/chat.py` makes it easy to fix one tool path but miss another, which can desynchronize SSE payloads, audit logging, or saved session traces.
3. Copy-pasted UI formatting helpers are low-risk individually, but they create steady consistency drift across chat, navbar, inspector, workspace, and ops surfaces.
4. The duplicate T-cell hypothesis docs are not just clutter: recursive knowledge indexing can retrieve conflicting content for the same concept, which weakens evidence quality and provenance clarity.

### Recommendation

- Treat `blocks` as the canonical session structure and keep legacy fields as a compatibility view derived at read boundaries only, unless there is still a hard write-side requirement for both shapes.
- Extract one internal helper in `backend/api/chat.py` for:
  - registering `pending_tools`
  - emitting `tool_start`
  - building the saved tool call
  - appending audit records
  - emitting `tool_end`
- Consolidate shared frontend formatters into `frontend/src/lib/` so workflow labels, token humanization, truncation, and identifier shortening behave consistently everywhere.
- Deduplicate or explicitly namespace the two T-cell rejuvenation hypothesis documents before relying on knowledge retrieval for that topic.

### Tradeoffs

- Keeping both session shapes preserves backward compatibility, but the current write-both/read-both pattern is now expensive enough that it should be treated as migration debt, not as a permanent architecture.
- Centralizing frontend helper functions will slightly reduce local readability in a few files, but it removes drift and makes copy changes much safer.
- Collapsing the duplicate knowledge documents requires choosing which version is authoritative, but leaving both in place already creates ambiguous runtime behavior.

### Open Questions

- Is there any remaining consumer that requires legacy session fields to be written to disk rather than derived on load?
- Should the duplicate T-cell hypothesis files be merged, or should one be moved to an archive/superseded namespace so retrieval can distinguish them intentionally?

### Repo Truth

- BioAPEX already has a block-oriented session schema in `backend/graph/session_manager.py` and renders live turn activity separately from the final answer in `frontend/src/components/chat/ChatMessage.tsx`.
- BioAPEX still keeps a persistent compact compliance card after completion when a compliance report exists.
- Biology questions that ask for substantive factual answers, papers, evidence, summaries, or recommendations already route through deterministic evidence review in `backend/evidence/review_gate.py`.
- Biology-sensitive execution already routes through deterministic compliance preflight in `backend/compliance/preflight.py`.

### Current External Truth

Current `claw-code` main as of 2026-04-01 is commit `7030d26e7a9ca7fef5c74f463eede01a59403847`.

Relevant observed patterns from that repo:

1. `rust/crates/claw-cli/src/render.rs`
   - strongly separates live spinner/activity rendering from the final rendered answer
   - treats compact progress as temporary UI, not permanent transcript content

2. `rust/crates/runtime/src/session.rs`
   - stores durable session truth as typed `text`, `tool_use`, and `tool_result` blocks with attached usage

3. `rust/crates/runtime/src/conversation.rs`
   - keeps permission decisions and pre/post-tool hooks in the runtime loop
   - denied or hook-blocked tools still produce a faithful tool-result message instead of silently disappearing

4. `rust/crates/runtime/src/prompt.rs`
   - budgets instruction context and includes discovered instruction files plus git snapshots

5. `rust/crates/tools/src/lib.rs`
   - declares tool specs with explicit required permission levels

### Recommendation

The best balance is:

1. Keep the answer path permissive for low-risk informational turns.
   - Users should almost always receive a response.
   - Low-risk `allow` results should not feel like a compliance workflow.

2. Keep the policy path strict, but mostly invisible unless it changes user action.
   - This is the real lesson from `claw-code`: clean output does not require weak runtime policy.
   - Hide routine safe-pass details from the main transcript.

3. Never bypass evidence review for substantive biology claims.
   - A fast answer with no evidence artifact is the wrong optimization for BioAPEX.
   - The right optimization is faster evidence retrieval/review plus cleaner presentation.

4. Show only action-affecting safety in the main answer surface.
   - `allow`: no default compliance card in main chat
   - `allow_with_warning`: small inline warning
   - `require_approval`: inline gate
   - `block`: explicit stop state

5. Preserve full truth in secondary and durable surfaces.
   - session blocks
   - evidence artifacts
   - compliance reports
   - audit logs

### Decision-Ready Guidance

If the goal is "users still get an answer," the right compromise is not to remove safety gates. It is to make safe passes quiet and fast while keeping evidence review and hard stops for the turns that actually need them.

In short:

- optimize UI friction down
- optimize evidence latency down
- keep deterministic policy and provenance intact

### Best First Product Change

If BioAPEX wants the single best first balance change, it should stop showing a persistent compliance card for every completed `allow` turn in main chat, while keeping:

- live turn activity during execution
- final answer in main chat
- warning/approval/block states inline when needed
- full compliance/evidence detail in inspector and artifact surfaces
