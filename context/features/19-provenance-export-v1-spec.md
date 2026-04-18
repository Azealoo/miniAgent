# Provenance Export V1 Spec

## Overview

Export workflow provenance in a portable format that can survive outside the chat UI and local project conventions. This phase should package the key lineage information for runs so others can inspect how outputs were produced, by whom, from what inputs, and with which tools and parameters.

## Requirements

- Emit a provenance bundle for each completed workflow run.
- Use RO-Crate as the primary package format for run bundles unless a later phase requires an alternative.
- Include PROV-compatible lineage information for:
  - entities
  - activities
  - agents
- Ensure the bundle references, at minimum:
  - input artifacts and hashes
  - output artifacts and hashes
  - workflow and step identifiers
  - tool versions
  - environment references
  - timestamps
- Make sure the exported provenance can be generated from files alone, not hidden runtime state.
- Define how partial or failed runs are represented in provenance exports.
- Add validation or smoke tests that ensure required provenance fields are present.

## References

- @context/features/02-artifact-naming-standard-spec.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/18-report-bundle-v1-spec.md
- Official RO-Crate specification
- Official W3C PROV data model
