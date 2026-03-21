import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _example_json(filename: str) -> dict:
    examples_dir = Path(__file__).parent.parent / "artifacts" / "examples"
    return json.loads((examples_dir / filename).read_text(encoding="utf-8"))


def _qa_report_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "artifact_type": "qa_report",
        "id": "qa-connector-import-20260320",
        "run_id": "run-20260320T190000Z-deadbeef",
        "created_at": "2026-03-20T19:00:00Z",
        "source_workflow": "qa-review",
        "related_artifacts": [],
        "overall_status": "passed",
        "failed_checks": [],
        "warnings": [],
        "missing_artifacts": [],
        "recommended_remediation": [],
        "checklist_artifacts": [],
    }


def _allowed_compliance_report_payload(run_id: str = "run-20260318T193000Z-deadbeef") -> dict:
    payload = _example_json("compliance_report.json")
    payload.update(
        {
            "id": f"compliance-connector-{run_id.lower()}",
            "run_id": run_id,
            "risk_category": "none",
            "triggered_rules": [],
            "runtime_state": "allowed",
            "preflight_disposition": "allow",
            "block_status": "not_blocked",
            "human_approval_required": False,
            "approval_scope": None,
            "approval": None,
            "final_disposition": "allow",
        }
    )
    return payload


def _provenance_payload(run_id: str = "run-20260318T193000Z-deadbeef") -> dict:
    payload = _example_json("prov.json")
    payload.update(
        {
            "id": f"provenance-demo-{run_id.lower()}",
            "run_id": run_id,
        }
    )
    return payload


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
def isolated_connector_state(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)

    for relpath in ("workspace", "memory", "skills", "knowledge", "artifacts"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager


def test_connector_registry_lists_builtin_connectors_with_safe_defaults(isolated_connector_state):
    from api.connectors import list_connector_registry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        response = list_connector_registry()

    connectors = {item["name"]: item for item in response["connectors"]}
    assert set(connectors) == {"eln_file_drop", "instrument_webhook_ingest", "lims_rest_bridge"}
    assert connectors["eln_file_drop"]["enabled"] is False
    assert connectors["eln_file_drop"]["capabilities"]["transport_patterns"] == ["file_drop"]
    assert connectors["eln_file_drop"]["config_summary"]["missing_required_fields"] == ["outgoing_dir"]
    assert connectors["lims_rest_bridge"]["capabilities"]["transport_patterns"] == ["rest_api"]
    assert connectors["instrument_webhook_ingest"]["capabilities"]["transport_patterns"] == ["webhook_callback"]


def test_connector_registry_reads_block_non_local_clients_without_inspection_token(isolated_connector_state):
    from api.connectors import get_connector_registry_detail, list_connector_registry

    with pytest.raises(HTTPException) as exc_info:
        list_connector_registry(_request("/api/connectors/registry", host="10.0.0.8"))
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        get_connector_registry_detail(
            "eln_file_drop",
            _request("/api/connectors/registry/eln_file_drop", host="10.0.0.8"),
        )
    assert exc_info.value.status_code == 403


def test_connector_registry_reads_allow_non_local_clients_with_inspection_token(isolated_connector_state):
    from api.connectors import get_connector_registry_detail, list_connector_registry

    config_path = isolated_connector_state / "config.json"
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
        listing = list_connector_registry(_request("/api/connectors/registry", host="10.0.0.8", headers=headers))
        detail = get_connector_registry_detail(
            "eln_file_drop",
            _request("/api/connectors/registry/eln_file_drop", host="10.0.0.8", headers=headers),
        )

    assert any(item["name"] == "eln_file_drop" for item in listing["connectors"])
    assert detail["name"] == "eln_file_drop"


def test_malformed_persisted_connector_config_fails_closed(isolated_connector_state):
    from api.connectors import list_connector_registry

    config_path = isolated_connector_state / "config.json"
    config_path.write_text(json.dumps({"connectors": "oops"}), encoding="utf-8")

    with patch("config._CONFIG_FILE", config_path):
        response = list_connector_registry()

    connectors = {item["name"]: item for item in response["connectors"]}
    assert connectors["eln_file_drop"]["enabled"] is False


def test_connector_configuration_can_be_disabled_by_policy(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, update_connector_registry_entry
    from audit.store import query_audit_events

    config_path = isolated_connector_state / "config.json"
    config_path.write_text(
        json.dumps({"production_hardening": {"api": {"connectors_configuration_enabled": False}}}),
        encoding="utf-8",
    )

    with patch("config._CONFIG_FILE", config_path), pytest.raises(HTTPException) as exc_info:
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(enabled=True, config={"outgoing_dir": "workspace/drop"}),
        )

    assert exc_info.value.status_code == 403
    events = query_audit_events(isolated_connector_state, event_type="connector_action")
    assert any(
        event.connector_name == "eln_file_drop"
        and event.outcome == "blocked"
        and event.details.get("failure_mode") == "policy_disabled"
        for event in events
    )


def test_connector_runtime_actions_can_be_disabled_by_policy(isolated_connector_state):
    from api.connectors import run_connector_registry_action
    from audit.store import query_audit_events

    config_path = isolated_connector_state / "config.json"
    config_path.write_text(
        json.dumps({"production_hardening": {"api": {"connectors_runtime_actions_enabled": False}}}),
        encoding="utf-8",
    )

    with patch("config._CONFIG_FILE", config_path), pytest.raises(HTTPException) as exc_info:
        run_connector_registry_action("eln_file_drop", "export")

    assert exc_info.value.status_code == 403
    events = query_audit_events(isolated_connector_state, event_type="connector_action")
    assert any(
        event.connector_name == "eln_file_drop"
        and event.outcome == "blocked"
        and event.details.get("failure_mode") == "policy_disabled"
        for event in events
    )


def test_connector_mutation_routes_block_non_local_clients_without_admin_token(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry

    with pytest.raises(HTTPException) as exc_info:
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(enabled=True, config={"outgoing_dir": "workspace/drop"}),
            _request("/api/connectors/registry/eln_file_drop", method="PUT", host="10.0.0.8"),
        )
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        run_connector_registry_action(
            "eln_file_drop",
            "export",
            request=_request(
                "/api/connectors/registry/eln_file_drop/actions/export",
                method="POST",
                host="10.0.0.8",
            ),
        )
    assert exc_info.value.status_code == 403


def test_connector_mutation_routes_allow_non_local_clients_with_admin_token(isolated_connector_state):
    from api.connectors import ConnectorActionRequest, ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry

    config_path = isolated_connector_state / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "production_hardening": {
                    "api": {
                        "allow_loopback_without_auth": False,
                        "admin_bearer_token_env_var": "BIOAPEX_ADMIN_TOKEN",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    headers = [(b"authorization", b"Bearer admin-token")]

    with patch("config._CONFIG_FILE", config_path), patch.dict(
        os.environ,
        {"BIOAPEX_ADMIN_TOKEN": "admin-token"},
        clear=False,
    ):
        configure_response = update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(enabled=True, config={"outgoing_dir": "workspace/drop"}),
            _request("/api/connectors/registry/eln_file_drop", method="PUT", host="10.0.0.8", headers=headers),
        )
        action_response = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(),
            _request(
                "/api/connectors/registry/eln_file_drop/actions/export",
                method="POST",
                host="10.0.0.8",
                headers=headers,
            ),
        )

    assert configure_response["result"]["outcome"] == "success"
    assert action_response["outcome"] in {"invalid_input", "execution_failure", "blocked"}


def test_connector_admin_routes_do_not_fall_back_to_execution_token(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, update_connector_registry_entry

    config_path = isolated_connector_state / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "production_hardening": {
                    "api": {
                        "allow_loopback_without_auth": False,
                        "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    headers = [(b"authorization", b"Bearer execution-token")]

    with patch("config._CONFIG_FILE", config_path), patch.dict(
        os.environ,
        {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
        clear=False,
    ), pytest.raises(HTTPException) as exc_info:
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(enabled=True, config={"outgoing_dir": "workspace/drop"}),
            _request("/api/connectors/registry/eln_file_drop", method="PUT", host="10.0.0.8", headers=headers),
        )

    assert exc_info.value.status_code == 403


def test_connector_config_defaults_do_not_leak_between_config_files(isolated_connector_state):
    from config import get_connector_entry, set_connector_entry

    primary_config = isolated_connector_state / "primary-config.json"
    secondary_config = isolated_connector_state / "secondary-config.json"

    with patch("config._CONFIG_FILE", primary_config):
        set_connector_entry("eln_file_drop", enabled=True, config={"outgoing_dir": "exports/eln"})
        assert get_connector_entry("eln_file_drop")["enabled"] is True

    with patch("config._CONFIG_FILE", secondary_config):
        assert get_connector_entry("eln_file_drop") == {"enabled": False, "config": {}}


def test_configure_connector_persists_enabled_state_and_uses_safe_summary(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, get_connector_registry_detail, update_connector_registry_entry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        response = update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "outgoing_dir": "exports/eln",
                    "include_archive": True,
                },
            ),
        )
        detail = get_connector_registry_detail("eln_file_drop")

    assert response["result"]["outcome"] == "success"
    assert response["connector"]["enabled"] is True
    assert "config" not in response["connector"]
    assert detail["config_summary"]["configured_fields"] == ["outgoing_dir", "include_archive"]
    assert detail["config_summary"]["uses_secret_references"] is False


def test_invalid_configure_reports_attempted_config_summary(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, update_connector_registry_entry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "outgoing_dir": "exports/eln",
                    "include_archive": True,
                },
            ),
        )
        with pytest.raises(HTTPException) as exc_info:
            update_connector_registry_entry(
                "eln_file_drop",
                ConnectorEntryUpdate(
                    enabled=True,
                    config={"include_archive": True},
                ),
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["config_summary"]["configured_fields"] == ["include_archive"]
    assert exc_info.value.detail["config_summary"]["missing_required_fields"] == ["outgoing_dir"]
    assert exc_info.value.detail["issues"][0]["field"] == "outgoing_dir"


def test_validate_connector_returns_invalid_result_and_audit_query_supports_connector_name(
    isolated_connector_state,
):
    from api.audit import list_audit_events
    from api.connectors import ConnectorValidationRequest, validate_connector_registry_entry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        result = validate_connector_registry_entry(
            "lims_rest_bridge",
            ConnectorValidationRequest(
                config={
                    "base_url": "ftp://lims.example.org",
                    "project_slug": "study-42",
                    "auth_strategy": "token_env",
                }
            ),
        )
        audit_response = list_audit_events(
            event_type="connector_action",
            connector_name="lims_rest_bridge",
            limit=10,
        )

    assert result["outcome"] == "invalid_input"
    assert result["failure_mode"] == "invalid_configuration"
    assert {issue["field"] for issue in result["issues"]} == {"base_url", "credential_env_var"}
    assert len(audit_response["events"]) == 1
    event = audit_response["events"][0]
    assert event["connector_name"] == "lims_rest_bridge"
    assert event["details"]["action"] == "validate"
    assert event["outcome"] == "invalid_input"


def test_update_connector_route_rejects_unknown_config_fields(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, get_connector_registry_detail, update_connector_registry_entry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        with pytest.raises(HTTPException) as exc_info:
            update_connector_registry_entry(
                "eln_file_drop",
                ConnectorEntryUpdate(
                    enabled=True,
                    config={
                        "outgoing_dir": "exports/eln",
                        "typo_field": "oops",
                    },
                ),
            )
        detail = get_connector_registry_detail("eln_file_drop")

    assert exc_info.value.status_code == 400
    assert any(issue["code"] == "unknown_field" for issue in exc_info.value.detail["issues"])
    assert detail["enabled"] is False
    assert detail["config_summary"]["configured"] is False


def test_update_connector_route_rejects_invalid_config_without_persisting_state(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, get_connector_registry_detail, update_connector_registry_entry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        with pytest.raises(HTTPException) as exc_info:
            update_connector_registry_entry(
                "instrument_webhook_ingest",
                ConnectorEntryUpdate(
                    enabled=True,
                    config={
                        "callback_path": "callbacks/instrument",
                        "accepted_event_types": ["run.finished"],
                    },
                ),
            )
        detail = get_connector_registry_detail("instrument_webhook_ingest")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["outcome"] == "invalid_input"
    assert detail["enabled"] is False
    assert detail["config_summary"]["configured"] is False


def test_validate_connector_uses_saved_config_when_request_body_is_omitted(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, update_connector_registry_entry, validate_connector_registry_entry

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "outgoing_dir": "exports/eln",
                    "include_archive": False,
                },
            ),
        )
        result = validate_connector_registry_entry("eln_file_drop")

    assert result["outcome"] == "success"
    assert result["config_summary"]["configured_fields"] == ["outgoing_dir", "include_archive"]


def test_file_drop_export_respects_include_archive_flag(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    _write_json(export_root / "eln_export.json", _example_json("eln_export.json"))
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export.json"
    )

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "outgoing_dir": "workspace/connector-drops",
                    "include_archive": False,
                },
            ),
        )
        export_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(artifact_path=artifact_path),
        )

    assert export_result["outcome"] == "success"
    assert export_result["artifact_paths"] == [artifact_path]
    assert export_result["external_paths"] == [
        str(
            isolated_connector_state
            / "workspace"
            / "connector-drops"
            / "artifacts"
            / "demo"
            / "2026-03-18"
            / "run-20260318T193000Z-deadbeef"
            / "outputs"
            / "generated"
            / "eln-export"
            / "eln_export.json"
        )
    ]


