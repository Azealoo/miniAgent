"""Tests for the derived Study Dossier v1 summary route."""

import os
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import rebuild_artifact_registry  # noqa: E402
from artifacts.schemas import SCHEMA_PACK_VERSION  # noqa: E402
from graph.agent import agent_manager  # noqa: E402


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "examples"


def _request(
    path: str,
    *,
    method: str = "GET",
    host: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
            "client": (host, 12345),
        }
    )


@pytest.fixture
def isolated_api_state(tmp_path):
    original_base_dir = agent_manager.base_dir
    agent_manager.base_dir = tmp_path
    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _load_example_json(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def _load_example_yaml(name: str) -> dict:
    return yaml.safe_load((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def _run_timestamp(run_id: str) -> datetime:
    return datetime.strptime(run_id[4:20], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _artifact_dir(base_dir: Path, workflow: str, run_id: str) -> Path:
    return base_dir / "artifacts" / workflow / _run_timestamp(run_id).date().isoformat() / run_id


def _artifact_path(workflow: str, run_id: str, filename: str) -> str:
    return f"artifacts/{workflow}/{_run_timestamp(run_id).date().isoformat()}/{run_id}/{filename}"


def _eln_export_path(filename: str) -> str:
    return f"outputs/generated/eln-export/{filename}"


def _normalize_dataset_manifest(
    payload: dict,
    *,
    dataset_id: str,
    run_id: str,
    study_name: str,
    workflow_slug: str,
) -> dict:
    manifest = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    manifest["schema_version"] = SCHEMA_PACK_VERSION
    manifest["id"] = dataset_id
    manifest["run_id"] = run_id
    manifest["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    manifest["design"]["study_name"] = study_name
    manifest["related_artifacts"] = [
        {
            "artifact_type": "workflow_run",
            "path": _artifact_path(workflow_slug, run_id, "run.json"),
            "id": f"workflow-run-{dataset_id}",
            "run_id": run_id,
        }
    ]
    return manifest


def _normalize_workflow_run(payload: dict, *, dataset_id: str, run_id: str, workflow_slug: str, lifecycle_status: str) -> dict:
    run = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    run["id"] = f"workflow-run-{dataset_id}-{run_id[-8:]}"
    run["run_id"] = run_id
    run["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    run["workflow"]["slug"] = workflow_slug
    run["workflow"]["name"] = workflow_slug.replace("-", " ").title()
    run["lifecycle_status"] = lifecycle_status
    for deviation in run.get("deviations", []):
        if isinstance(deviation, dict):
            deviation["run_id"] = run_id
    run["related_artifacts"] = [
        {
            "artifact_type": "dataset_manifest",
            "path": _artifact_path(workflow_slug, run_id, "dataset_manifest.yaml"),
            "id": dataset_id,
            "run_id": run_id,
        }
    ]
    run["inputs"] = [
        {
            "artifact_type": "dataset_manifest",
            "path": _artifact_path(workflow_slug, run_id, "dataset_manifest.yaml"),
            "id": dataset_id,
            "run_id": run_id,
        }
    ]
    return run


def _normalize_evidence_review(payload: dict, *, dataset_id: str, run_id: str, review_status: str) -> dict:
    review = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    review["id"] = f"evidence-review-{dataset_id}"
    review["run_id"] = run_id
    review["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    review["source_workflow"] = "study-alpha"
    review["review_status"] = review_status
    review["related_artifacts"] = [
        {
            "artifact_type": "dataset_manifest",
            "path": _artifact_path("study-alpha", run_id, "dataset_manifest.yaml"),
            "id": dataset_id,
            "run_id": run_id,
        }
    ]
    review["evidence_included"] = review["evidence_included"][:1]
    review["source_facts"] = review["source_facts"][:1]
    review["synthesized_conclusions"] = review["synthesized_conclusions"][:1]
    return review


def _normalize_compliance_report(payload: dict, *, dataset_id: str, run_id: str) -> dict:
    report = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    report["id"] = f"compliance-{dataset_id}"
    report["run_id"] = run_id
    report["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    report["source_workflow"] = "study-alpha"
    report["runtime_state"] = "approved_override"
    report["decision_source"] = "human_override"
    report["preflight_disposition"] = "require_approval"
    report["block_status"] = "not_blocked"
    report["human_approval_required"] = True
    report["approval_scope"] = "message"
    report["approval"] = {
        "approved_by": "reviewer@example.org",
        "approval_scope": "message",
        "approved_at": "2026-03-19T10:31:00Z",
        "override_for_disposition": "allow",
        "rationale": "Approve this study for the summary view test.",
    }
    report["final_disposition"] = "allow"
    report["related_artifacts"] = [
        {
            "artifact_type": "workflow_run",
            "path": _artifact_path("study-alpha", run_id, "run.json"),
            "id": f"workflow-run-{dataset_id}",
            "run_id": run_id,
        }
    ]
    return report


def _normalize_qa_report(payload: dict, *, dataset_id: str, run_id: str, overall_status: str) -> dict:
    report = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    report["id"] = f"qa-{dataset_id}"
    report["run_id"] = run_id
    report["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    report["source_workflow"] = "study-alpha"
    report["overall_status"] = overall_status
    report["related_artifacts"] = [
        {
            "artifact_type": "workflow_run",
            "path": _artifact_path("study-alpha", run_id, "run.json"),
            "id": f"workflow-run-{dataset_id}",
            "run_id": run_id,
        }
    ]
    return report


def _normalize_checklist_results(payload: dict, *, dataset_id: str, run_id: str, overall_status: str) -> dict:
    results = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    results["id"] = f"checklist-{dataset_id}"
    results["run_id"] = run_id
    results["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    results["source_workflow"] = "study-beta"
    results["overall_status"] = overall_status
    if overall_status == "not_applicable":
        results["evaluations"] = []
        results["summary"] = {
            "evaluated_checklist_count": 0,
            "passed_checklist_count": 0,
            "warning_checklist_count": 0,
            "blocked_checklist_count": 0,
            "not_applicable_checklist_count": 0,
            "failed_required_item_count": 0,
            "failed_best_practice_item_count": 0,
        }
    results["evaluated_artifacts"] = [
        {
            "artifact_type": "dataset_manifest",
            "path": _artifact_path("study-beta", run_id, "dataset_manifest.yaml"),
            "id": dataset_id,
            "run_id": run_id,
        }
    ]
    results["related_artifacts"] = [
        {
            "artifact_type": "workflow_run",
            "path": _artifact_path("study-beta", run_id, "run.json"),
            "id": f"workflow-run-{dataset_id}",
            "run_id": run_id,
        }
    ]
    return results


def _normalize_provenance(payload: dict, *, dataset_id: str, run_id: str) -> dict:
    prov = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    prov["id"] = f"provenance-{dataset_id}"
    prov["run_id"] = run_id
    prov["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    prov["source_workflow"] = "study-alpha"
    prov["related_artifacts"] = [
        {
            "artifact_type": "workflow_run",
            "path": _artifact_path("study-alpha", run_id, "run.json"),
            "id": f"workflow-run-{dataset_id}",
            "run_id": run_id,
        }
    ]
    return prov


def _normalize_biocompute(payload: dict, *, dataset_id: str, run_id: str) -> dict:
    doc = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    doc["id"] = f"biocompute-{dataset_id}"
    doc["run_id"] = run_id
    doc["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    doc["source_workflow"] = "study-alpha"
    for ref in doc.get("related_artifacts", []):
        if isinstance(ref, dict) and ref.get("artifact_type") == "dataset_manifest":
            ref["id"] = dataset_id
            ref["path"] = _artifact_path("study-alpha", run_id, "dataset_manifest.yaml")
    return doc


def _normalize_eln_export(payload: dict, *, dataset_id: str, run_id: str) -> dict:
    doc = deepcopy(payload)
    run_timestamp = _run_timestamp(run_id)
    doc["id"] = f"eln-export-{dataset_id}"
    doc["run_id"] = run_id
    doc["created_at"] = run_timestamp.isoformat().replace("+00:00", "Z")
    doc["source_workflow"] = "study-alpha"
    doc["workflow_run"]["path"] = _artifact_path("study-alpha", run_id, "run.json")
    doc["workflow_run"]["id"] = f"workflow-run-{dataset_id}"
    doc["workflow_run"]["run_id"] = run_id
    doc["dataset_manifest"]["path"] = _artifact_path("study-alpha", run_id, "dataset_manifest.yaml")
    doc["dataset_manifest"]["id"] = dataset_id
    for ref in doc.get("related_artifacts", []):
        if isinstance(ref, dict) and ref.get("artifact_type") == "dataset_manifest":
            ref["path"] = _artifact_path("study-alpha", run_id, "dataset_manifest.yaml")
            ref["id"] = dataset_id
            ref["run_id"] = run_id
        if isinstance(ref, dict) and ref.get("artifact_type") == "workflow_run":
            ref["path"] = _artifact_path("study-alpha", run_id, "run.json")
            ref["id"] = f"workflow-run-{dataset_id}"
            ref["run_id"] = run_id
    for ref in doc.get("provenance_exports", []):
        if isinstance(ref, dict) and ref.get("artifact_type") == "provenance":
            ref["path"] = _artifact_path("study-alpha", run_id, "prov.json")
            ref["run_id"] = run_id
    for ref in doc.get("biocompute_exports", []):
        if isinstance(ref, dict) and ref.get("artifact_type") == "biocompute":
            ref["path"] = _artifact_path("study-alpha", run_id, "biocompute.json")
            ref["run_id"] = run_id
    return doc


def _write_study_run(
    base_dir: Path,
    *,
    workflow_slug: str,
    run_id: str,
    dataset_id: str,
    study_name: str,
    lifecycle_status: str,
    include_full_outputs: bool,
    qa_status: str | None = None,
    checklist_status: str | None = None,
) -> None:
    run_dir = _artifact_dir(base_dir, workflow_slug, run_id)
    timestamp = _run_timestamp(run_id)

    manifest = _normalize_dataset_manifest(
        _load_example_yaml("dataset_manifest.yaml"),
        dataset_id=dataset_id,
        run_id=run_id,
        study_name=study_name,
        workflow_slug=workflow_slug,
    )
    manifest["source_workflow"] = workflow_slug
    _write_yaml(run_dir / "dataset_manifest.yaml", manifest)

    workflow_run = _normalize_workflow_run(
        _load_example_json("run.json"),
        dataset_id=dataset_id,
        run_id=run_id,
        workflow_slug=workflow_slug,
        lifecycle_status=lifecycle_status,
    )
    workflow_run["created_at"] = timestamp.isoformat().replace("+00:00", "Z")
    workflow_run["source_workflow"] = workflow_slug
    _write_json(run_dir / "run.json", workflow_run)

    if include_full_outputs:
        evidence_review = _normalize_evidence_review(
            _load_example_json("evidence_review.json"),
            dataset_id=dataset_id,
            run_id=run_id,
            review_status="supported",
        )
        compliance_report = _normalize_compliance_report(
            _load_example_json("compliance_report.json"),
            dataset_id=dataset_id,
            run_id=run_id,
        )
        qa_report = _normalize_qa_report(
            _load_example_json("qa_report.json"),
            dataset_id=dataset_id,
            run_id=run_id,
            overall_status=qa_status or "warning",
        )
        _write_json(run_dir / "evidence_review.json", evidence_review)
        _write_json(run_dir / "compliance_report.json", compliance_report)
        _write_json(run_dir / "qa_report.json", qa_report)

        provenance = _normalize_provenance(_load_example_json("prov.json"), dataset_id=dataset_id, run_id=run_id)
        biocompute = _normalize_biocompute(_load_example_json("biocompute.json"), dataset_id=dataset_id, run_id=run_id)
        eln_export = _normalize_eln_export(_load_example_json("eln_export.json"), dataset_id=dataset_id, run_id=run_id)
        _write_json(run_dir / "prov.json", provenance)
        _write_json(run_dir / "biocompute.json", biocompute)
        eln_export_dir = run_dir / "outputs" / "generated" / "eln-export"
        _write_json(eln_export_dir / "eln_export.json", eln_export)
        (eln_export_dir / "eln_export_bundle.tar.gz").write_bytes(b"bundle")
    elif checklist_status is not None:
        checklist_results = _normalize_checklist_results(
            _load_example_json("checklist_results.json"),
            dataset_id=dataset_id,
            run_id=run_id,
            overall_status=checklist_status,
        )
        _write_json(run_dir / "checklist_results.json", checklist_results)


class TestStudiesApi:
    def test_app_includes_studies_route(self):
        import app

        assert any(route.path == "/api/studies" for route in app.app.routes)
        assert not any(route.path == "/api/studies/{study_id}" for route in app.app.routes)

    def test_list_studies_derives_summaries_from_artifacts(self, isolated_api_state):
        _write_study_run(
            isolated_api_state,
            workflow_slug="study-alpha",
            run_id="run-20260318T193000Z-a1b2c3d4",
            dataset_id="ds-alpha-study-v1",
            study_name="Alpha Study",
            lifecycle_status="completed",
            include_full_outputs=False,
        )
        _write_study_run(
            isolated_api_state,
            workflow_slug="study-alpha",
            run_id="run-20260319T104500Z-a1b2c3d5",
            dataset_id="ds-alpha-study-v1",
            study_name="Alpha Study Updated",
            lifecycle_status="blocked",
            include_full_outputs=True,
            qa_status="warning",
        )
        _write_study_run(
            isolated_api_state,
            workflow_slug="study-beta",
            run_id="run-20260318T091500Z-b1b2c3d4",
            dataset_id="ds-beta-study-v1",
            study_name="Beta Study",
            lifecycle_status="completed",
            include_full_outputs=False,
            checklist_status="not_applicable",
        )

        rebuild_artifact_registry(isolated_api_state)

        from api.studies import list_studies

        response = list_studies(request=_request("/api/studies"))

        assert response["items"][0]["study_id"] == "ds-alpha-study-v1"
        assert response["items"][0]["title"] == "Alpha Study Updated"
        assert response["items"][0]["run_count"] == 2
        assert response["items"][0]["active_run_state"] == "blocked"
        assert response["items"][0]["evidence_state"] == "supported"
        assert response["items"][0]["compliance_state"] == "approved_override"
        assert response["items"][0]["qa_state"] == "warning"
        assert response["items"][0]["export_available"] is True
        assert response["items"][0]["artifact_counts"] == {
            "dataset_manifests": 2,
            "workflow_runs": 2,
            "evidence_reviews": 1,
            "claim_graphs": 0,
            "compliance_reports": 1,
            "qa_reports": 1,
            "checklist_results": 0,
            "exports": 4,
        }

        assert response["items"][1]["study_id"] == "ds-beta-study-v1"
        assert response["items"][1]["qa_state"] == "not_started"
        assert response["items"][1]["export_available"] is False
        assert response["items"][1]["artifact_counts"]["checklist_results"] == 1

    def test_list_studies_blocks_non_local_clients_without_inspection_token(self, isolated_api_state):
        _write_study_run(
            isolated_api_state,
            workflow_slug="study-alpha",
            run_id="run-20260318T193000Z-a1b2c3d4",
            dataset_id="ds-alpha-study-v1",
            study_name="Alpha Study",
            lifecycle_status="completed",
            include_full_outputs=False,
        )

        from api.studies import list_studies

        with pytest.raises(HTTPException) as exc_info:
            list_studies(request=_request("/api/studies", host="10.0.0.8"))

        assert exc_info.value.status_code == 403

    def test_list_studies_allows_non_local_clients_with_inspection_token(self, isolated_api_state):
        _write_study_run(
            isolated_api_state,
            workflow_slug="study-alpha",
            run_id="run-20260318T193000Z-a1b2c3d4",
            dataset_id="ds-alpha-study-v1",
            study_name="Alpha Study",
            lifecycle_status="completed",
            include_full_outputs=False,
        )

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "inspection_bearer_token_env_var": "BIOAPEX_INSPECTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer inspection-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_INSPECTION_TOKEN": "inspection-token"},
            clear=False,
        ):
            from api.studies import list_studies

            response = list_studies(request=_request("/api/studies", host="10.0.0.8", headers=headers))

        assert response["items"][0]["study_id"] == "ds-alpha-study-v1"
