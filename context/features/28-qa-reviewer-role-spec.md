# QA Reviewer Role Spec

## Overview

Add a dedicated verification role that reviews produced artifacts before high-confidence outputs are finalized. This role should evaluate provenance completeness, checklist results, evidence grounding, and deviation severity, and then emit a machine-readable pass or fail assessment.

## Requirements

- Define the QA reviewer inputs:
  - workflow run record
  - report bundle
  - compliance report
  - evidence cards
  - checklist outputs
  - deviation records
- Require the QA reviewer to emit a `qa_report`.
- Include at minimum:
  - overall status
  - failed checks
  - warnings
  - missing artifacts
  - recommended remediation
- Ensure the reviewer can block final publication or export when critical requirements fail.
- Define the difference between QA review and compliance review so responsibilities stay clear.
- Add a deterministic checklist-first layer before any model synthesis in the QA role.
- Make QA review repeatable from artifacts alone.

## References

- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/18-report-bundle-v1-spec.md
- @context/features/26-deviation-logging-spec.md
- @context/features/27-checklist-gates-spec.md
- NIH rigor and transparency guidance
