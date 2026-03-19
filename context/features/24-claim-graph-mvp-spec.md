# Claim Graph MVP Spec

## Overview

Represent scientific claims and their supporting or conflicting evidence as a graph of explicit relationships. This phase should make later contradiction detection, evidence summaries, and audit review much easier by removing claim logic from ad hoc prose.

## Requirements

- Define the first graph node types:
  - claim
  - evidence card
  - entity
  - workflow result
- Define the first edge types:
  - supports
  - contradicts
  - mentions
  - derived_from
  - evaluated_by
- Store claim text separately from evidence linkage so claims can be revised without losing provenance.
- Require each claim node to record confidence, status, and provenance to its generating context.
- Ensure claims can point to either literature evidence or internal workflow outputs.
- Add a simple contradiction detection rule set for v1, even if conservative.
- Ensure the graph can be regenerated from underlying artifacts if needed.

## References

- @backend/knowledge/literature-synthesis-guidelines.md
- @context/features/04-artifact-registry-mvp-spec.md
- @context/features/21-evidence-retrieval-mvp-spec.md
- @context/features/22-entity-grounding-mvp-spec.md
- @context/features/23-evidence-review-flow-spec.md