def test_file_drop_non_dry_run_export_requires_guardrail_artifacts(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    _write_json(export_root / "eln_export.json", _example_json("eln_export.json"))
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    manifest_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export.json"
    )
    compliance_path = (
        "artifacts/compliance-preflight/2026-03-18/run-20260318T193000Z-deadbeef/compliance_report.json"
    )
    _write_json(isolated_connector_state / compliance_path, _allowed_compliance_report_payload())

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={"outgoing_dir": "workspace/connector-drops"},
            ),
        )
        missing_compliance_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                dry_run=False,
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
            ),
        )
        missing_provenance_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                dry_run=False,
                compliance_artifact_path=compliance_path,
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
            ),
        )

    assert missing_compliance_result["outcome"] == "blocked"
    assert missing_compliance_result["issues"][0]["field"] == "compliance_artifact_path"
    assert missing_provenance_result["outcome"] == "blocked"
    assert missing_provenance_result["issues"][0]["field"] == "provenance_artifact_paths"


def test_file_drop_non_dry_run_export_blocks_invalid_registered_artifacts(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "eln_export.json").write_text("{bad json\n", encoding="utf-8")
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    manifest_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export.json"
    )
    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    compliance_path = (
        "artifacts/compliance-preflight/2026-03-18/run-20260318T193000Z-deadbeef/compliance_report.json"
    )
    provenance_path = "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/prov.json"
    _write_json(isolated_connector_state / compliance_path, _allowed_compliance_report_payload())
    _write_json(isolated_connector_state / provenance_path, _provenance_payload())

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={"outgoing_dir": "workspace/connector-drops"},
            ),
        )
        export_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                dry_run=False,
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
                compliance_artifact_path=compliance_path,
                provenance_artifact_paths=[provenance_path],
            ),
        )

    drop_root = isolated_connector_state / "workspace" / "connector-drops"
    assert export_result["outcome"] == "blocked"
    assert export_result["issues"][0]["field"] == "artifact_path"
    assert export_result["artifact_paths"] == [manifest_path]
    assert export_result["metadata"]["artifact_registry_status"] == "invalid"
    assert "Expecting property name enclosed in double quotes" in export_result["metadata"]["artifact_registry_error"]
    assert not (drop_root / manifest_path).exists()


