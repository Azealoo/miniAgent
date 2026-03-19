# Checklist Gates Spec

## Overview

Define reusable checklist-based quality gates for common biology reporting and rigor standards. These gates should score completeness and block or warn when required information is missing. The main goal is to make the rigorous path easier than the sloppy path.

## Requirements

- Implement checklist definitions as editable files or structured configs, not hidden prompt text only.
- Support at least these checklist families in design:
  - MIQE-style qPCR completeness
  - PRISMA-style literature screening completeness
  - ARRIVE-style animal study reporting completeness
- Require each checklist item to record:
  - item ID
  - description
  - severity
  - pass criteria
  - remediation guidance
- Allow a run or report to be scored against one or more checklists.
- Produce a structured output artifact that can be consumed by the QA role and report bundle.
- Distinguish missing-required metadata from soft best-practice warnings.
- Make checklist results visible to the user before final outputs are considered complete.

## References

- @backend/knowledge/skill-safety-review-checklist.md
- @backend/knowledge/guide-risk-checklist.md
- @backend/knowledge/literature-synthesis-guidelines.md
- @context/features/23-evidence-review-flow-spec.md
- @context/features/28-qa-reviewer-role-spec.md
- ARRIVE guidelines
- MIQE guidelines
- PRISMA guidelines
