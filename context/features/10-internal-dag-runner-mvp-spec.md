# Internal DAG Runner MVP Spec

## Overview

Build the first internal workflow runner that can execute explicit step graphs and persist state to files. This runner does not need to be the final orchestration system. It needs to prove that repetitive biology tasks can execute as declared workflows rather than ad hoc tool chatter.

## Requirements

- Implement a runner that consumes the workflow spec format from the previous phase.
- Support directed acyclic graphs with explicit step dependencies.
- Persist workflow state to disk so a run can be inspected or resumed after interruption.
- Require each step to record:
  - start time
  - end time
  - status
  - inputs resolved
  - outputs produced
  - errors or warnings
- Define the run lifecycle:
  - created
  - preflight checked
  - running
  - waiting
  - failed
  - completed
  - blocked
- Support at least one internal step executor and one external command or job submission executor.
- Ensure the runner never depends on hidden Python REPL state.
- Emit a `workflow_run` record that later phases can extend.
- Add unit tests for dependency resolution, failure propagation, and state persistence.

## References

- @backend/graph/agent.py
- @backend/api/chat.py
- @backend/graph/session_manager.py
- @backend/tools/slurm_tool.py
- @backend/tests/test_tools.py
- @context/features/09-workflow-spec-format-spec.md
- @context/features/11-workflow-event-streaming-spec.md
- @context/features/29-slurm-run-manager-upgrade-spec.md
