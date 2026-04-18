# General Biology Agent Direction

Date: 2026-04-01
Analyst: Codex

## Question

What should BioAPEX do if the product goal is no longer "pick a workflow first," but instead:

- let the user ask general biology questions in the frontend
- let the agent choose tools when needed
- keep workflows available only when they are the right structured execution path
- borrow architecture ideas from `Azealoo/claw-code` without copying the wrong product boundary

## Repo Truth

### 1. BioAPEX already supports general-agent turns in the backend

- `backend/api/chat.py`
  - `ChatRequest.selected_workflow` is optional.
  - When `selected_workflow` is absent, the request still goes through:
    - compliance preflight
    - protocol classification
    - evidence-review gate
    - generic agent streaming through `agent_manager.astream(...)`
- The workflow runner path only activates inside the explicit `if request.selected_workflow:` branch.

Implication:

- The backend is not fundamentally workflow-only.
- BioAPEX already has the right high-level runtime split for a general biology agent with optional workflows.

### 2. The frontend still makes workflows feel like the primary mode

- `frontend/src/components/chat/ChatInput.tsx`
  - keeps a visible workflow picker
  - renders selected workflow chips
  - primes draft messages from workflow-biased quick actions
  - uses placeholder text that still mentions "workflow step"
- `frontend/src/components/layout/workspace-data.ts`
  - keeps `Flows` in the primary navigation
  - defines workflow-centered quick starts
  - frames part of the product around tracking named workflows
- `frontend/src/lib/store.tsx`
  - treats selected workflow as a first-class UI state and updates it from workflow events
- `frontend/src/lib/api.ts`
  - forwards `selected_workflow` as optional context on every chat request

Implication:

- The main blocker is product emphasis and interaction design, not missing backend capability.

### 3. BioAPEX already has several "best parts" of Claw-like architecture

- `backend/graph/session_manager.py`
  - session schema already supports ordered blocks for:
    - `text`
    - `tool_use`
    - `tool_result`
    - `retrieval`
    - `workflow_event`
    - `usage`
- `backend/graph/prompt_builder.py`
  - already discovers ancestor instruction files
  - already follows referenced context files
  - already enforces prompt budgets
  - already supports optional git context injection
- `backend/tools/registry.py`
  - already exposes manifest-like policy metadata:
    - access scope
    - evidence requirement
    - compliance-preflight requirement
    - output contract version

Implication:

- BioAPEX does not need a large architectural rewrite to get closer to the strong parts of `claw-code`.
- Several previously identified Claw-inspired runtime ideas are already implemented here.

### 4. BioAPEX still has a stronger scientific boundary than Claw

From repo docs and code:

- `context/project-overview.md` still defines BioAPEX as a transparent, file-first biologist assistant with provenance, compliance, and explicit workflows.
- `backend/api/chat.py` always runs deterministic compliance preflight before deeper execution.
- `backend/api/chat.py` also runs an evidence-review gate for biology-answering turns.

Implication:

- The right move is not to weaken scientific policy.
- The right move is to make low-friction general use feel natural while preserving explicit evidence/provenance layers underneath.

## External Truth

Primary-source inspection of `https://github.com/Azealoo/claw-code` on 2026-04-01 shows:

### 1. The Rust workspace is the real architectural reference

`README.md` on `main` says the active systems-language port lives under `rust/` and lists:

- `crates/api-client`
- `crates/runtime`
- `crates/tools`
- `crates/commands`
- `crates/plugins`
- `crates/compat-harness`
- `crates/claw-cli`

The Python `src/` tree is presented as a porting workspace, not the main long-term runtime shape.

### 2. Claw's strongest reusable runtime ideas are structural, not visual

From the current Rust files:

- `rust/crates/runtime/src/session.rs`
  - durable session schema with typed blocks for `text`, `tool_use`, and `tool_result`
- `rust/crates/runtime/src/conversation.rs`
  - explicit turn loop
  - tool-use / tool-result cycle
  - permission decisions
  - pre-tool and post-tool hooks
  - usage accumulation
  - compaction hooks
- `rust/crates/runtime/src/prompt.rs`
  - ancestor instruction discovery
  - deduplication
  - prompt budgeting
  - git context snapshots
  - config rendering into prompt context
- `rust/crates/runtime/src/config.rs`
  - layered config precedence across user, project, and local scopes
  - typed parsing for hooks, plugins, MCP, OAuth, permission mode, and sandbox settings
- `rust/crates/tools/src/lib.rs`
  - central tool spec definitions
  - explicit required permission levels
  - normalized allowed-tool filtering
  - plugin tool validation against built-ins

### 3. Claw is not the right product-boundary model for BioAPEX

The repo is a harness/runtime product for general agentic work.

It does not provide a comparable scientific contract for:

- evidence-backed biology answers
- provenance-rich scientific artifacts
- deterministic compliance gating
- explicit scientific workflow outputs as a first-class product promise

Implication:

- BioAPEX should borrow Claw's runtime explicitness and discoverability patterns.
- BioAPEX should not copy Claw's generic product posture.

## Assumptions

- The user wants "Claw style" to mean the interaction feel and architecture discipline, not a literal terminal clone.
- The user's phrase "clock code" refers to `claw-code`.
- The product shift is toward a general biology assistant first, not toward removing workflows entirely.

