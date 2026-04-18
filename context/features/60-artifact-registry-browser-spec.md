# Artifact Registry Browser Spec

## Overview

Build a first-class artifact registry browser so BioAPEX’s file-first and provenance-rich backend becomes visible in the frontend. This phase should go beyond the current generated-files list and expose the actual registry of workflow outputs, evidence artifacts, compliance reports, and related records.

## Requirements

- Add a dedicated artifact registry browsing surface in the frontend.
- The artifact browser should support filtering by the real backend fields:
  - `run_id`
  - `artifact_type`
  - `workflow`
  - `date`
  - `dataset_id`
  - `include_invalid`
- Present artifact rows/cards with enough metadata to distinguish:
  - run records
  - workflow outputs
  - evidence cards
  - compliance reports
  - provenance bundles
  - related artifacts
- Make it easy to understand which workflow or run produced an artifact.
- Provide a drill-in path from an artifact registry entry to:
  - a raw file preview
  - a structured metadata view
  - the originating run when available
- Keep the browser usable both as a dedicated workspace and as a supporting inspector surface.
- Include empty, loading, filtered-empty, and invalid-artifact states.
- Keep the experience aligned with the backend registry contract instead of inventing a parallel artifact model.

## References

- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @backend/api/artifact_registry.py
- @backend/api/files.py
- @context/features/48-generated-files-list-spec.md
- @context/features/54-files-workspace-spec.md

