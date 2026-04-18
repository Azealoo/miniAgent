# P6 Biologist Skill And Memory Runtime

Date: 2026-04-02

## Goal

Turn the cleaned chat-only backend into a more biologist-native assistant by:

- upgrading the existing prototype skill corpus into a trustworthy biology workflow library
- replacing snapshot-only skill handling with runtime skill discovery and selection
- replacing single-file `memory/MEMORY.md` assumptions with a backward-compatible memory directory
- adding relevant-memory retrieval that works with the current engine-first backend instead of reopening the harness redesign

## Why This Phase Comes Next

- `P5 Engine-First Backend Cleanup` left the backend in a strong place to build on:
  - `backend/runtime/chat_runtime.py` owns turn streaming
  - `backend/runtime/query_engine.py` owns ordinary turn flow
  - `backend/tools/registry.py` already provides a solid tool policy contract
- The current skill system is still snapshot-first:
  - `backend/tools/skills_scanner.py` writes `SKILLS_SNAPSHOT.md`
  - `backend/graph/prompt_builder.py` injects the whole snapshot into the prompt
- The current memory system is still single-file-first:
  - `backend/graph/memory_indexer.py` indexes only `memory/MEMORY.md`
  - `backend/api/files.py` only triggers memory rebuilds when `memory/MEMORY.md` changes
- The current skill corpus is useful but uneven:
  - several biology skills are strong seeds for a real biologist workflow library
  - taxonomy is inconsistent (`bio/scRNA`, `bio/perturbation`, `bio/calculations`, `bio/hpc`)
  - at least one skill still points at a removed runtime tool (`slurm_tool`)

## Must-Have End State

- Stable biology skills have normalized metadata, valid tool dependencies, and a consistent output quality bar.
- Runtime skill discovery and prompt injection no longer depend on dumping one monolithic snapshot into every turn.
- Memory is organized as a directory with `MEMORY.md` as an index or compatibility layer rather than the only durable memory source.
- Turn-time memory retrieval returns relevant memory files or sections with source attribution.
- The backend remains engine-first and chat-first while gaining more domain-specific skill and memory behavior.

## Phase Rules

1. Do not reopen the harness redesign unless a slice needs a small, explicit seam.
2. Preserve backward compatibility for `memory/MEMORY.md` and `/api/skills` until replacements are verified.
3. Treat the current `backend/skills/` directory as the domain seed set, not as throwaway prototype work.
4. Promote only tool-backed biology workflows to `stable`; leave thin prompt macros visibly `experimental` or non-user-invocable.
5. Stable biology skills must surface assumptions, evidence or source basis, caveats, and a recommended next step.
6. Remove or quarantine skills that depend on deleted tools or invalid taxonomy values before building richer routing on top of them.

## Slice 1: Skill Catalog Foundation

### Goal

Normalize the current skill corpus so later registry and routing work is built on consistent metadata instead of one-off prototypes.

### Likely File Targets

- `backend/skills/**/SKILL.md`
- `backend/tools/skills_scanner.py`
- `backend/knowledge/skill-authoring-guide.md`
- `backend/knowledge/biology-skill-taxonomy.md`
- `backend/tests/test_skills_scanner.py`

### Must Do

- Normalize category strings to the published taxonomy, especially:
  - `bio/scRNA` -> `bio/single_cell_rna`
  - `bio/perturbation` -> `bio/perturb_seq` or another explicit supported domain
  - `bio/calculations` and `bio/hpc` -> supported biology or compute domains
- Standardize the core frontmatter used by user-facing biology skills:
  - `category`
  - `requires_tools`
  - `species`
  - `modality`
  - `stage`
  - `stability`
  - `safety_level`
- Add an explicit maturity split:
  - `stable`
  - `evolving`
  - `experimental`
