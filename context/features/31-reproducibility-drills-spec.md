# Reproducibility Drills Spec

## Overview

Turn reproducibility into a testable product requirement. This phase should add drills that recreate runs from artifacts alone and compare outcomes against expected tolerances. The point is not philosophical reproducibility messaging. The point is operational proof.

## Requirements

- Define at least one drill for a workflow run that is rerun from stored manifests, parameters, and environment references.
- Define pass criteria for deterministic outputs versus outputs allowed within tolerance.
- Add a provenance completeness check that fails when required lineage fields are missing.
- Add a report bundle completeness check and a compliance artifact presence check.
- Decide which drills run in normal CI and which are scheduled or manual because of compute cost.
- Make drill outputs themselves first-class artifacts or test reports.
- Ensure drills can run without interactive chat state.

## References

- @backend/tests/test_api_health.py
- @backend/tests/test_config.py
- @backend/tests/test_session_manager.py
- @backend/tests/test_tools.py
- @backend/pytest.ini
- @context/features/18-report-bundle-v1-spec.md
- @context/features/19-provenance-export-v1-spec.md
- @context/features/30-external-workflow-adapter-v1-spec.md