## Risks

1. Overcorrecting away from workflows

- If workflows stop being visible or discoverable at all, BioAPEX could lose one of its strongest differentiators:
  - explicit reproducible analysis paths
  - durable run artifacts
  - auditable execution

2. Copying Claw too literally

- If BioAPEX copies a generic coding-agent shell too directly, it will drift away from:
  - scientific identity
  - provenance
  - evidence discipline
  - compliance visibility

3. Solving the wrong layer first

- A big backend rewrite would be expensive and mostly unnecessary.
- The codebase already supports optional workflows, structured session blocks, and policy-aware tools.

4. Making general biology answers too loose

- If "general agent" becomes "freeform answerer without evidence guardrails," BioAPEX will become faster but less trustworthy.

## Recommendation

Shift BioAPEX to:

`general biology agent first, structured workflows second`

but implement that as a product-emphasis and routing change, not as a teardown of the existing backend.

### What to keep

- deterministic compliance preflight
- evidence-review gating for substantive biology answers
- optional explicit workflows for reproducible execution
- structured session blocks
- artifact-first outputs
- policy-aware tool registry

### What to change

- make the default frontend feel like:
  - ask a biology question
  - attach study files
  - request evidence
  - request interpretation
  - request analysis help
- demote workflow picking from "default user decision" to "optional advanced/structured mode"
- expose capability discovery through biology-native quick actions and contextual suggestions

## Step-By-Step Plan

### Phase 1. Lock the product contract

Create a small spec/plan that states:

- BioAPEX is a general biology agent by default
- workflows remain available for tasks that need reproducibility and durable execution
- low-risk question answering should not force the user to choose a workflow first

This should update the active product direction before UI work continues.

### Phase 2. Pivot the composer from workflow-first to question-first

Change the frontend composer so the default path is:

- ask a biology question
- attach files or identifiers
- optionally choose a mode only when helpful

Concrete targets:

- `frontend/src/components/chat/ChatInput.tsx`
- `frontend/src/components/layout/workspace-data.ts`

Recommended changes:

- replace the default workflow button emphasis with a lighter "Modes" or "Analysis run" affordance
- rewrite quick actions around intents such as:
  - Ask a biology question
  - Review evidence
  - Interpret an attached result
  - Plan an analysis
  - Run a structured workflow
- update placeholder copy so it stops leading with "workflow step"

### Phase 3. Reframe navigation around user goals instead of internal machinery

Review the top-level nav and workspace labels.

`Flows` is accurate internally, but it keeps steering the product toward workflow management.

Possible replacements:

- `Runs`
- `Analysis`
- `Capabilities`

The exact label is a product choice, but the current one over-signals workflow-first usage.

### Phase 4. Add lightweight intent routing, not heavy new orchestration

Do not replace the backend agent loop first.

Instead:

- keep `selected_workflow` optional
- add light intent tagging or routing hints so the UI can distinguish:
  - general question
  - evidence review
  - protocol support
  - structured workflow run

This can be additive and should not remove the current generic agent path.

### Phase 5. Preserve workflows as "expert mode with artifacts"

Keep structured workflows for:

- RNA-seq and other reproducible analysis runs
- protocol execution
- long-running toolchains
- auditable export-producing work

The change is not "remove workflows."
It is "users should only think about workflows when the task truly needs one."

### Phase 6. Improve capability discoverability using existing architecture

Use what BioAPEX already has:

- block-driven turn details
- tool registry metadata
- skills
- artifact surfaces

Add UI that answers:

- what can BioAPEX do here?
- what tools did it use?
- what evidence supports this answer?
- when should I escalate into a structured run?

### Phase 7. Only then consider deeper runtime alignment with Claw

Because BioAPEX already has:

- prompt context discovery
- session blocks
- tool manifest metadata

the remaining deeper runtime work should be selective, not wholesale.

The next worthwhile deeper slice would likely be:

- stronger typed capability/intent metadata across tools, skills, and frontend quick actions

not a rewrite of the session or chat runtime.

## Concrete First Slice

The best first implementation slice is:

`General Biology Agent Shell`

Scope:

- change composer copy
- reduce visual prominence of workflow selection
- rewrite quick actions around biology intents
- keep workflow launch available but secondary
- do not change backend contracts except for additive naming or labels if needed

Why this first:

- highest product leverage
- lowest architectural risk
- directly aligned with the user's stated goal
- does not throw away working workflow infrastructure

## Open Questions

1. Should workflows stay in top-level navigation, or move behind a secondary "Runs" / "Analysis" surface?
2. Should evidence review be an explicit quick action, an automatic hidden behavior, or both?
3. Should the default agent mode expose tool activity and citations prominently, or keep them mostly in the inspector unless the user asks?
4. Do you want the first pass to be mostly UX/product copy, or do you also want intent-aware backend labeling in the same slice?

## Decision

Do not rebuild BioAPEX around Claw.

Do reposition BioAPEX as:

- a general biology agent for the default experience
- with explicit workflows available when the task needs reproducibility, artifacts, and execution structure

That uses the strongest part of the current codebase and the strongest lessons from `claw-code` at the same time.
