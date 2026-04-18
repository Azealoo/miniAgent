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

## Implementation Notes

- Materialize the MVP as a durable `claim_graph.json` artifact under the canonical artifact layout.
- Expose a deterministic `claim_graph` tool that accepts existing `evidence_card`, `evidence_review`, `entity_grounding`, and `workflow_run` artifact paths as graph inputs.
- Represent `evidence_review` artifacts as `workflow_result` nodes so reviewed conclusions can point to internal workflow outputs without inventing a new node class in v1.
- Materialize workflow-backed claim nodes directly from `workflow_run` lifecycle, QC, summary-metric, and warning fields with `workflow_summary` provenance, explicit `workflow_result` edges, and support for workflow-only graph builds.
- Keep claim statements in claim nodes and all support/contradiction/entity/workflow linkage in explicit edges.
- Make contradiction detection deterministic and explainable:
  - require overlapping grounded-entity context or overlapping topic tokens
  - require opposing polarity cues
  - prefer conservative false negatives over opaque false positives

## References

- @backend/knowledge/literature-synthesis-guidelines.md
- @context/features/04-artifact-registry-mvp-spec.md
- @context/features/21-evidence-retrieval-mvp-spec.md
- @context/features/22-entity-grounding-mvp-spec.md
- @context/features/23-evidence-review-flow-spec.md
