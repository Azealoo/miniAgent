"""Shared backend DTO schemas consumed by ``scripts/codegen-types.ts``.

This module collects the pydantic models and TypedDicts whose shapes are
persisted, wire-serialized, or otherwise crossed over into the frontend. It
emits one JSON document mapping model name → JSON schema; ``scripts/codegen-types.ts``
reads that document (plus ``runtime/events.schema.json``) and writes
``frontend/src/lib/types.generated.ts``.

Two invariants keep backend/frontend in sync:

1. ``shared_types.schema.json`` is committed. ``tests/test_shared_types_schema.py``
   regenerates it from the pydantic models and fails the build on any drift.
2. ``frontend/src/lib/types.generated.ts`` is committed. The vitest drift-guard
   in ``frontend/src/lib/types.generated.test.ts`` re-runs the TypeScript
   codegen and fails if the checked-in file diverges from the snapshot.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from graph.session.session_schema import (
    SessionApprovalGateBlock,
    SessionPlanBlock,
    SessionRetrievalBlock,
    SessionTextBlock,
    SessionToolResultBlock,
    SessionToolUseBlock,
    SessionUsageBlock,
    SessionVerificationBlock,
)
from tools.contracts import (
    ToolArtifactRef,
    ToolResultEnvelope,
    ToolResultError,
)

SHARED_TYPES_SCHEMA_VERSION: int = 1

SCHEMA_SNAPSHOT_PATH = Path(__file__).with_name("shared_types.schema.json")


# Ordered mapping from generated TypeScript type name → Python source type.
# The ordering here is stable and mirrored in ``types.generated.ts`` so diffs
# stay readable when fields change.
_MODEL_SOURCES: tuple[tuple[str, Any], ...] = (
    # Tool contracts — backend/tools/contracts.py
    ("ToolArtifactRef", ToolArtifactRef),
    ("ToolResultError", ToolResultError),
    ("ToolResultEnvelope", ToolResultEnvelope),
    # Session content blocks — backend/graph/session/session_schema.py
    ("SessionTextBlock", SessionTextBlock),
    ("SessionToolUseBlock", SessionToolUseBlock),
    ("SessionToolResultBlock", SessionToolResultBlock),
    ("SessionRetrievalBlock", SessionRetrievalBlock),
    ("SessionUsageBlock", SessionUsageBlock),
    ("SessionPlanBlock", SessionPlanBlock),
    ("SessionVerificationBlock", SessionVerificationBlock),
    ("SessionApprovalGateBlock", SessionApprovalGateBlock),
)

# Composite types the codegen assembles on the TypeScript side from the
# individual blocks above. Listing them here keeps the manifest self-describing
# so the codegen script does not need to hard-code the list.
_COMPOSITE_TYPES: dict[str, dict[str, Any]] = {
    "SessionContentBlock": {
        "kind": "union",
        "members": [
            "SessionTextBlock",
            "SessionToolUseBlock",
            "SessionToolResultBlock",
            "SessionRetrievalBlock",
            "SessionUsageBlock",
            "SessionPlanBlock",
            "SessionVerificationBlock",
            "SessionApprovalGateBlock",
        ],
    },
}


def _schema_for(model: Any) -> dict[str, Any]:
    return TypeAdapter(model).json_schema(ref_template="#/$defs/{model}")


def generate_shared_types_schema() -> dict[str, Any]:
    """Return the manifest consumed by ``scripts/codegen-types.ts``.

    The output is deterministic: keys are sorted, schemas come straight from
    pydantic's TypeAdapter, and the composite section is a static manifest.
    """
    models: dict[str, Any] = {
        name: _schema_for(source) for name, source in _MODEL_SOURCES
    }
    return {
        "schema_version": SHARED_TYPES_SCHEMA_VERSION,
        "models": models,
        "composites": _COMPOSITE_TYPES,
    }


def write_snapshot(path: Path | None = None) -> Path:
    """Regenerate and overwrite the committed schema snapshot."""
    target = path or SCHEMA_SNAPSHOT_PATH
    target.write_text(
        json.dumps(generate_shared_types_schema(), indent=2, sort_keys=True) + "\n"
    )
    return target


if __name__ == "__main__":  # pragma: no cover - CLI convenience
    path = write_snapshot()
    print(f"wrote {path}")
