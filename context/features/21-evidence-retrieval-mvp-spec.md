# Evidence Retrieval MVP Spec

## Overview

Build the first structured evidence pipeline so literature retrieval becomes durable scientific memory instead of one-off summaries. This phase should use stable identifiers and cached raw responses to create evidence cards the agent can cite, review, and reuse later.

## Requirements

- Make NCBI-backed evidence retrieval the first supported literature path.
- Define the lifecycle:
  - search for candidate records
  - select stable IDs
  - fetch authoritative metadata
  - normalize to `evidence_card`
  - cache raw payloads
- Require evidence cards to be keyed by a stable identifier such as PMID.
- Store both normalized evidence cards and raw fetched payloads.
- Define minimum evidence-card fields for v1:
  - source database
  - stable identifier
  - title
  - study type if inferable
  - claims
  - limitations
  - entity tags
  - cached source path
- Prevent silent regeneration that overwrites prior evidence without versioning or traceability.
- Support linking evidence cards into sessions, reports, and future claim graphs.

## References

- @backend/tools/ncbi_eutils_tool.py
- @backend/skills/pubmed_search/SKILL.md
- @backend/skills/pubmed_fetch_abstract/SKILL.md
- @backend/skills/paper_triage/SKILL.md
- @backend/knowledge/literature-synthesis-guidelines.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/04-artifact-registry-mvp-spec.md
- NCBI E-utilities documentation
