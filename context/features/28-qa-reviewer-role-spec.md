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
- Link the reviewer inputs explicitly through durable artifact references in the emitted `qa_report`, including:
  - `workflow_run`
  - structured `report_bundle_manifest`
  - human-readable `report_bundle`
  - linked `compliance_report`
  - linked `evidence_review` and `evidence_card` artifacts when interpretation claims are present
- Treat compliance review and QA review as separate gates:
  - compliance review remains the deterministic policy and approval gate
  - QA review remains the post-run artifact, provenance, evidence, checklist, and deviation gate
- If a workflow emits a `qa_report`, honor `overall_status in {failed, blocked}` as a publish-blocking outcome before final stable outputs are promoted for publication.
- Keep generated reviewer artifacts on disk even when final publication is blocked so the failed QA state remains inspectable and auditable.

## References

- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/18-report-bundle-v1-spec.md
- @context/features/26-deviation-logging-spec.md
- @context/features/27-checklist-gates-spec.md
- NIH rigor and transparency guidance
