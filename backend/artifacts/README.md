# Artifact Naming Standard

This directory defines the canonical layout for durable BioAPEX artifacts.

## Canonical Run ID

- Format: `run-YYYYMMDDTHHMMSSZ-xxxxxxxx`
- Timestamp is UTC to the second.
- The trailing suffix is 8 lowercase hex characters.
- Reruns always get a fresh `run_id`, even when inputs are identical.

## Canonical Run Directory

Every execution-oriented artifact lives under:

`artifacts/<workflow>/<YYYY-MM-DD>/<run_id>/`

`<workflow>` is a lowercase slug derived from the workflow or tool name.

## Required Run Layout

Each run directory reserves these top-level locations:

- `run.json`: required machine-readable root run record, created when the run directory is prepared
- `content_hashes.json`: per-artifact SHA-256 digests keyed by relative path, initialized alongside `run.json`
- `inputs/user/`: user-supplied files copied or linked into the run
- `outputs/generated/`: generated files that do not use a stable root filename
- `dataset_manifest.yaml`
- `workflow_plan.json`
- `compliance_report.json`
- `evidence_card.yaml`
- `protocol_run.yaml`
- `qa_report.json`
- `prov.json`
- `biocompute.json`
- `ro-crate/`

## User-Supplied vs Generated Files

- User-supplied files live under `inputs/user/` and use the pattern
  `inputs/user/<slot>__<sanitized-filename>` when a slot is known, or
  `inputs/user/user__<sanitized-filename>` otherwise.
- Generated files that are not one of the stable root artifacts live under
  `outputs/generated/` or `outputs/generated/<step>/`.
- Stable artifact classes keep their reserved top-level names so later code can
  locate them without guessing.

## Metadata Header

Every artifact should expose, at minimum:

- `schema_version`
- `artifact_type`
- `run_id`
- `created_at`
- `source_workflow` or `source_tool`

The helper functions in `naming.py` build this header for JSON or YAML records.

## Collision Rules

- New runs must create a new run directory rather than reusing an existing one.
- Writes inside a run must fail fast if the target path already exists; use the `RunLayout` path helpers to reserve artifact locations before writing.
- Artifact paths must stay relative to the project root, or to another caller-
  provided allowed root that is validated before use.

## API Compatibility

- `/api/files` may read under `artifacts/` so durable artifacts remain
  inspectable through the existing file browser.
- `/api/files` does not allow writes under `artifacts/`; artifact creation
  should happen through workflow code, not manual editor overwrites.
