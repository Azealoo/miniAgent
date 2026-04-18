# Audit Logging Spec

## Overview

Create an audit trail for the system’s operationally important actions. This phase should capture enough detail to reconstruct who requested what, what the system did, what was blocked, what artifacts were produced, and which external systems were touched.

## Requirements

- Define the audit event types that matter for v1:
  - chat request received
  - compliance decision
  - workflow started
  - workflow finished
  - tool invoked
  - file written
  - job submitted
  - export generated
- Ensure audit records are append-only and timestamped.
- Capture correlation IDs such as session ID, run ID, step ID, and job ID when available.
- Avoid logging sensitive payloads in unsafe detail; define a redaction policy.
- Ensure blocked and failed actions are logged, not just successful ones.
- Make audit logs queryable enough for later operational review.
- Define retention or rotation expectations if logs become large.

## References

- @backend/api/chat.py
- @backend/api/files.py
- @backend/graph/session_manager.py
- @backend/tools/slurm_tool.py
- @context/features/07-compliance-rules-mvp-spec.md
- @context/features/08-compliance-block-flow-spec.md
- @context/features/29-slurm-run-manager-upgrade-spec.md