def test_file_drop_non_dry_run_export_requires_matching_compliance_run_id(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "eln_export.json").write_text('{"stub": true}\n', encoding="utf-8")
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    compliance_path = (
        "artifacts/compliance-preflight/2026-03-19/run-20260319T193000Z-deadbeef/compliance_report.json"
    )
    provenance_path = "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/prov.json"
    _write_json(
        isolated_connector_state / compliance_path,
        _allowed_compliance_report_payload("run-20260319T193000Z-deadbeef"),
    )
    _write_json(isolated_connector_state / provenance_path, _provenance_payload())

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={"outgoing_dir": "workspace/connector-drops"},
            ),
        )
        export_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                dry_run=False,
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
                compliance_artifact_path=compliance_path,
                provenance_artifact_paths=[provenance_path],
            ),
        )

    assert export_result["outcome"] == "blocked"
    assert export_result["issues"][0]["field"] == "compliance_artifact_path"
    assert export_result["metadata"]["expected_run_id"] == "run-20260318T193000Z-deadbeef"
    assert export_result["metadata"]["observed_run_id"] == "run-20260319T193000Z-deadbeef"


def test_file_drop_action_exports_persisted_eln_files_and_reports_sync_status(isolated_connector_state):
    from api.audit import list_audit_events
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    _write_json(export_root / "eln_export.json", _example_json("eln_export.json"))
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    compliance_path = (
        "artifacts/compliance-preflight/2026-03-18/run-20260318T193000Z-deadbeef/compliance_report.json"
    )
    provenance_path = "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/prov.json"
    _write_json(isolated_connector_state / compliance_path, _allowed_compliance_report_payload())
    _write_json(isolated_connector_state / provenance_path, _provenance_payload())

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={"outgoing_dir": "workspace/connector-drops"},
            ),
        )
        export_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                dry_run=False,
                session_id="session-connector-export",
                workflow_id="demo",
                compliance_artifact_path=compliance_path,
                provenance_artifact_paths=[provenance_path],
            ),
        )
        sync_result = run_connector_registry_action(
            "eln_file_drop",
            "sync_status",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
            ),
        )
        audit_response = list_audit_events(
            event_type="connector_action",
            connector_name="eln_file_drop",
            run_id="run-20260318T193000Z-deadbeef",
            workflow_id="demo",
            limit=10,
        )

    drop_root = isolated_connector_state / "workspace" / "connector-drops" / "artifacts" / "demo"
    assert export_result["outcome"] == "success"
    assert export_result["metadata"]["compliance_artifact_path"] == compliance_path
    assert export_result["metadata"]["provenance_artifact_paths"] == [provenance_path]
    assert export_result["metadata"]["copied_count"] == 2
    assert (drop_root / "2026-03-18" / "run-20260318T193000Z-deadbeef" / "outputs" / "generated" / "eln-export" / "eln_export.json").exists()
    assert (drop_root / "2026-03-18" / "run-20260318T193000Z-deadbeef" / "outputs" / "generated" / "eln-export" / "eln_export_bundle.tar.gz").exists()
    assert sync_result["outcome"] == "success"
    assert sync_result["metadata"]["matching_count"] == 2
    assert {event["details"]["action"] for event in audit_response["events"]} >= {"export", "sync_status"}
    export_events = [event for event in audit_response["events"] if event["details"]["action"] == "export"]
    assert export_events
    assert export_events[0]["run_id"] == "run-20260318T193000Z-deadbeef"


