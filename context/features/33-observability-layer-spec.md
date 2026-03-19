# Observability Layer Spec

## Overview

Add operational metrics and tracing so production workflows can be monitored and improved. This phase is about visibility into performance, failure modes, queueing, QC outcomes, and evidence coverage, not just debug logging.

## Requirements

- Define the first metrics set:
  - chat latency
  - workflow duration
  - step duration
  - failure rate
  - block rate
  - QC pass rate
  - evidence coverage rate
- Add correlation between frontend-visible runs and backend metrics via stable IDs.
- Define how to distinguish user-facing latency from backend execution latency.
- Ensure metrics collection does not require parsing free-text logs.
- Add one lightweight tracing story for multi-step workflow execution.
- Define operational dashboards or reports to be built later from these signals.
- Keep the design compatible with both local development and cluster-backed execution.

## References

- @backend/api/chat.py
- @backend/graph/agent.py
- @backend/graph/session_manager.py
- @frontend/src/lib/store.tsx
- @context/features/11-workflow-event-streaming-spec.md
- @context/features/29-slurm-run-manager-upgrade-spec.md
- @context/features/32-audit-logging-spec.md
