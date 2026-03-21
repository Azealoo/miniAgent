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

## Implementation Notes

- V1 starts with a backend connector registry and typed action contract under `backend/connectors/` rather than direct external-system execution.
- Connector discovery is exposed through `/api/connectors/registry` and `/api/connectors/registry/{name}`, with config and validation flows under the same route family.
- Executable runtime actions are exposed through `/api/connectors/registry/{name}/actions/{import|export|sync_status}` with typed request/result envelopes and structured audit coverage.
- Initial built-in connector definitions cover the required transport families:
  - `eln_file_drop`
  - `lims_rest_bridge`
  - `instrument_webhook_ingest`
- Connector entries are disabled by default until explicitly configured, reflecting the project’s conservative safety posture for external integrations.
- Saved connector state is limited to enablement plus validated config values or secret references in `backend/config.json`; unknown config keys are rejected and response payloads expose config summaries instead of raw secret-bearing values.
- Every connector configure or validate action emits a structured `connector_action` audit event so connector activity is queryable alongside other operational records.
- V1 capability metadata explicitly records supported lifecycle actions, transport patterns, artifact domains, and mandatory guardrails for compliance, provenance, and artifact registration.
- Non-dry-run connector import/export execution now requires explicit proof artifacts for the declared guardrails: an allowed persisted `compliance_report` whose `run_id` matches the resolved connector-action run context, provenance artifact references for export, and successful artifact-registry refreshes that return valid records for all touched proof/source paths before side effects proceed.
- `eln_file_drop` can execute additive exports from persisted ELN artifacts while preserving canonical `artifacts/...` relative paths beneath the configured drop root, honoring `include_archive`, and blocking overwrite conflicts.
- `lims_rest_bridge` and `instrument_webhook_ingest` execute typed translation and validation previews for import/export or sync-status actions without introducing hidden connector-owned state; import previews resolve the run context from the validated payload when needed so compliance proofs cannot be reused across unrelated runs, and webhook import previews require an allowed event type, a delivery signature placeholder, and a configured shared-secret environment reference.
- Executable connector actions must stay inside the typed result and audit contract even when external reads or writes fail: file-drop export preflight read conflicts, copy failures, directory-creation errors, and sync-status read failures resolve to structured `execution_failure` or `partial_result` outcomes instead of uncaught 500s, preserving planned artifact/external path context, and connector audit records derive `run_id` from the request, validated payload preview, guardrail metadata, or persisted source artifacts so successful and failed connector actions remain queryable by run.

## References

- @backend/api/files.py
- @backend/api/skills_registry.py
- @backend/config.py
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/32-audit-logging-spec.md
- @context/features/34-eln-export-v1-spec.md
- SiLA 2 documentation