def test_file_drop_export_execution_failure_returns_structured_result_and_audit_event(isolated_connector_state):
    from api.audit import list_audit_events
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    _write_json(export_root / "eln_export.json", _example_json("eln_export.json"))
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    manifest_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export.json"
    )
    compliance_path = (
        "artifacts/compliance-preflight/2026-03-18/run-20260318T193000Z-deadbeef/compliance_report.json"
    )
    provenance_path = "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/prov.json"
    _write_json(isolated_connector_state / compliance_path, _allowed_compliance_report_payload())
    _write_json(isolated_connector_state / provenance_path, _provenance_payload())
    (isolated_connector_state / "workspace" / "connector-drops").write_text("not a directory\n", encoding="utf-8")

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "eln_file_drop",
            ConnectorEntryUpdate(
                enabled=True,
                config={"outgoing_dir": "workspace/connector-drops"},
            ),
        )
        export_result = run_connector_registry_action(
            "eln_file_drop",
            "export",
            ConnectorActionRequest(
                artifact_path=artifact_path,
                dry_run=False,
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
                compliance_artifact_path=compliance_path,
                provenance_artifact_paths=[provenance_path],
            ),
        )
        audit_response = list_audit_events(
            event_type="connector_action",
            connector_name="eln_file_drop",
            run_id="run-20260318T193000Z-deadbeef",
            workflow_id="demo",
            outcome="execution_failure",
            limit=10,
        )

    assert export_result["outcome"] == "execution_failure"
    assert export_result["failure_mode"] == "remote_failure"
    assert export_result["metadata"]["error_type"] == "NotADirectoryError"
    assert export_result["metadata"]["copied_count"] == 0
    assert export_result["metadata"]["transfer_mode"] == "failed"
    assert export_result["metadata"]["attempted_source_path"] == manifest_path
    assert export_result["external_paths"][0].endswith("eln_export.json")
    assert len(audit_response["events"]) == 1
    event = audit_response["events"][0]
    assert event["details"]["action"] == "export"
    assert event["outcome"] == "execution_failure"
    assert event["details"]["metadata"]["error_type"] == "NotADirectoryError"