- Remove or quarantine stale tool dependencies, especially skills that still reference deleted runtime tools.
- Tighten scanner tests so invalid metadata or missing required fields fail loudly for the promoted stable set.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "category: bio/scRNA|category: bio/perturbation|category: bio/calculations|category: bio/hpc|slurm_tool" backend/skills -S`

### Done When

- Stable/user-invocable biology skills all use valid taxonomy values and valid tool names.
- Prototype skills are visibly marked as such instead of pretending to be production-ready.
- Scanner coverage protects the normalized metadata shape.

### Depends On

- none

## Slice 2: Memory Directory Foundation

### Goal

Replace the single-file memory assumption with a backward-compatible memory directory contract.

### Likely File Targets

- `backend/graph/memory_indexer.py`
- `backend/api/files.py`
- `backend/workspace/AGENTS.md`
- `backend/memory/MEMORY.md`
- `backend/memory/`
- `backend/tests/test_memory_indexer.py`
- `backend/tests/test_tools.py`
- `backend/tests/test_audit_logging.py`

### Must Do

- Define a durable memory directory layout, at minimum:
  - `memory/MEMORY.md` as index or compatibility entrypoint
  - `memory/project/`
  - `memory/user/`
  - optional `memory/agent/` or another clearly scoped runtime bucket
- Teach the memory layer to discover memory files by path instead of assuming exactly one file.
- Keep current read and write behavior for `memory/MEMORY.md` working during the migration.
- Update file-write hooks so writes anywhere under `memory/` refresh memory state, not only writes to `memory/MEMORY.md`.
- Clarify the boundary between long-term memory and knowledge-base content in operator-facing instructions.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_tools.py tests/test_audit_logging.py -q`
- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_engine_health.py -q -k "files or session_tokens"`

### Done When

- The backend can discover multiple memory files without breaking current `memory/MEMORY.md` flows.
- File writes under `memory/` consistently trigger memory refresh behavior.
- Instructions/docs no longer describe memory as a single giant file only.

### Depends On

- none

## Slice 3: Relevant Memory Selection

### Goal

Make turn-time memory retrieval relevant, sourced, and compact instead of broad single-file injection.

### Likely File Targets

- `backend/graph/memory_indexer.py`
- `backend/graph/agent.py`
- `backend/graph/prompt_builder.py`
- `backend/tests/test_memory_indexer.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_chat_streaming.py`

### Must Do

- Index memory content with per-file or per-section source paths.
- Retrieve a small relevant subset for the current user message.
- Keep retrieval output source-aware so the chat transcript can show where the memory came from.
- Preserve the existing chat runtime contract:
  - no regression in event ordering
  - no regression in persisted retrieval blocks
  - no broad prompt blow-up from excessive memory injection

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_memory_indexer.py tests/test_prompt_builder.py tests/test_chat_streaming.py -q`

### Done When

- Retrieved memories cite real memory paths instead of always `MEMORY.md`.
- Only a bounded, relevant memory subset is injected into a turn.
- Existing chat streaming behavior stays green.

### Depends On

- Slice 2

## Slice 4: Runtime Skill Registry Foundation

### Goal

Replace snapshot-first skill handling with a structured runtime registry while keeping compatibility where needed.

### Likely File Targets

- `backend/tools/skills_scanner.py`
- `backend/api/files.py`
- `backend/graph/prompt_builder.py`
- `backend/workspace/AGENTS.md`
- `backend/tests/test_skills_scanner.py`
- `backend/tests/test_prompt_builder.py`

### Must Do

- Introduce a runtime skill registry object built from:
  - local `backend/skills/`
  - configured extra dirs
  - repo `.agents/skills/`
- Keep precedence and enable/disable behavior explicit and tested.
- Demote `SKILLS_SNAPSHOT.md` to a derived artifact or compatibility output instead of the primary runtime source.
- Upgrade `/api/skills` so it can surface richer metadata without forcing clients to parse the snapshot.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_chat_engine_health.py -q`

### Done When

- Skill discovery is runtime-structured rather than file-dump-driven.
- Prompt-building and skill listing no longer rely on a monolithic snapshot as the source of truth.

### Depends On

- Slice 1

## Slice 5: Skill Routing And Prompt Integration

### Goal

Route each turn toward a small relevant skill subset so the model sees biologist-relevant workflows instead of the entire catalog.

### Likely File Targets

- `backend/graph/agent.py`
- `backend/graph/prompt_builder.py`
- `backend/runtime/query_engine.py`
- `backend/tests/test_prompt_builder.py`
- `backend/tests/test_runtime_query_engine.py`
- `backend/tests/test_chat_streaming.py`
- new selector module if needed under `backend/graph/` or `backend/tools/`

### Must Do

- Select candidate skills per turn using normalized metadata such as:
  - name
  - aliases
  - tags
  - category
  - modality
  - stage
- Preserve explicit skill invocation by name when the user asks for a skill directly.
- Inject only the selected skill context into the prompt for ordinary turns.
- Keep the routing logic deterministic enough to test.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_prompt_builder.py tests/test_runtime_query_engine.py tests/test_chat_streaming.py -q`

