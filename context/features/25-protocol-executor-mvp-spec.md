# Protocol Executor MVP Spec

## Overview

Create a high-constraint protocol execution mode that behaves more like a careful lab operator than a free-form chatbot. The phase should start by turning protocol-following into a structured run with explicit inputs, steps, materials, and output logs.

## Requirements

- Define what qualifies as a protocol-execution request and how it is routed differently from normal chat.
- Require the protocol executor to read an explicit source protocol or skill before proceeding.
- Emit a `protocol_run` artifact that captures:
  - protocol source
  - operator
  - samples
  - materials
  - reagents
  - equipment
  - timestamps
  - completion status
- Force the executor to record assumptions rather than silently infer missing procedural details.
- Ensure protocol execution can be blocked by compliance gates before operational guidance is produced.
- Make protocol steps explicit and sequential so later deviation logging can attach to them cleanly.
- Define the boundary between allowed high-level guidance and blocked unsafe procedural detail for sensitive cases.

## Implementation Notes

- Protocol-execution routing now happens in `backend/api/chat.py` after compliance preflight and before evidence-review or general agent streaming.
- The MVP uses `backend/protocol_executor.py` to require an explicit workspace protocol path or named skill source before procedural guidance is emitted.
- Missing, unreadable, or unstructured sources fail closed: BioAPEX records a blocked `protocol_run` artifact but does not emit sequential procedural instructions, and arbitrary non-protocol files are not treated as executable protocol documents.
- `protocol_run` artifacts now include explicit sequential `steps` with stable `step_id`, `sequence_number`, `title`, `instruction`, and `status` fields.
- Protocol mode includes a deterministic sensitive-procedure boundary: when the source or request matches sensitive operational signals, BioAPEX records the blocked run but withholds step-by-step guidance even if generic compliance preflight alone would have allowed the turn.

## References

- @backend/skills/protocol_from_knowledge/SKILL.md
- @backend/skills/buffer_recipe_scaler/SKILL.md
- @backend/skills/dilution_calculator/SKILL.md
- @backend/skills/unit_conversion/SKILL.md
- @backend/skills/guide_risk_precheck/SKILL.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/07-compliance-rules-mvp-spec.md
- @context/features/26-deviation-logging-spec.md