def test_file_drop_preflight_failure_preserves_artifact_context_and_derived_audit_run_id(isolated_connector_state):
    from api.audit import list_audit_events
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    _write_json(export_root / "eln_export.json", _example_json("eln_export.json"))
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    manifest_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export.json"
    )
    compliance_path = (
        "artifacts/compliance-preflight/2026-03-18/run-20260318T193000Z-deadbeef/compliance_report.json"
    )
    provenance_path = "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/prov.json"
    _write_json(isolated_connector_state / compliance_path, _allowed_compliance_report_payload())
    _write_json(isolated_connector_state / provenance_path, _provenance_payload())

    preexisting_manifest = (
        isolated_connector_state
        / "workspace"
        / "connector-drops"
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
        / "eln_export.json"
    )
    preexisting_manifest.parent.mkdir(parents=True, exist_ok=True)
    preexisting_manifest.write_text("placeholder\n", encoding="utf-8")
    preexisting_manifest.chmod(0)

    try:
        with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
            update_connector_registry_entry(
                "eln_file_drop",
                ConnectorEntryUpdate(
                    enabled=True,
                    config={"outgoing_dir": "workspace/connector-drops"},
                ),
            )
            export_result = run_connector_registry_action(
                "eln_file_drop",
                "export",
                ConnectorActionRequest(
                    artifact_path=artifact_path,
                    dry_run=False,
                    workflow_id="demo",
                    compliance_artifact_path=compliance_path,
                    provenance_artifact_paths=[provenance_path],
                ),
            )
            audit_response = list_audit_events(
                event_type="connector_action",
                connector_name="eln_file_drop",
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
                outcome="execution_failure",
                limit=10,
            )
    finally:
        preexisting_manifest.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert export_result["outcome"] == "execution_failure"
    assert export_result["failure_mode"] == "remote_failure"
    assert export_result["metadata"]["error_type"] == "PermissionError"
    assert export_result["metadata"]["attempted_source_path"] == manifest_path
    assert export_result["artifact_paths"] == [manifest_path, artifact_path]
    assert export_result["external_paths"][0].endswith("eln_export.json")
    assert len(audit_response["events"]) == 1
    event = audit_response["events"][0]
    assert event["run_id"] == "run-20260318T193000Z-deadbeef"
    assert event["artifact_paths"] == [manifest_path, artifact_path]
    assert event["details"]["metadata"]["error_type"] == "PermissionError"


