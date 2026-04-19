# Tool Selection Guide

Several tools in `backend/tools/registry.py` overlap in surface area. Picking
the wrong one is a common planner mistake — the calls succeed but impose
excess risk, skip policy hooks, or ignore evidence requirements. This guide
names a preferred default per family and the conditions under which a
different tool is the right choice.

The authoritative list of registered tools is `_instantiate_all_tools` in
`backend/tools/__init__.py` (15 tools). Access scope, read-only /
destructive flags, concurrency behavior, planner/verifier exposure, and
sandbox envelopes are declared in `backend/tools/registry.py`; do not guess
them — look them up.

Conventions used below:

- **access scope** — `inspection` (read-only lookups), `execution`
  (causes side effects), `admin` (privileged; none of the registered 15
  are admin).
- **tier** — `read-only / concurrency-safe` tools run in the parallel
  dispatcher tier (`is_concurrency_safe_tier`); destructive or
  execution-scope tools run serially.
- **sandbox** — present only on high-risk tools (`python_repl`,
  `fetch_url`, `http_json`, `write_file`). See `_HIGH_RISK_SANDBOX_SPECS`.

## URL retrieval — `fetch_url` vs `http_json`

**Default: `http_json`** when the endpoint returns structured JSON and you
need to keep parsing in-process.

**Use `fetch_url`** when retrieving HTML or other opaque text (landing
pages, documentation, PDFs via an intermediary) where you want the body as
a string for downstream summarization.

Both are `inspection` scope, read-only, concurrency-safe, public network
sandbox. Differences worth keeping in mind:

| | `fetch_url` | `http_json` |
| - | - | - |
| max wall-clock | 30 s | 45 s |
| max output bytes | 8 KB | 100 KB |
| expected shape | text/HTML | JSON |

If the payload is JSON, `http_json` gives you ~12× more body budget and a
longer timeout; `fetch_url` will silently truncate a large JSON document at
8 KB.

## Execution — `python_repl` vs `terminal`

**Default: `python_repl`** for any data-manipulation or analysis step.
Sandbox restricts file writes to `memory/`, `skills/`, `knowledge/`,
`artifacts/`, `storage/`; network is disabled; 60 s wall-clock; 5 KB output
cap. This is the safer execution surface.

**Use `terminal`** only when the work genuinely requires shell semantics:
invoking an installed CLI, process trees, pipelines that cannot be
expressed in Python, or workflow runners. `terminal` carries no sandbox
and no file-root allowlist at the tool layer — policy wrappers and workspace
boundaries are the only guardrails.

Both are `execution` scope and `requires_approval=true`. Neither is
read-only or concurrency-safe; expect them to run serially and to surface
an approval prompt to the operator. Do not treat either as a fallback when
a dedicated tool (e.g. `ncbi_eutils`, `read_file`) already does the job.

## Biology databases — `ncbi_eutils` vs `ensembl_api` vs `uniprot_api`

All three are `inspection` scope, read-only, concurrency-safe, and carry
`evidence_requirement = "recommended"`. Pick by identifier space:

- **`ncbi_eutils`** — NCBI EUtils (PubMed, Gene, Nucleotide, Protein,
  Taxonomy, …). Default for literature lookups, PubMed IDs, taxonomy
  resolution, and any NCBI-native identifier.
- **`ensembl_api`** — Ensembl REST. Default for Ensembl IDs (ENSG/ENST),
  genome coordinates, cross-species orthology, and regulatory features.
- **`uniprot_api`** — UniProt REST. Default for protein-level questions
  keyed on UniProt accessions (P12345-style), sequence, domains, and
  protein function annotation.

Record at least one evidence span when these tools contribute to a claim —
their `evidence_requirement` is `recommended`, and verification will flag
unsupported claims derived from them.

## Evidence surface — `evidence_retrieval` vs `evidence_review` vs `entity_grounding`

These are **not interchangeable**; they sit at different points in the
evidence pipeline.

- **`evidence_retrieval`** (`inspection`, read-only, concurrency-safe,
  `evidence_requirement = recommended`) — fetches candidate evidence for a
  claim. This is the only one of the three that is read-only and safe to
  dispatch in parallel batches.
- **`entity_grounding`** (`execution`, `evidence_requirement = recommended`)
  — resolves mentions to canonical entities. Execution-scope because it
  mutates grounding state; run it after retrieval, before review.
- **`evidence_review`** (`execution`, `evidence_requirement = required`,
  `verifier_exposed = true`) — scores and decides on evidence. This is the
  verifier-side gate; it must run with real evidence attached and will
  refuse ungrounded inputs.

**Default pipeline:** `evidence_retrieval` → `entity_grounding` →
`evidence_review`. Calling `evidence_review` without the first two is the
most common misuse.

## File I/O — `read_file` vs `write_file`

- **`read_file`** (`inspection`, read-only, concurrency-safe). Default for
  any disk read inside the allowed roots; no sandbox needed.
- **`write_file`** (`execution`, `destructive`, `requires_approval`,
  `interrupt_behavior = avoid_interrupting`). Sandboxed to `memory/`,
  `skills/`, `knowledge/`; network disabled; 15 s wall-clock; 20 KB
  output. Use when the deliverable is a durable file — **not** as a
  scratchpad for transient text.

If the target path is outside the write sandbox roots, the operation does
not belong in `write_file`; route it through the appropriate artifact or
session channel instead.

## Knowledge lookup — `search_knowledge_base`

Single-tool family. `inspection` scope, read-only, concurrency-safe,
`evidence_requirement = recommended`. Default for any in-repo knowledge
pull under `backend/knowledge/`. Prefer it over `read_file` when the
question is "what do we know about X?" rather than "open this specific
file." Unlike `read_file`, it returns ranked, multi-document snippets and
respects the knowledge index.

## Helper agents — `plan_agent` vs `verification_agent`

Both are `inspection` scope and return structured JSON artifacts.

- **`plan_agent`** — invoke before broad tool use on non-trivial tasks to
  get an ordered execution plan with per-step `preferred_tool_order`. The
  plan is advisory, not enforced.
- **`verification_agent`** — invoke after execution to validate claims
  against captured evidence. `verifier_exposed = true`; its companion
  surface is `evidence_review`.

Do not call `plan_agent` for trivial single-tool tasks; the overhead
dominates. Do not skip `verification_agent` on tasks that produce claims
destined for a user-facing answer.

## Quick cross-family rules

- If two tools could work, prefer the one with `access_scope =
  "inspection"` — it is safer and dispatchable in parallel.
- If a tool is `destructive` or `requires_approval`, assume it will prompt
  the operator; plan around the interruption rather than retrying on
  rejection.
- Sandboxed tools (`python_repl`, `fetch_url`, `http_json`, `write_file`)
  enforce hard timeouts and output caps. If you need more, the answer is
  usually a different tool, not a longer retry.
- Evidence-bearing tools (`ncbi_eutils`, `evidence_retrieval`,
  `evidence_review`, `entity_grounding`, `uniprot_api`, `ensembl_api`,
  `search_knowledge_base`) should always attach provenance; the registry
  declares this expectation via `evidence_requirement`.
