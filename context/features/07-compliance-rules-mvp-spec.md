# Compliance Rules MVP Spec

## Overview

Add the first deterministic compliance and safety screening layer before the agent performs biology-sensitive work. This phase should not try to solve every regulatory case. It should create the rule engine, trigger taxonomy, and structured outputs needed to identify obviously risky requests and route them into allow, block, or review-required states.

## Requirements

- Define the first set of compliance categories:
  - biosafety
  - human subjects
  - privacy and protected data
  - dangerous procedural guidance
  - sensitive export or sharing constraints
- Implement deterministic trigger rules before any model-based judgment layer.
- Define the minimum input inspected by the rules engine:
  - user message
  - attached identifiers or filenames if present
  - selected workflow type if known
- Produce a machine-readable `compliance_report` artifact or equivalent structured object.
- Require each triggered rule to record:
  - rule ID
  - category
  - trigger text or matched feature
  - severity
  - recommended action
- Define the initial action states:
  - allow
  - allow with warning
  - require approval
  - block
- Ensure no risky execution tool runs before the compliance preflight completes.
- Make the rule set editable and reviewable, ideally file-based rather than hard-coded only.
- Add tests that prove representative risky requests are flagged before execution begins.

## References

- @backend/api/chat.py
- @backend/graph/agent.py
- @backend/workspace/AGENTS.md
- @backend/knowledge/guide-risk-checklist.md
- @backend/knowledge/skill-safety-review-checklist.md
- @backend/skills/guide_risk_precheck/SKILL.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/08-compliance-block-flow-spec.md
- BMBL biosafety guidance
- HHS 45 CFR 46 Common Rule
- HIPAA Privacy Rule