def test_file_drop_sync_status_failure_preserves_artifact_context_and_derived_audit_run_id(isolated_connector_state):
    from api.audit import list_audit_events
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    export_root = (
        isolated_connector_state
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
    )
    export_root.mkdir(parents=True, exist_ok=True)
    _write_json(export_root / "eln_export.json", _example_json("eln_export.json"))
    (export_root / "eln_export_bundle.tar.gz").write_bytes(b"eln bundle")

    artifact_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export_bundle.tar.gz"
    )
    manifest_path = (
        "artifacts/demo/2026-03-18/run-20260318T193000Z-deadbeef/"
        "outputs/generated/eln-export/eln_export.json"
    )

    preexisting_manifest = (
        isolated_connector_state
        / "workspace"
        / "connector-drops"
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T193000Z-deadbeef"
        / "outputs"
        / "generated"
        / "eln-export"
        / "eln_export.json"
    )
    preexisting_manifest.parent.mkdir(parents=True, exist_ok=True)
    preexisting_manifest.write_text("placeholder\n", encoding="utf-8")
    preexisting_manifest.chmod(0)

    try:
        with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
            update_connector_registry_entry(
                "eln_file_drop",
                ConnectorEntryUpdate(
                    enabled=True,
                    config={"outgoing_dir": "workspace/connector-drops"},
                ),
            )
            sync_result = run_connector_registry_action(
                "eln_file_drop",
                "sync_status",
                ConnectorActionRequest(
                    artifact_path=artifact_path,
                    workflow_id="demo",
                ),
            )
            audit_response = list_audit_events(
                event_type="connector_action",
                connector_name="eln_file_drop",
                run_id="run-20260318T193000Z-deadbeef",
                workflow_id="demo",
                outcome="execution_failure",
                limit=10,
            )
    finally:
        preexisting_manifest.chmod(stat.S_IRUSR | stat.S_IWUSR)

    assert sync_result["outcome"] == "execution_failure"
    assert sync_result["failure_mode"] == "remote_failure"
    assert sync_result["metadata"]["error_type"] == "PermissionError"
    assert sync_result["metadata"]["attempted_source_path"] == manifest_path
    assert sync_result["artifact_paths"] == [manifest_path, artifact_path]
    assert sync_result["external_paths"][0].endswith("eln_export.json")
    assert len(audit_response["events"]) == 1
    event = audit_response["events"][0]
    assert event["details"]["action"] == "sync_status"
    assert event["run_id"] == "run-20260318T193000Z-deadbeef"
    assert event["artifact_paths"] == [manifest_path, artifact_path]
    assert event["details"]["metadata"]["error_type"] == "PermissionError"


