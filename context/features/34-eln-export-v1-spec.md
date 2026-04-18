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

## Implementation Notes

- V1 materializes a file-first export manifest at `outputs/generated/eln-export/eln_export.json` and a portable archive at `outputs/generated/eln-export/eln_export_bundle.tar.gz` for terminal workflow runs.
- The archive preserves canonical `artifacts/...` relative paths under a portable root so existing run/report/provenance links remain valid without path rewriting.
- The export is built only from persisted artifacts already on disk, including the canonical run record, content hashes, workflow inputs/outputs, provenance exports, report-bundle outputs, and linked protocol/evidence artifacts when present.
- Missing artifacts and unsupported vendor-specific ELN fields are represented explicitly in the manifest instead of being omitted silently.
- `content_hashes.json` excludes the derived ELN manifest/archive outputs to avoid self-referential archive hashing while preserving canonical run-artifact digests.

## References

- @context/features/19-provenance-export-v1-spec.md
- @context/features/25-protocol-executor-mvp-spec.md
- ELN file format guidance
- RO-Crate specification
