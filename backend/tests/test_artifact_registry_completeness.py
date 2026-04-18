"""Completeness audit for the BioAPEX artifact registry.

Walks every canonical artifact path under ``backend/artifacts/`` and asserts that
``ArtifactRegistry`` can build a valid record for each one. Used as a CI guard
so that writers cannot drop files under the canonical
``artifacts/<workflow>/<YYYY-MM-DD>/<run_id>/...`` prefix without a matching
registry entry.

Two failure modes are surfaced:

* **Orphans** — a canonical artifact file exists on disk but the registry
  machinery cannot produce a record for it. These must be registered (usually
  by running ``ArtifactRegistry(base_dir).rebuild()`` after the write) or the
  file must be removed / relocated outside the canonical prefix.
* **Invalid records** — the registry produced a record but marked it
  ``status == "invalid"``. Either fix the underlying artifact so it parses /
  matches its path, or delete it.

The scan reuses ``_scan_candidate_paths`` / ``build_record`` directly rather
than ``rebuild()`` so the test does not write ``storage/artifact_registry/
registry.json`` into the repo tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts.registry import ArtifactRegistry, ArtifactRegistryRecord  # noqa: E402

BACKEND_ROOT: Path = Path(__file__).parent.parent.resolve()


def _collect_records() -> tuple[list[str], list[ArtifactRegistryRecord]]:
    registry = ArtifactRegistry(BACKEND_ROOT)
    canonical_paths = sorted(set(registry._scan_candidate_paths()))
    records: list[ArtifactRegistryRecord] = []
    for relative in canonical_paths:
        record = registry.build_record(relative)
        if record is not None:
            records.append(record)
    return canonical_paths, records


def test_every_canonical_artifact_has_a_registry_record() -> None:
    canonical_paths, records = _collect_records()
    registered_paths = {record.path for record in records}
    missing = sorted(set(canonical_paths) - registered_paths)
    assert not missing, (
        "Canonical artifact files are missing from the registry; register them "
        "via ArtifactRegistry(base_dir).rebuild() or remove/relocate the files:\n  "
        + "\n  ".join(missing)
    )


def test_no_invalid_artifact_registry_records() -> None:
    _, records = _collect_records()
    invalid = [record for record in records if record.status == "invalid"]
    assert not invalid, (
        "Registry contains invalid artifact records; repair the artifact or "
        "remove it from the canonical layout:\n"
        + "\n".join(
            f"  {record.path}: {record.error or 'unspecified error'}"
            for record in invalid
        )
    )