def test_webhook_import_action_validates_supported_payload_and_sync_status(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"), patch.dict(
        os.environ,
        {"BIOAPEX_WEBHOOK_SECRET": "secret-token"},
        clear=False,
    ):
        update_connector_registry_entry(
            "instrument_webhook_ingest",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "callback_path": "/api/connectors/instrument",
                    "shared_secret_env": "BIOAPEX_WEBHOOK_SECRET",
                    "accepted_event_types": ["run.finished"],
                },
            ),
        )
        import_result = run_connector_registry_action(
            "instrument_webhook_ingest",
            "import",
            ConnectorActionRequest(
                payload=_qa_report_payload(),
                event_type="run.finished",
                delivery_signature="sha256=demo-signature",
            ),
        )
        sync_result = run_connector_registry_action(
            "instrument_webhook_ingest",
            "sync_status",
            ConnectorActionRequest(),
        )

    assert import_result["outcome"] == "success"
    assert import_result["metadata"]["artifact_preview"]["artifact_type"] == "qa_report"
    assert import_result["metadata"]["event_type"] == "run.finished"
    assert sync_result["outcome"] == "success"
    assert sync_result["metadata"]["secret_present"] is True


def test_webhook_import_requires_matching_compliance_run_id_without_request_run_id(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    compliance_path = (
        "artifacts/compliance-preflight/2026-03-19/run-20260319T193000Z-deadbeef/compliance_report.json"
    )
    _write_json(
        isolated_connector_state / compliance_path,
        _allowed_compliance_report_payload("run-20260319T193000Z-deadbeef"),
    )

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"), patch.dict(
        os.environ,
        {"BIOAPEX_WEBHOOK_SECRET": "secret-token"},
        clear=False,
    ):
        update_connector_registry_entry(
            "instrument_webhook_ingest",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "callback_path": "/api/connectors/instrument",
                    "shared_secret_env": "BIOAPEX_WEBHOOK_SECRET",
                    "accepted_event_types": ["run.finished"],
                },
            ),
        )
        import_result = run_connector_registry_action(
            "instrument_webhook_ingest",
            "import",
            ConnectorActionRequest(
                payload=_qa_report_payload(),
                dry_run=False,
                event_type="run.finished",
                delivery_signature="sha256=demo-signature",
                compliance_artifact_path=compliance_path,
            ),
        )

    assert import_result["outcome"] == "blocked"
    assert import_result["issues"][0]["field"] == "compliance_artifact_path"
    assert import_result["metadata"]["expected_run_id"] == "run-20260320T190000Z-deadbeef"
    assert import_result["metadata"]["observed_run_id"] == "run-20260319T193000Z-deadbeef"


