# RNA-seq Workflow Skeleton Spec

## Overview

Create the first explicit biology workflow that proves the new workflow layer can represent a common end-to-end analysis task. This phase is about structure, contracts, and orchestration. It should not assume every downstream tool integration is finished yet.

## Requirements

- Define a workflow named something like `rnaseq_qc_de`.
- Require the workflow to declare these logical stages:
  - dataset intake
  - compliance preflight
  - raw QC
  - aggregated QC
  - quantification or count generation
  - differential expression
  - report bundle creation
- Define the required user-supplied inputs and their schema references.
- Define the expected output artifacts even if some steps are stubbed initially.
- Require step boundaries to be explicit so later FastQC, MultiQC, DE, and provenance integrations can plug in cleanly.
- Ensure the workflow can fail early if intake, QC, or compliance gates do not pass.
- Add one example manifest and one example workflow plan to the spec.

## Authored Contract

- Workflow ID: `rnaseq_qc_de`
- Required inputs:
  - `dataset_manifest` via `artifact_schema:dataset_manifest@1.0.0`
  - `condition_field` metadata string
  - `baseline_condition` metadata string
  - `comparison_condition` metadata string
- Explicit stages:
  - `dataset_intake`
  - `compliance_preflight` via a `before_execution` compliance hook
  - `raw_qc`
  - `aggregated_qc`
  - `quantification`
  - `differential_expression`
  - `report_bundle`
- Declared workflow outputs:
  - `fastqc_run` durable artifact via `artifact_schema:fastqc_run@1.0.0`
  - `fastqc_metrics` durable artifact via `artifact_schema:fastqc_metrics@1.0.0`
  - `quantification_bundle` value handle for future count-generation artifacts
  - `differential_expression_bundle` value handle for future DE artifacts
  - `report_bundle_manifest` value handle for the final bundle contract
  - `qa_report` durable artifact via `artifact_schema:qa_report@1.0.0`
- Early-failure behavior:
  - block before execution if `dataset_manifest` is missing
  - run `compliance_preflight` before any stage starts
  - evaluate a raw-QC gate after `raw_qc`
  - evaluate an aggregated-QC gate after `aggregated_qc`

## Example Manifest

Example file: `backend/artifacts/examples/rnaseq_dataset_manifest.yaml`

```yaml
schema_version: "1.0.0"
artifact_type: dataset_manifest
id: ds-bulk-rnaseq-demo-v1
run_id: run-20260319T200000Z-14aa00ff
created_at: 2026-03-19T20:00:00Z
source_workflow: dataset-intake
related_artifacts: []
assay_type: bulk_rna_seq
organism: homo_sapiens
reference_build: grch38
sample_sheet_path: backend/artifacts/examples/rnaseq/sample_sheet.tsv
privacy_classification: controlled
design:
  study_name: interferon-rnaseq-pilot
  experiment_type: bulk_rna_seq
  condition_summary: Bulk RNA-seq pilot comparing treated and control libraries for differential expression.
  analysis_kind: comparative
  condition_fields:
    - condition
  batch_fields:
    - batch
  replicate_structure: 3 control and 3 treated libraries
  timepoints:
    - end_point
  factors:
    - condition
    - batch
source_files:
  - backend/artifacts/examples/rnaseq/control_rep1_R1.fastq
  - backend/artifacts/examples/rnaseq/control_rep1_R2.fastq
  - backend/artifacts/examples/rnaseq/control_rep2_R1.fastq
  - backend/artifacts/examples/rnaseq/control_rep2_R2.fastq
  - backend/artifacts/examples/rnaseq/control_rep3_R1.fastq
  - backend/artifacts/examples/rnaseq/control_rep3_R2.fastq
  - backend/artifacts/examples/rnaseq/treated_rep1_R1.fastq
  - backend/artifacts/examples/rnaseq/treated_rep1_R2.fastq
  - backend/artifacts/examples/rnaseq/treated_rep2_R1.fastq
  - backend/artifacts/examples/rnaseq/treated_rep2_R2.fastq
  - backend/artifacts/examples/rnaseq/treated_rep3_R1.fastq
  - backend/artifacts/examples/rnaseq/treated_rep3_R2.fastq
assay_extensions:
  workflow_stub:
    aggregated_qc:
      fastqc_pass_rate: 1.0
      libraries_aggregated: 6
```

## Example Workflow Plan

Example file: `backend/artifacts/examples/rnaseq_workflow_plan.json`

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "workflow_plan",
  "run_id": "run-20260319T200500Z-14aa00ff",
  "created_at": "2026-03-19T20:05:00Z",
  "source_workflow": "rnaseq_qc_de",
  "workflow_id": "rnaseq_qc_de",
  "inputs": {
    "dataset_manifest": "backend/artifacts/examples/rnaseq_dataset_manifest.yaml",
    "condition_field": "condition",
    "baseline_condition": "control",
    "comparison_condition": "treated"
  },
  "steps": [
    {"id": "dataset_intake", "name": "Dataset intake and manifest validation"},
    {"id": "compliance_preflight", "name": "Compliance preflight"},
    {"id": "raw_qc", "name": "FastQC raw-read QC stage"},
    {"id": "aggregated_qc", "name": "Aggregated QC placeholder stage"},
    {"id": "quantification", "name": "Quantification planning skeleton stage"},
    {"id": "differential_expression", "name": "Differential expression planning skeleton stage"},
    {"id": "report_bundle", "name": "Report bundle skeleton stage"}
  ],
  "expected_outputs": [
    {
      "name": "fastqc_run",
      "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T200500Z-14aa00ff/fastqc_run.json"
    },
    {
      "name": "fastqc_metrics",
      "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T200500Z-14aa00ff/fastqc_metrics.json"
    },
    {
      "name": "quantification_bundle",
      "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T200500Z-14aa00ff/outputs/generated/quantification/quantification_bundle.json"
    },
    {
      "name": "differential_expression_bundle",
      "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T200500Z-14aa00ff/outputs/generated/differential-expression/differential_expression_bundle.json"
    },
    {
      "name": "report_bundle_manifest",
      "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T200500Z-14aa00ff/outputs/generated/report-bundle/report_bundle_manifest.json"
    },
    {
      "name": "qa_report",
      "path": "artifacts/rnaseq-qc-de/2026-03-19/run-20260319T200500Z-14aa00ff/qa_report.json"
    }
  ]
}
```

## References

- @backend/knowledge/data-and-pipeline-conventions.md
- @backend/skills/run_pipeline_safely/SKILL.md
- @backend/skills/analysis_to_slurm_runner/SKILL.md
- @context/features/09-workflow-spec-format-spec.md
- @context/features/10-internal-dag-runner-mvp-spec.md
- @context/features/15-fastqc-integration-spec.md
- @context/features/16-multiqc-integration-spec.md
- @context/features/17-de-analysis-integration-spec.md
- nf-core/rnaseq documentation
