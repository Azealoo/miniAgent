# Core Schema Pack V1 Spec

## Overview

Define the first version of the structured artifact schemas that all later workflow, evidence, compliance, and protocol features will depend on. The goal is to replace loosely structured text outputs with explicit, versioned documents that can be validated, indexed, tested, and exported.

## Requirements

- Create versioned schemas for the following artifact types:
  - `dataset_manifest`
  - `workflow_run`
  - `evidence_card`
  - `compliance_report`
  - `protocol_run`
  - `qa_report`
- Choose the file format for each schema deliberately:
  - YAML for human-edited inputs such as manifests and protocol runs
  - JSON for machine-emitted records such as workflow runs and compliance reports unless a strong reason exists otherwise
- Require every schema to include:
  - `schema_version`
  - unique identifier
  - creation timestamp
  - source agent or workflow
  - pointers to related artifacts
- Define required versus optional fields for each schema so the orchestrator can block incomplete work.
- Define validation rules for each schema:
  - field types
  - enumerations
  - path format rules
  - identifier normalization rules
- Make dataset manifests explicit about assay type, organism, reference build, design metadata, and privacy classification.
- Make workflow runs explicit about inputs, outputs, engine, parameters, environment, QC status, and provenance exports.
- Make evidence cards explicit about source database, stable identifier, extracted claims, confidence, limitations, and cached raw payload location.
- Make compliance reports explicit about risk category, triggered rules, block status, human approval requirement, and final disposition.
- Make protocol runs explicit about operator, sample IDs, materials, reagent lots, equipment, timestamps, deviations, and completion state.
- Add schema examples to the spec so implementers can start building validators and fixtures immediately.

## References

- @backend/api/files.py
- @backend/graph/session_manager.py
- @backend/tools/write_file_tool.py
- @backend/knowledge/data-and-pipeline-conventions.md
- @backend/knowledge/literature-synthesis-guidelines.md
- @backend/knowledge/skill-safety-review-checklist.md
- @context/features/02-artifact-naming-standard-spec.md
- Official BioCompute specification
- Official RO-Crate specification
- Official W3C PROV data model
