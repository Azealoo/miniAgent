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

## References

- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/17-de-analysis-integration-spec.md
- @context/features/19-provenance-export-v1-spec.md
- Official BioCompute specification
