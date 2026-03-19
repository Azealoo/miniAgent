# Report Bundle V1 Spec

## Overview

Create a standard report bundle for completed workflow runs so users receive a consistent, audit-friendly output instead of a pile of unrelated files. This report should act as the primary handoff artifact for humans while still pointing cleanly to structured machine artifacts.

## Requirements

- Define the contents of a minimum report bundle for any completed workflow:
  - executive summary
  - inputs used
  - workflow version
  - QC summary
  - key outputs
  - warnings and failures
  - provenance pointers
  - next recommended actions
- Require the report bundle to link to the canonical run record instead of duplicating all metadata.
- Ensure the report makes QC pass/fail state obvious.
- Ensure blocked or partial runs still get a partial report bundle with clear status.
- Support both Markdown and machine-readable summary output if useful.
- Make the report bundle reference evidence cards when interpretation claims are included.
- Define a naming convention and storage location that matches the artifact standard.

## References

- @context/features/02-artifact-naming-standard-spec.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/15-fastqc-integration-spec.md
- @context/features/16-multiqc-integration-spec.md
- @context/features/17-de-analysis-integration-spec.md
- @context/features/19-provenance-export-v1-spec.md
