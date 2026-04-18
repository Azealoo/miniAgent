# BioCompute Export V1 Spec

## Overview

Add optional BioCompute export for computational biology workflows where a more domain-specific execution record is valuable. This should build on the workflow run and provenance artifacts rather than becoming a separate parallel truth source.

## Requirements

- Define which workflow classes should emit BioCompute objects in v1.
- Map existing workflow run fields into the BioCompute structure rather than inventing duplicate fields.
- Ensure all BioCompute exports reference the same inputs, outputs, parameters, and provenance IDs already used elsewhere.
- Make BioCompute export optional but deterministic for supported workflows.
- Document how missing required BioCompute fields should be handled:
  - block export
  - emit partial export with warnings
- Add at least one concrete example for an RNA-seq style workflow.

## Authored Contract

- V1 support is intentionally narrow:
  - emit BioCompute only for the authored `rnaseq_qc_de` workflow
  - leave unsupported workflows unchanged with `workflow_run.biocompute_exports = []`
- Persist BioCompute as the stable root artifact `biocompute.json` and record additive run-level pointers in `workflow_run.biocompute_exports`.
- Materialize BioCompute only after terminal provenance is available so the export can reference canonical `run.json`, `prov.json`, and `ro-crate/ro-crate-metadata.json` paths already persisted on disk.
- Derive BioCompute content from existing file-first sources:
  - `workflow_run.inputs` and `workflow_run.outputs` for IO-domain references
  - `workflow_run.parameters` for parametric-domain entries
  - `prov.json` tool versions and artifact IDs for software prerequisites and provenance cross-references
  - `dataset_manifest.yaml` for study, assay, organism, and reference-build context when available
- For BioCompute fields that require URIs, emit fetchable raw-file URLs or other standards-valid URIs rather than BioAPEX-internal relative paths.
- Missing BioCompute-required source data must not fail the workflow. Emit a partial BioCompute export instead and record that explicitly in `extension_domain`:
  - `export_status: partial`
  - `export_warnings: [...]`
- Emit a standards-style `error_domain` for every BioCompute export using explicit `empirical_error` and `algorithmic_error` entries keyed by namespaced URIs rather than a BioAPEX-only warning counter object.
- `extension_domain[*].extension_schema` must point to a fetchable schema URL; in BioAPEX v1 this should resolve through the backend raw file API to `artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json`, using the configured public BioAPEX base URL when one is provided.
- Validate the BioCompute standards-facing payload against vendored official IEEE 2791 reference schemas and validate each emitted extension payload against its referenced BioAPEX extension schema before treating the export as materialized.
- Pin `spec_version` to the IEEE 2791 schema URL and keep the exported object deterministic from persisted files plus the workflow spec, not hidden runtime state.
- Use `license: NOASSERTION` in v1 because BioAPEX does not yet infer or persist dataset/export licensing metadata.

## Example

- Concrete RNA-seq example artifact: `backend/artifacts/examples/biocompute.json`
- Example run-level pointer contract:

```json
{
  "artifact_type": "workflow_run",
  "provenance_exports": [
    "artifacts/rnaseq_qc_de/2026-03-18/run-20260318T193000Z-deadbeef/prov.json",
    "artifacts/rnaseq_qc_de/2026-03-18/run-20260318T193000Z-deadbeef/ro-crate/ro-crate-metadata.json"
  ],
  "biocompute_exports": [
    "artifacts/rnaseq_qc_de/2026-03-18/run-20260318T193000Z-deadbeef/biocompute.json"
  ]
}
```

## References

- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/17-de-analysis-integration-spec.md
- @context/features/19-provenance-export-v1-spec.md
- Official BioCompute specification
