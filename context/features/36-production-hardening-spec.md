# Production Hardening Spec

## Overview

Harden the system for real-world deployment once the workflow, evidence, compliance, and artifact foundations are in place. This phase should consolidate safety, permissions, authentication, sandboxing, secrets handling, test coverage, and failure recovery into a deployment-ready posture.

## Requirements

- Review all execution-capable tools and define least-privilege policies for each.
- Tighten shell, file, and job execution boundaries so workflow features do not broaden the attack surface unintentionally.
- Define authentication and authorization requirements for user actions, approvals, exports, and connector use.
- Define secrets handling for API keys, cluster credentials, and external service tokens.
- Add explicit backup and restore expectations for sessions, artifacts, and registry state.
- Define failure-recovery behavior for interrupted workflow runs, partial exports, and transient external API failures.
- Expand the automated test matrix to include:
  - security-sensitive path tests
  - compliance gate tests
  - workflow persistence tests
  - artifact validation tests
- Define a deployment checklist for local, HPC, and any future hosted environments.

## References

- @backend/api/chat.py
- @backend/api/files.py
- @backend/config.py
- @backend/tools/terminal_tool.py
- @backend/tools/python_repl_tool.py
- @backend/tools/read_file_tool.py
- @backend/tools/write_file_tool.py
- @backend/tools/slurm_tool.py
- @backend/tests/test_tools.py
- @backend/tests/test_config.py
- @context/features/07-compliance-rules-mvp-spec.md
- @context/features/31-reproducibility-drills-spec.md
- @context/features/32-audit-logging-spec.md