def test_webhook_import_requires_signature_and_secret_and_rejects_unknown_event_type(isolated_connector_state):
    from api.connectors import ConnectorEntryUpdate, run_connector_registry_action, update_connector_registry_entry
    from connectors import ConnectorActionRequest

    with patch("config._CONFIG_FILE", isolated_connector_state / "config.json"):
        update_connector_registry_entry(
            "instrument_webhook_ingest",
            ConnectorEntryUpdate(
                enabled=True,
                config={
                    "callback_path": "/api/connectors/instrument",
                    "shared_secret_env": "BIOAPEX_WEBHOOK_SECRET",
                    "accepted_event_types": ["run.finished"],
                },
            ),
        )
        with patch.dict(os.environ, {"BIOAPEX_WEBHOOK_SECRET": "secret-token"}, clear=False):
            missing_signature_result = run_connector_registry_action(
                "instrument_webhook_ingest",
                "import",
                ConnectorActionRequest(
                    payload=_qa_report_payload(),
                    event_type="run.finished",
                ),
            )
            invalid_event_result = run_connector_registry_action(
                "instrument_webhook_ingest",
                "import",
                ConnectorActionRequest(
                    payload=_qa_report_payload(),
                    event_type="run.failed",
                    delivery_signature="sha256=demo-signature",
                ),
            )
        missing_secret_result = run_connector_registry_action(
            "instrument_webhook_ingest",
            "import",
            ConnectorActionRequest(
                payload=_qa_report_payload(),
                event_type="run.finished",
                delivery_signature="sha256=demo-signature",
            ),
        )

    assert missing_signature_result["outcome"] == "invalid_input"
    assert missing_signature_result["issues"][0]["field"] == "delivery_signature"
    assert invalid_event_result["outcome"] == "blocked"
    assert invalid_event_result["issues"][0]["field"] == "event_type"
    assert missing_secret_result["outcome"] == "blocked"
    assert missing_secret_result["metadata"]["secret_present"] is False
