# Artifact Naming Standard Spec

## Overview

Define a deterministic naming and storage convention for every durable artifact the system will create. This includes workflow runs, evidence cards, protocol runs, compliance reports, figures, QC outputs, and export bundles. The goal is to make every artifact human-browsable, machine-indexable, and easy to trace back to its inputs, parameters, and run context.

## Requirements

- Define one canonical `run_id` format for all execution-oriented artifacts.
- Define one canonical directory pattern for generated outputs:
  - `artifacts/<workflow>/<YYYY-MM-DD>/<run_id>/...`
- Require each run directory to contain a machine-readable root record such as `run.json` or `run.yaml`.
- Require stable filenames for common artifact classes:
  - `dataset_manifest.yaml`
  - `workflow_plan.json`
  - `compliance_report.json`
  - `evidence_card.yaml`
  - `protocol_run.yaml`
  - `qa_report.json`
  - `prov.json`
  - `ro-crate/`
- Define how content hashes are generated and where they are stored.
- Define naming rules for user-supplied files versus generated files so later registry code can distinguish them reliably.
- Require all artifact paths to be relative to the project root or another explicitly allowed root.
- Define collision behavior:
  - reruns with the same inputs must still get a new run directory
  - artifacts inside a run must not silently overwrite previous outputs
- Define a lightweight metadata header that every artifact should expose, at minimum:
  - schema version
  - artifact type
  - run ID
  - creation timestamp
  - source workflow or source tool
- Ensure the naming convention is compatible with current file APIs and future Slurm or workflow-engine outputs.

## References

- @backend/api/files.py
- @backend/config.py
- @backend/tools/write_file_tool.py
- @backend/tools/read_file_tool.py
- @backend/tools/slurm_tool.py
- @backend/knowledge/data-and-pipeline-conventions.md
- @context/features/03-core-schema-pack-v1-spec.md
- Official W3C PROV data model
- Official RO-Crate specification
