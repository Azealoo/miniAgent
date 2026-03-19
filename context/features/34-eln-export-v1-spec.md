# ELN Export V1 Spec

## Overview

Enable export of experiments and workflow runs into open, portable formats suitable for electronic lab notebook or research-object style sharing. This phase should prioritize portability and preservation over vendor-specific integrations.

## Requirements

- Define the first exportable scope:
  - protocol runs
  - workflow runs
  - report bundles
  - evidence summaries if relevant
- Reuse existing artifact and provenance records instead of reserializing hidden state.
- Define one export package structure and manifest.
- Ensure exported bundles preserve links between experiments, datasets, results, and provenance.
- Make export behavior deterministic so the same run exports the same logical content.
- Mark missing or unsupported fields clearly instead of silently dropping them.

## References

- @context/features/19-provenance-export-v1-spec.md
- @context/features/25-protocol-executor-mvp-spec.md
- ELN file format guidance
- RO-Crate specification