### Done When

- Perturb-seq, scRNA, wet-lab, and literature questions each surface a meaningfully narrower skill set.
- Explicit skill-name requests still work.
- Prompt size and relevance improve without changing the engine-first runtime boundary.

### Depends On

- Slice 1
- Slice 4

## Slice 6: Core Biologist Workflow Hardening

### Goal

Promote a small trusted set of biology workflows from prototype status to stable biologist-facing skills.

### Initial Stable-Candidate Set

- `gene_symbol_normalizer`
- `protocol_from_knowledge`
- `paper_triage`
- `guide_risk_precheck`
- `scRNA_qc_checklist`
- `differential_expression_helper`
- `marker_gene_validator`
- `literature_consensus_map`

### Likely File Targets

- `backend/skills/gene_symbol_normalizer/SKILL.md`
- `backend/skills/protocol_from_knowledge/SKILL.md`
- `backend/skills/paper_triage/SKILL.md`
- `backend/skills/guide_risk_precheck/SKILL.md`
- `backend/skills/scRNA_qc_checklist/SKILL.md`
- `backend/skills/differential_expression_helper/SKILL.md`
- `backend/skills/marker_gene_validator/SKILL.md`
- `backend/skills/literature_consensus_map/SKILL.md`
- `backend/knowledge/skill-authoring-guide.md`
- stable-skill quality tests under `backend/tests/`

### Must Do

- Rewrite stable-candidate skills so they are tool-backed rather than generic prompt templates.
- Prefer current BioAPEX biology tools where possible:
  - `search_knowledge_base`
  - `evidence_retrieval`
  - `evidence_review`
  - `ensembl_api`
  - `uniprot_api`
  - `ncbi_eutils`
- Require a consistent user-facing output shape for stable biology skills:
  - biological context or assumptions
  - evidence or source basis
  - caveats or ambiguity
  - recommended next experiment or analysis step
- Add tests or catalog checks that prevent promoted stable skills from drifting back into thin prototypes.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_chat_streaming.py -q`
- `cd /gpfs/projects/hrbomics/miniAgent && rg -n "stability: stable" backend/skills/*/SKILL.md -S`

### Done When

- A small stable biology workflow set is strong enough to route to confidently.
- Stable skills visibly use evidence-aware or knowledge-aware tooling and produce biologist-native outputs.

### Depends On

- Slice 1
- Slice 4
- Slice 5

## Slice 7: Final Surface And Regression Closeout

### Goal

Finish the phase with aligned docs, compatibility decisions, and a green focused backend sweep.

### Likely File Targets

- `backend/api/files.py`
- `backend/workspace/AGENTS.md`
- `backend/knowledge/skill-authoring-guide.md`
- `backend/graph/prompt_builder.py`
- `context/current-feature.md`
- `.omx/plans/p6-biologist-skill-and-memory-runtime.md`
- `.omx/plans/p6-biologist-skill-and-memory-runtime-verification.md`

### Must Do

- Decide whether `SKILLS_SNAPSHOT.md` remains as a compatibility artifact or is removed after the runtime registry is proven.
- Align file API docs, workspace instructions, and tests with the new memory-dir and skill-registry behavior.
- Run a focused regression sweep across the touched backend surfaces.
- Leave the repo with one obvious story for skills and memory instead of mixed old/new contracts.

### Verification

- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_skills_scanner.py tests/test_prompt_builder.py tests/test_memory_indexer.py tests/test_chat_streaming.py tests/test_runtime_query_engine.py tests/test_chat_engine_health.py -q`
- `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m compileall -q .`

### Done When

- Docs, prompt wiring, API behavior, and tests all describe the same skill and memory model.
- The backend still feels engine-first and chat-first after the domain-specific upgrades.

### Depends On

- Slices 1 through 6

## Phase Exit Conditions

- BioAPEX can discover, select, and surface a small relevant set of skills per biology turn.
- BioAPEX can store and retrieve long-term memory from a structured memory directory with backward-compatible `MEMORY.md` behavior.
- The promoted stable skill set is clearly better for biologists than the current prototype baseline.
- The backend remains clean enough that future work lands in skill, memory, and tool seams rather than reopening core runtime cleanup.
