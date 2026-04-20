"""Tests for HMAC signing of artifact provenance records."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts.naming import prepare_run_directory
from artifacts.provenance import (
    ProvenanceSignatureError,
    SIGNATURE_ALGORITHM,
    materialize_provenance_bundle,
    sign_provenance_payload,
    verify_provenance_bundle,
)
from artifacts.schemas import WorkflowRun, load_artifact_document


EXAMPLES_DIR = Path(__file__).parent.parent / "artifacts" / "examples"
HMAC_KEY = "unit-test-hmac-key"


def _make_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "provenance",
        "id": "provenance-demo",
        "run_id": "run-20260318T193000Z-deadbeef",
        "created_at": "2026-03-18T19:37:00Z",
        "source_workflow": "demo-workflow",
        "related_artifacts": [],
        "workflow": {"name": "Demo Workflow", "slug": "demo-workflow"},
        "used": [],
    }


def test_sign_provenance_payload_embeds_canonical_hmac(monkeypatch):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)

    payload_a = _make_payload()
    payload_b = _make_payload()
    # Insert keys in a different order to prove canonical serialization is
    # order-independent.
    reordered = {key: payload_b.pop(key) for key in reversed(list(payload_b))}

    sign_provenance_payload(payload_a)
    sign_provenance_payload(reordered)

    assert payload_a["signature"]["algorithm"] == SIGNATURE_ALGORITHM
    assert len(payload_a["signature"]["digest"]) == 64
    assert payload_a["signature"] == reordered["signature"]


def test_sign_provenance_payload_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("BIOAPEX_PROVENANCE_HMAC_KEY", raising=False)

    with pytest.raises(ProvenanceSignatureError, match="not configured"):
        sign_provenance_payload(_make_payload())


def test_verify_provenance_bundle_happy_path(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)
    payload = _make_payload()
    sign_provenance_payload(payload)

    path = tmp_path / "prov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    verified = verify_provenance_bundle(path)
    assert verified["signature"]["algorithm"] == SIGNATURE_ALGORITHM


def test_verify_provenance_bundle_rejects_tampered_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)
    payload = _make_payload()
    sign_provenance_payload(payload)
    # Tamper with a non-signature field after signing.
    payload["workflow"]["name"] = "Tampered Workflow"

    path = tmp_path / "prov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProvenanceSignatureError, match="mismatch"):
        verify_provenance_bundle(path)


def test_verify_provenance_bundle_rejects_missing_signature(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)
    payload = _make_payload()

    path = tmp_path / "prov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProvenanceSignatureError, match="missing a signature"):
        verify_provenance_bundle(path)


def test_verify_provenance_bundle_rejects_wrong_key(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)
    payload = _make_payload()
    sign_provenance_payload(payload)

    path = tmp_path / "prov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", "different-key")
    with pytest.raises(ProvenanceSignatureError, match="mismatch"):
        verify_provenance_bundle(path)


def test_verify_provenance_bundle_requires_configured_key(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)
    payload = _make_payload()
    sign_provenance_payload(payload)

    path = tmp_path / "prov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.delenv("BIOAPEX_PROVENANCE_HMAC_KEY", raising=False)
    with pytest.raises(ProvenanceSignatureError, match="not configured"):
        verify_provenance_bundle(path)


def test_materialize_provenance_bundle_signs_and_links_ro_crate(monkeypatch, tmp_path):
    monkeypatch.setenv("BIOAPEX_PROVENANCE_HMAC_KEY", HMAC_KEY)

    run_document = load_artifact_document(EXAMPLES_DIR / "run.json")
    assert isinstance(run_document, WorkflowRun)

    layout = prepare_run_directory(
        tmp_path,
        run_document.workflow.name,
        created_at=run_document.created_at,
        run_id=run_document.run_id,
    )

    export_paths = materialize_provenance_bundle(
        base_dir=tmp_path,
        layout=layout,
        run_document=run_document,
        workflow_version="1.0.0",
    )

    provenance_path = tmp_path / export_paths[0]
    ro_crate_path = tmp_path / export_paths[1]

    prov_payload = verify_provenance_bundle(provenance_path)
    assert prov_payload["signature"]["algorithm"] == SIGNATURE_ALGORITHM

    ro_crate_payload = json.loads(ro_crate_path.read_text(encoding="utf-8"))
    prov_entries = [
        entry for entry in ro_crate_payload["@graph"] if entry.get("@id") == "../prov.json"
    ]
    assert prov_entries, "RO-Crate metadata must reference prov.json"
    prov_entry = prov_entries[0]
    assert prov_entry["signatureAlgorithm"] == SIGNATURE_ALGORITHM
    assert prov_entry["signatureDigest"] == prov_payload["signature"]["digest"]


def test_materialize_provenance_bundle_refuses_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("BIOAPEX_PROVENANCE_HMAC_KEY", raising=False)

    run_document = load_artifact_document(EXAMPLES_DIR / "run.json")
    assert isinstance(run_document, WorkflowRun)

    layout = prepare_run_directory(
        tmp_path,
        run_document.workflow.name,
        created_at=run_document.created_at,
        run_id=run_document.run_id,
    )

    with pytest.raises(ProvenanceSignatureError, match="not configured"):
        materialize_provenance_bundle(
            base_dir=tmp_path,
            layout=layout,
            run_document=run_document,
            workflow_version="1.0.0",
        )
