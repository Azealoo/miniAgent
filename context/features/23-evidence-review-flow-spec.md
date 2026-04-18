# Evidence Review Flow Spec

## Overview

Create the execution logic that turns evidence cards into a reviewable evidence workflow. The goal is to ensure that important scientific claims are grounded in structured sources and that the agent can clearly separate retrieved evidence from interpretation.

## Requirements

- Define when the system must enter evidence-review mode instead of answering directly from chat context alone.
- Require factual biology claims used in reports or recommendations to point to one or more evidence cards.
- Define the minimum review outputs:
  - evidence included
  - evidence excluded
  - limitations noted
  - confidence level
  - unresolved conflicts
- Ensure the agent distinguishes extracted source facts from synthesized conclusions.
- Support linking evidence review outputs into session summaries, report bundles, and QA review.
- Define a fallback behavior when no adequate evidence is found.
- Add UI or backend-visible markers that make unsupported claims obvious.

## References

- @backend/skills/paper_triage/SKILL.md
- @backend/skills/literature_consensus_map/SKILL.md
- @backend/knowledge/literature-synthesis-guidelines.md
- @context/features/21-evidence-retrieval-mvp-spec.md
- @context/features/22-entity-grounding-mvp-spec.md
- @context/features/24-claim-graph-mvp-spec.md
- @context/features/28-qa-reviewer-role-spec.md
