"""Drift-guard for the shared backend → frontend DTO schema snapshot.

Mirrors the pattern in ``test_runtime_events.py``. If this test fails, either:

1. Regenerate the snapshot and the frontend types.generated.ts:
       python -m codegen.shared_types
       (cd ../frontend && npm run codegen:types)
   then re-run ``pytest backend/tests/test_shared_types_schema.py`` and
   ``cd frontend && npm test`` — both must pass before the change lands.

2. Revert the model change if the drift is unintentional.
"""
from __future__ import annotations

import json

from codegen.shared_types import (
    SCHEMA_SNAPSHOT_PATH,
    SHARED_TYPES_SCHEMA_VERSION,
    generate_shared_types_schema,
)


def test_shared_types_schema_snapshot_matches_pydantic_models() -> None:
    """Fail the build if the committed JSON snapshot drifts from the pydantic models."""
    committed = json.loads(SCHEMA_SNAPSHOT_PATH.read_text())
    current = generate_shared_types_schema()
    assert current == committed, (
        "backend/codegen/shared_types.schema.json is out of date with the "
        "pydantic models — regenerate it with `python -m codegen.shared_types` "
        "and re-run `npm run codegen:types` in the frontend."
    )


def test_shared_types_snapshot_includes_expected_models() -> None:
    committed = json.loads(SCHEMA_SNAPSHOT_PATH.read_text())
    models = committed["models"]
    expected = {
        "ToolArtifactRef",
        "ToolResultError",
        "ToolResultEnvelope",
        "SessionTextBlock",
        "SessionToolUseBlock",
        "SessionToolResultBlock",
        "SessionRetrievalBlock",
        "SessionUsageBlock",
        "SessionPlanBlock",
        "SessionVerificationBlock",
    }
    assert expected.issubset(models.keys())


def test_shared_types_snapshot_declares_schema_version() -> None:
    committed = json.loads(SCHEMA_SNAPSHOT_PATH.read_text())
    assert committed["schema_version"] == SHARED_TYPES_SCHEMA_VERSION


def test_shared_types_composite_union_lists_all_session_blocks() -> None:
    committed = json.loads(SCHEMA_SNAPSHOT_PATH.read_text())
    members = committed["composites"]["SessionContentBlock"]["members"]
    for model in (
        "SessionTextBlock",
        "SessionToolUseBlock",
        "SessionToolResultBlock",
        "SessionRetrievalBlock",
        "SessionUsageBlock",
        "SessionPlanBlock",
        "SessionVerificationBlock",
    ):
        assert model in members
        assert model in committed["models"]
