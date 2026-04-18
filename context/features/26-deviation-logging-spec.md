# Deviation Logging Spec

## Overview

Make deviations from workflows or protocols explicit, structured, and reviewable. This phase is critical because real biology work rarely follows the ideal path exactly, and production-grade traceability requires the system to record what changed, why it changed, and what the likely impact was.

## Requirements

- Define a deviation record schema that can attach to a protocol step or workflow step.
- Require each deviation to record:
  - source run ID
  - step ID
  - timestamp
  - original expected behavior
  - actual behavior
  - reason
  - impact assessment
  - author or agent
- Ensure deviations can be created manually by the user or automatically by the system when expected outputs do not match the workflow spec.
- Add severity levels so QA and reports can highlight important deviations.
- Ensure deviations appear in protocol runs, workflow runs, and report bundles.
- Prevent deviations from being hidden only inside free-text chat messages.

## References

- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/18-report-bundle-v1-spec.md
- @context/features/25-protocol-executor-mvp-spec.md
- @context/features/28-qa-reviewer-role-spec.md
