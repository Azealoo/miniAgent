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
  - `run_id`
  - creation timestamp
  - `source_workflow` or `source_tool`
  - optional `source_agent` when agent provenance is useful in addition to the required workflow/tool source
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

## Schema Examples

These examples are intentionally implementation-grade and align with the stable artifact filenames introduced by the artifact naming standard.

### `dataset_manifest.yaml`

```yaml
schema_version: "1.0.0"
artifact_type: dataset_manifest
id: ds-norman-perturb-seq-v1
run_id: run-20260318T193000Z-deadbeef
created_at: 2026-03-18T19:30:00Z
source_workflow: dataset-intake
related_artifacts:
  - artifact_type: workflow_run
    path: artifacts/dataset-intake/2026-03-18/run-20260318T193000Z-deadbeef/run.json
    id: workflow-run-dataset-intake-v1
    run_id: run-20260318T193000Z-deadbeef
assay_type: perturb_seq
organism: homo_sapiens
reference_build: grch38
privacy_classification: controlled
design:
  study_name: norman-perturb-seq-pilot
  experiment_type: perturb_seq
  condition_summary: CRISPRi perturb-seq pilot with non-targeting controls and donor replicates.
source_files:
  - data/norman/counts.h5ad
```

### `run.json`

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "workflow_run",
  "id": "workflow-run-rna-seq-qc-20260318",
  "run_id": "run-20260318T193000Z-deadbeef",
  "created_at": "2026-03-18T19:30:00Z",
  "source_workflow": "internal-dag-runner",
  "related_artifacts": [],
  "workflow": {"name": "RNA Seq QC", "slug": "rna-seq-qc"},
  "lifecycle_status": "completed",
  "qc_status": "warning",
  "engine": "internal_dag_runner_v1",
  "parameters": {"min_genes": 200},
  "environment": {"conda_env": "miniAgent", "platform": "linux"},
  "inputs": [],
  "outputs": [],
  "provenance_exports": [
    "artifacts/rna-seq-qc/2026-03-18/run-20260318T193000Z-deadbeef/prov.json"
  ]
}
```

### `evidence_card.yaml`

```yaml
schema_version: "1.0.0"
artifact_type: evidence_card
id: evidence-pmid-12345678
run_id: run-20260318T193000Z-deadbeef
created_at: 2026-03-18T19:30:00Z
source_workflow: literature-retrieval
related_artifacts: []
source_database: pubmed
stable_identifier: pmid:12345678
title: Perturb-seq reveals reproducible interferon-response programs across donors
claims:
  - id: interferon-program-shared-across-donors
    statement: Donor-matched perturb-seq profiles preserved a shared interferon-response program across replicates.
    confidence: high
confidence: high
limitations:
  - Cohort size was limited and not all perturbations replicated equally across batches.
cached_raw_payload_path: backend/knowledge/cache/pubmed/12345678.md
```

### `compliance_report.json`

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "compliance_report",
  "id": "compliance-rna-seq-qc-20260318",
  "run_id": "run-20260318T193000Z-deadbeef",
  "created_at": "2026-03-18T19:30:00Z",
  "source_tool": "guide_risk_precheck",
  "related_artifacts": [],
  "risk_category": "privacy",
  "triggered_rules": [
    {
      "rule_id": "privacy-identifiers-in-sample-sheet",
      "category": "privacy",
      "trigger_text": "Patient sheet includes direct identifiers in uploaded metadata columns.",
      "severity": "high",
      "recommended_action": "require_approval"
    }
  ],
  "block_status": "not_blocked",
  "human_approval_required": true,
  "final_disposition": "require_approval"
}
```

### `protocol_run.yaml`

```yaml
schema_version: "1.0.0"
artifact_type: protocol_run
id: protocol-run-rna-extraction-20260318
run_id: run-20260318T193000Z-deadbeef
created_at: 2026-03-18T19:30:00Z
source_workflow: protocol-executor
related_artifacts: []
protocol_source:
  artifact_type: protocol_document
  path: backend/knowledge/protocols/rna_extraction.md
  id: rna-extraction-standard-v1
operator: wetlab-operator-01
sample_ids:
  - sample-001
materials:
  - id: lysis-buffer
    name: Lysis Buffer
started_at: 2026-03-18T19:31:00Z
completed_at: 2026-03-18T20:05:00Z
completion_state: completed
deviations: []
assumptions: []
```

### `qa_report.json`

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "qa_report",
  "id": "qa-rna-seq-qc-20260318",
  "run_id": "run-20260318T193000Z-deadbeef",
  "created_at": "2026-03-18T19:40:00Z",
  "source_workflow": "qa-review",
  "related_artifacts": [],
  "overall_status": "warning",
  "failed_checks": [],
  "warnings": ["One donor replicate exceeded the ambient RNA warning threshold."],
  "missing_artifacts": [],
  "recommended_remediation": ["Review donor-specific QC thresholds before final report publication."],
  "checklist_artifacts": []
}
```

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
