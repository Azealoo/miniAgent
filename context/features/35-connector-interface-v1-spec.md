# Connector Interface V1 Spec

## Overview

Define a thin, stable adapter surface for future ELN, LIMS, instrument, and external service integrations. The system should keep its internal truth in file-based artifacts and use connectors only as import/export or synchronization layers.

## Requirements

- Define the connector lifecycle:
  - configure
  - validate
  - import
  - export
  - sync status
- Keep connectors isolated from core workflow logic; they should translate to and from internal schemas, not redefine them.
- Support at least these transport patterns in design:
  - file drop
  - REST API
  - webhook callback
- Require every connector action to emit structured audit information.
- Define connector capability discovery so the orchestrator knows what each connector can do.
- Ensure connectors cannot bypass compliance, provenance, or artifact-registration rules.
- Make failure modes explicit and non-destructive.

## References

- @backend/api/files.py
- @backend/api/skills_registry.py
- @backend/config.py
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/32-audit-logging-spec.md
- @context/features/34-eln-export-v1-spec.md
- SiLA 2 documentation
