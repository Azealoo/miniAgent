# Slurm Run Manager Upgrade Spec

## Overview

Evolve the current safe Slurm command wrapper into a structured run manager suitable for workflow execution. The current tool can submit and inspect jobs, but production biology workflows need explicit resource contracts, job records, log capture, and stable links back to run artifacts.

## Requirements

- Keep the existing safety posture of no arbitrary shell execution.
- Add a structured submission mode that records:
  - job ID
  - submitted script
  - resource request
  - working directory
  - run ID
  - submission time
- Capture stdout, stderr, and log paths as structured outputs or linked artifacts.
- Define a job record artifact that can be connected to workflow runs.
- Support status polling and terminal state normalization:
  - pending
  - running
  - completed
  - failed
  - cancelled
  - timed out
- Make it possible for the workflow runner to resume from stored job records instead of losing track after process restart.
- Preserve project-root path restrictions for submitted scripts.
- Add explicit resource contract fields instead of relying only on opaque `sbatch` strings.

## References

- @backend/tools/slurm_tool.py
- @backend/skills/analysis_to_slurm_runner/SKILL.md
- @backend/skills/slurm_job_template/SKILL.md
- @backend/knowledge/cluster-slurm-runbooks.md
- @context/features/10-internal-dag-runner-mvp-spec.md
- @context/features/30-external-workflow-adapter-v1-spec.md
- Slurm `sbatch` documentation
