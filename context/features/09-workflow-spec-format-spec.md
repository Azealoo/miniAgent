# Workflow Spec Format Spec

## Overview

Define the file format that describes explicit biology workflows. This is the contract between planning, execution, compliance, and artifact generation. A workflow spec should be readable by humans, validated by code, and specific enough that the runner can execute it without guessing hidden logic.

## Requirements

- Define a workflow spec file format and storage location, for example under `workflows/`.
- Each workflow spec must include:
  - workflow ID
  - version
  - purpose
  - required inputs
  - optional inputs
  - steps
  - outputs
  - QC gates
  - compliance hooks
  - engine or executor type
- Define a step model that supports:
  - step ID
  - human label
  - tool or executor
  - input bindings
  - output bindings
  - prerequisites
  - retry policy
  - failure policy
- Define how workflow specs reference dataset manifests, artifact schemas, and future report templates.
- Make step outputs explicit so later steps can only consume declared outputs, not hidden global state.
- Support both internal Python-executed steps and external engine-backed steps.
- Define which parts are static in the workflow spec versus dynamic per run.
- Add validation rules that fail fast for undefined step references, missing required inputs, or cyclic dependencies.

## References

- @backend/graph/agent.py
- @backend/tools/slurm_tool.py
- @backend/knowledge/data-and-pipeline-conventions.md
- @backend/skills/analysis_to_slurm_runner/SKILL.md
- @backend/skills/run_pipeline_safely/SKILL.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/10-internal-dag-runner-mvp-spec.md
- Nextflow documentation
- Snakemake documentation
- Common Workflow Language specification
