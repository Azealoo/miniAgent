# Entity Grounding MVP Spec

## Overview

Normalize biological entities so workflows, evidence cards, and future interpretation logic stop depending on unstable free-text names. This phase should focus on genes, proteins, and related identifiers using the APIs already present in the repo.

## Requirements

- Define the first supported entity classes:
  - gene
  - protein
  - transcript if needed
- Define one normalized internal representation for an entity and its aliases.
- Use existing API tools to ground user-provided names to stable accessions or identifiers.
- Record source database, identifier version when relevant, preferred label, aliases, species, and unresolved ambiguity.
- Define behavior for ambiguous matches:
  - prompt for clarification if required
  - otherwise record ambiguity explicitly and avoid overconfident linking
- Make evidence cards and workflow artifacts able to reference normalized entities instead of plain text only.
- Add caching or artifact persistence for grounding results so repeated lookups are not opaque.

## References

- @backend/tools/uniprot_api_tool.py
- @backend/tools/ensembl_api_tool.py
- @backend/skills/gene_symbol_normalizer/SKILL.md
- @backend/skills/ncbi_gene_lookup/SKILL.md
- @backend/skills/uniprot_lookup/SKILL.md
- @backend/skills/ortholog_mapper/SKILL.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/21-evidence-retrieval-mvp-spec.md
