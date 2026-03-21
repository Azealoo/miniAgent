"""Executable connector adapter runtime for import, export, and sync status actions."""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

import config as cfg
from audit.store import append_connector_action_event
from artifacts import (
    ComplianceReport,
    ProvenanceArtifact,
    load_artifact_document,
    refresh_artifact_registry_path,
    validate_artifact_payload,
)

from .models import (
    ConnectorActionRequest,
    ConnectorActionResult,
    ConnectorDefinition,
    ConnectorExecutionAction,
    ConnectorValidationIssue,
)
from .registry import (
    get_connector_definition,
    summarize_connector_config,
    validate_connector_config,
)


class ConnectorRequestError(Exception):
    def __init__(self, issue: ConnectorValidationIssue):
        super().__init__(issue.message)
        self.issue = issue


def _clean_relative_path(raw_path: str) -> str:
    cleaned = raw_path.strip().lstrip("/").removeprefix("./")
    if not cleaned:
        raise ValueError("Path must not be empty.")
    if ".." in cleaned.split("/"):
        raise ValueError("Path must not contain '..'.")
    return str(PurePosixPath(cleaned))


def _resolve_internal_path(base_dir: Path, relative_path: str) -> tuple[str, Path]:
    cleaned = _clean_relative_path(relative_path)
    target = (base_dir / cleaned).resolve()
    try:
        target.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise ValueError("Resolved artifact path escapes the project directory.") from exc
    return cleaned, target


def _infer_domain_from_path(relative_path: str) -> str | None:
    pure_path = PurePosixPath(relative_path)
    if pure_path.name == "run.json":
        return "workflow_run"
    if pure_path.name == "protocol_run.yaml":
        return "protocol_run"
    if pure_path.name == "report_bundle_manifest.json":
        return "report_bundle_manifest"
    if pure_path.name == "eln_export.json":
        return "eln_export"
    if pure_path.name == "eln_export_bundle.tar.gz":
        return "eln_export"
    if "report-bundle" in pure_path.as_posix() and pure_path.suffix.lower() == ".md":
        return "report_bundle"
    return None


class ConnectorAdapter:
    def __init__(
        self,
        *,
        base_dir: Path,
        definition: ConnectorDefinition,
        config: dict[str, Any],
    ):
        self.base_dir = base_dir.resolve()
        self.definition = definition
        self.config = dict(config)
        self.config_summary = summarize_connector_config(definition, self.config)

    def _issue(self, field: str | None, code: str, message: str) -> ConnectorValidationIssue:
        return ConnectorValidationIssue(field=field, code=code, message=message)

    def _resolve_persisted_artifact_path(self, relative_path: str, *, field_name: str) -> tuple[str, Path]:
        try:
            artifact_relpath, artifact_path = _resolve_internal_path(self.base_dir, relative_path)
        except ValueError as exc:
            raise ConnectorRequestError(self._issue(field_name, "invalid_field_value", str(exc))) from exc
        if not artifact_relpath.startswith("artifacts/"):
            raise ConnectorRequestError(
                self._issue(
                    field_name,
                    "invalid_field_value",
                    f"{field_name} must point to a persisted file under artifacts/.",
                )
            )
        if not artifact_path.exists() or not artifact_path.is_file():
            raise ConnectorRequestError(
                self._issue(
                    field_name,
                    "invalid_field_value",
                    f"{field_name} does not exist as a file: {artifact_relpath}",
                )
            )
        return artifact_relpath, artifact_path

    def _guardrail_block(
        self,
        action: ConnectorExecutionAction,
        *,
        summary: str,
        issues: list[ConnectorValidationIssue],
        artifact_paths: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorActionResult:
        return self._failure(
            action,
            outcome="blocked",
            summary=summary,
            failure_mode="blocked_action",
            issues=issues,
            artifact_paths=artifact_paths,
            metadata=metadata,
        )

    def _expected_run_id(
        self,
        request: ConnectorActionRequest,
        artifact_paths: list[str],
        *,
        payload_run_id: str | None = None,
    ) -> str | None:
        if request.run_id is not None:
            return request.run_id
        if isinstance(payload_run_id, str) and payload_run_id.strip():
            return payload_run_id.strip()
        for artifact_relpath in artifact_paths:
            try:
                _, artifact_path = self._resolve_persisted_artifact_path(
                    artifact_relpath,
                    field_name="artifact_path",
                )
                document = load_artifact_document(artifact_path)
            except Exception:
                continue
            run_id = getattr(document, "run_id", None)
            if isinstance(run_id, str) and run_id.strip():
                return run_id.strip()
        return None

    def _enforce_execution_guardrails(
        self,
        action: ConnectorExecutionAction,
        request: ConnectorActionRequest,
        *,
        artifact_paths: list[str] | None = None,
        payload_run_id: str | None = None,
    ) -> tuple[ConnectorActionResult | None, dict[str, Any]]:
        if request.dry_run or action not in {"import", "export"}:
            return None, {}

        guardrails = self.definition.capabilities.guardrails
        candidate_artifact_paths = list(dict.fromkeys(artifact_paths or []))
        expected_run_id = self._expected_run_id(
            request,
            candidate_artifact_paths,
            payload_run_id=payload_run_id,
        )
        metadata: dict[str, Any] = {}
        guardrail_artifact_paths: list[str] = []
        artifact_field_names = {relative_path: "artifact_path" for relative_path in candidate_artifact_paths}

        if guardrails.requires_compliance_gate:
            if request.compliance_artifact_path is None:
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked because non-dry-run execution "
                        "requires an allowed compliance_report artifact."
                    ),
                    issues=[
                        self._issue(
                            "compliance_artifact_path",
                            "missing_required_field",
                            "compliance_artifact_path is required for non-dry-run connector execution.",
                        )
                    ],
                ), {}
            try:
                compliance_relpath, compliance_path = self._resolve_persisted_artifact_path(
                    request.compliance_artifact_path,
                    field_name="compliance_artifact_path",
                )
                compliance_document = load_artifact_document(compliance_path)
            except ConnectorRequestError as exc:
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked because the compliance gate "
                        "proof artifact could not be resolved."
                    ),
                    issues=[exc.issue],
                ), {}
            except Exception as exc:
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked because the compliance gate "
                        "proof artifact could not be loaded."
                    ),
                    issues=[
                        self._issue(
                            "compliance_artifact_path",
                            "invalid_field_value",
                            f"compliance_artifact_path could not be loaded: {exc}",
                        )
                    ],
                ), {}
            if not isinstance(compliance_document, ComplianceReport):
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked because the compliance gate "
                        "proof artifact is not a compliance_report."
                    ),
                    issues=[
                        self._issue(
                            "compliance_artifact_path",
                            "invalid_field_value",
                            "compliance_artifact_path must reference a compliance_report artifact.",
                        )
                    ],
                ), {}

            allowed_runtime_states = {"allowed", "warning_issued", "approved_override"}
            allowed_dispositions = {"allow", "allow_with_warning"}
            if (
                compliance_document.runtime_state not in allowed_runtime_states
                or compliance_document.final_disposition not in allowed_dispositions
            ):
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked by the referenced compliance "
                        "report disposition."
                    ),
                    issues=[
                        self._issue(
                            "compliance_artifact_path",
                            "invalid_field_value",
                            "compliance_artifact_path must reference an allowed compliance_report artifact for "
                            "non-dry-run connector execution.",
                        )
                    ],
                    artifact_paths=[compliance_relpath],
                    metadata={
                        "compliance_runtime_state": compliance_document.runtime_state,
                        "compliance_final_disposition": compliance_document.final_disposition,
                    },
                ), {}

            guardrail_artifact_paths.append(compliance_relpath)
            artifact_field_names[compliance_relpath] = "compliance_artifact_path"
            if expected_run_id is not None and compliance_document.run_id != expected_run_id:
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked because the compliance gate "
                        "proof artifact did not match the requested run_id."
                    ),
                    issues=[
                        self._issue(
                            "compliance_artifact_path",
                            "invalid_field_value",
                            "compliance_artifact_path must match the connector action run_id.",
                        )
                    ],
                    artifact_paths=[compliance_relpath],
                    metadata={
                        "expected_run_id": expected_run_id,
                        "observed_run_id": compliance_document.run_id,
                    },
                ), {}
            metadata.update(
                {
                    "compliance_artifact_path": compliance_relpath,
                    "compliance_runtime_state": compliance_document.runtime_state,
                    "compliance_final_disposition": compliance_document.final_disposition,
                }
            )

        if guardrails.requires_provenance_records and action == "export":
            if not request.provenance_artifact_paths:
                return self._guardrail_block(
                    action,
                    summary=(
                        f"Connector {self.definition.name} {action} was blocked because non-dry-run export "
                        "requires provenance artifact references."
                    ),
                    issues=[
                        self._issue(
                            "provenance_artifact_paths",
                            "missing_required_field",
                            "provenance_artifact_paths is required for non-dry-run connector export.",
                        )
                    ],
                ), {}

            resolved_provenance_paths: list[str] = []
            for raw_path in request.provenance_artifact_paths:
                try:
                    provenance_relpath, provenance_path = self._resolve_persisted_artifact_path(
                        raw_path,
                        field_name="provenance_artifact_paths",
                    )
                    provenance_document = load_artifact_document(provenance_path)
                except ConnectorRequestError as exc:
                    return self._guardrail_block(
                        action,
                        summary=(
                            f"Connector {self.definition.name} {action} was blocked because a provenance proof "
                            "artifact could not be resolved."
                        ),
                        issues=[exc.issue],
                    ), {}
                except Exception as exc:
                    return self._guardrail_block(
                        action,
                        summary=(
                            f"Connector {self.definition.name} {action} was blocked because a provenance proof "
                            "artifact could not be loaded."
                        ),
                        issues=[
                            self._issue(
                                "provenance_artifact_paths",
                                "invalid_field_value",
                                f"provenance proof artifact could not be loaded: {exc}",
                            )
                        ],
                    ), {}

                if not isinstance(provenance_document, ProvenanceArtifact):
                    return self._guardrail_block(
                        action,
                        summary=(
                            f"Connector {self.definition.name} {action} was blocked because a referenced "
                            "provenance proof artifact is not a provenance record."
                        ),
                        issues=[
                            self._issue(
                                "provenance_artifact_paths",
                                "invalid_field_value",
                                "provenance_artifact_paths must reference provenance artifacts.",
                            )
                        ],
                        artifact_paths=[provenance_relpath],
                    ), {}
                if expected_run_id is not None and provenance_document.run_id != expected_run_id:
                    return self._guardrail_block(
                        action,
                        summary=(
                            f"Connector {self.definition.name} {action} was blocked because a provenance proof "
                            "artifact did not match the requested run_id."
                        ),
                        issues=[
                            self._issue(
                                "provenance_artifact_paths",
                                "invalid_field_value",
                                "Each provenance artifact must match the connector action run_id.",
                            )
                        ],
                        artifact_paths=[provenance_relpath],
                        metadata={
                            "expected_run_id": expected_run_id,
                            "observed_run_id": provenance_document.run_id,
                        },
                    ), {}
                resolved_provenance_paths.append(provenance_relpath)

            guardrail_artifact_paths.extend(resolved_provenance_paths)
            for provenance_relpath in resolved_provenance_paths:
                artifact_field_names[provenance_relpath] = "provenance_artifact_paths"
            metadata["provenance_artifact_paths"] = resolved_provenance_paths

        if guardrails.requires_artifact_registration:
            registered_artifact_paths: list[str] = []
            for relative_path in dict.fromkeys(candidate_artifact_paths + guardrail_artifact_paths):
                try:
                    record = refresh_artifact_registry_path(self.base_dir, relative_path)
                except Exception:
                    record = None
                if record is None:
                    return self._guardrail_block(
                        action,
                        summary=(
                            f"Connector {self.definition.name} {action} was blocked because required artifacts "
                            "could not be registered."
                        ),
                        issues=[
                            self._issue(
                                artifact_field_names.get(relative_path, "artifact_path"),
                                "invalid_field_value",
                                f"Artifact registration failed for required path: {relative_path}",
                            )
                        ],
                        artifact_paths=[relative_path],
                    ), {}
                if record.status != "valid":
                    return self._guardrail_block(
                        action,
                        summary=(
                            f"Connector {self.definition.name} {action} was blocked because required artifacts "
                            "did not pass artifact registration validation."
                        ),
                        issues=[
                            self._issue(
                                artifact_field_names.get(relative_path, "artifact_path"),
                                "invalid_field_value",
                                f"Artifact registration returned an invalid record for required path: {relative_path}",
                            )
                        ],
                        artifact_paths=[relative_path],
                        metadata={
                            "artifact_registry_status": record.status,
                            "artifact_registry_error": record.error,
                        },
                    ), {}
                registered_artifact_paths.append(record.path)
            metadata["registered_artifact_paths"] = registered_artifact_paths

        return None, metadata

    def execute(
        self,
        action: ConnectorExecutionAction,
        request: ConnectorActionRequest,
    ) -> ConnectorActionResult:
        if action not in self.definition.capabilities.supported_actions:
            return self._failure(
                action,
                outcome="unsupported",
                summary=f"Connector {self.definition.name} does not support action {action}.",
                failure_mode="unsupported_capability",
                action_supported=False,
            )

        issues = validate_connector_config(self.definition, self.config)
        if issues:
            return self._failure(
                action,
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} configuration is incomplete or invalid.",
                failure_mode="invalid_configuration",
                issues=issues,
            )

        handler = getattr(self, f"_execute_{action}", None)
        if handler is None:
            return self._failure(
                action,
                outcome="unsupported",
                summary=f"Connector {self.definition.name} does not implement action {action}.",
                failure_mode="unsupported_capability",
                action_supported=False,
            )
        return handler(request)

    def _base_metadata(self, request: ConnectorActionRequest) -> dict[str, Any]:
        return {
            "dry_run": request.dry_run,
            "transport_patterns": self.definition.capabilities.transport_patterns,
            "artifact_domains": self.definition.capabilities.artifact_domains,
            "guardrails": self.definition.capabilities.guardrails.model_dump(mode="json"),
            "configured_fields": self.config_summary.configured_fields,
        }

    def _execution_failure(
        self,
        action: ConnectorExecutionAction,
        request: ConnectorActionRequest,
        *,
        summary: str,
        error: Exception,
        failure_mode: str = "remote_failure",
        artifact_paths: list[str] | None = None,
        external_paths: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorActionResult:
        failure_metadata = self._base_metadata(request)
        failure_metadata.update(
            {
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        if metadata:
            failure_metadata.update(metadata)
        return self._failure(
            action,
            outcome="execution_failure",
            summary=summary,
            failure_mode=failure_mode,
            artifact_paths=artifact_paths,
            external_paths=external_paths,
            metadata=failure_metadata,
        )

    def _success(
        self,
        action: ConnectorExecutionAction,
        request: ConnectorActionRequest,
        *,
        summary: str,
        metadata: dict[str, Any] | None = None,
        artifact_paths: list[str] | None = None,
        external_paths: list[str] | None = None,
    ) -> ConnectorActionResult:
        combined_metadata = self._base_metadata(request)
        if metadata:
            combined_metadata.update(metadata)
        return ConnectorActionResult(
            connector_name=self.definition.name,
            action=action,
            status="success",
            outcome="success",
            summary=summary,
            config_summary=self.config_summary,
            artifact_paths=artifact_paths or [],
            external_paths=external_paths or [],
            metadata=combined_metadata,
        )

    def _failure(
        self,
        action: ConnectorExecutionAction,
        *,
        outcome: str,
        summary: str,
        failure_mode: str,
        issues: list[ConnectorValidationIssue] | None = None,
        metadata: dict[str, Any] | None = None,
        artifact_paths: list[str] | None = None,
        external_paths: list[str] | None = None,
        action_supported: bool = True,
    ) -> ConnectorActionResult:
        combined_metadata = {
            "transport_patterns": self.definition.capabilities.transport_patterns,
            "artifact_domains": self.definition.capabilities.artifact_domains,
            "guardrails": self.definition.capabilities.guardrails.model_dump(mode="json"),
            "configured_fields": self.config_summary.configured_fields,
        }
        if metadata:
            combined_metadata.update(metadata)
        return ConnectorActionResult(
            connector_name=self.definition.name,
            action=action,
            status="failed",
            outcome=outcome,
            summary=summary,
            action_supported=action_supported,
            failure_mode=failure_mode,
            issues=issues or [],
            config_summary=self.config_summary,
            artifact_paths=artifact_paths or [],
            external_paths=external_paths or [],
            metadata=combined_metadata,
        )


class ELNFileDropAdapter(ConnectorAdapter):
    def _include_archive_enabled(self) -> bool:
        if "include_archive" not in self.config:
            return True
        return bool(self.config["include_archive"])

    def _destination_root(self) -> Path:
        raw = str(self.config["outgoing_dir"]).strip()
        target = Path(raw)
        if not target.is_absolute():
            target = (self.base_dir / target).resolve()
        return target

    def _export_sources(self, request: ConnectorActionRequest) -> tuple[list[str], str]:
        if request.artifact_path is None:
            issue = ConnectorValidationIssue(
                field="artifact_path",
                code="missing_required_field",
                message="artifact_path is required for file-drop export and sync status actions.",
            )
            raise ConnectorRequestError(issue)

        artifact_relpath, artifact_path = self._resolve_persisted_artifact_path(
            request.artifact_path,
            field_name="artifact_path",
        )

        inferred_domain = _infer_domain_from_path(artifact_relpath)
        source_paths = [artifact_relpath]
        descriptor = inferred_domain or artifact_path.name
        include_archive = self._include_archive_enabled()

        if inferred_domain == "workflow_run":
            try:
                workflow_run = load_artifact_document(artifact_path)
            except Exception as exc:
                issue = ConnectorValidationIssue(
                    field="artifact_path",
                    code="invalid_field_value",
                    message=f"workflow_run artifact could not be loaded: {exc}",
                )
                raise ConnectorRequestError(issue) from exc
            export_paths = list(getattr(workflow_run, "eln_exports", []))
            if not include_archive:
                export_paths = [path for path in export_paths if not path.endswith("eln_export_bundle.tar.gz")]
            if not export_paths:
                issue = ConnectorValidationIssue(
                    field="artifact_path",
                    code="invalid_field_value",
                    message="workflow_run does not reference any persisted eln_exports.",
                )
                raise ConnectorRequestError(issue)
            source_paths = export_paths
            descriptor = "workflow_run ELN exports"
        elif inferred_domain == "eln_export":
            sibling_manifest = str(PurePosixPath(artifact_relpath).with_name("eln_export.json"))
            sibling_archive = str(PurePosixPath(artifact_relpath).with_name("eln_export_bundle.tar.gz"))
            if artifact_relpath.endswith("eln_export.json"):
                if include_archive and (self.base_dir / sibling_archive).exists():
                    source_paths.append(sibling_archive)
                descriptor = "ELN export manifest"
            elif artifact_relpath.endswith("eln_export_bundle.tar.gz"):
                if include_archive:
                    if (self.base_dir / sibling_manifest).exists():
                        source_paths.insert(0, sibling_manifest)
                    descriptor = "ELN export bundle"
                elif (self.base_dir / sibling_manifest).exists():
                    source_paths = [sibling_manifest]
                    descriptor = "ELN export manifest"
                else:
                    issue = ConnectorValidationIssue(
                        field="artifact_path",
                        code="invalid_field_value",
                        message=(
                            "include_archive is disabled, but the requested artifact_path points to the ELN export "
                            "archive and no manifest is available instead."
                        ),
                    )
                    raise ConnectorRequestError(issue)

        if inferred_domain is None and descriptor not in self.definition.capabilities.artifact_domains:
            issue = ConnectorValidationIssue(
                field="artifact_path",
                code="invalid_field_value",
                message=f"artifact_path does not resolve to a supported export domain for connector {self.definition.name}.",
            )
            raise ConnectorRequestError(issue)

        deduped_paths = list(dict.fromkeys(source_paths))
        for source_relpath in deduped_paths:
            try:
                self._resolve_persisted_artifact_path(source_relpath, field_name="artifact_path")
            except ConnectorRequestError as exc:
                raise ConnectorRequestError(
                    ConnectorValidationIssue(
                        field="artifact_path",
                        code=exc.issue.code,
                        message=f"Referenced export source is missing on disk: {source_relpath}",
                    )
                ) from exc
        return deduped_paths, descriptor

    def _planned_destinations(self, source_paths: list[str]) -> list[Path]:
        destination_root = self._destination_root()
        return [(destination_root / PurePosixPath(source_path)).resolve() for source_path in source_paths]

    def _copy_preflight(
        self,
        request: ConnectorActionRequest,
        source_paths: list[str],
        destination_paths: list[Path],
        *,
        descriptor: str,
        guardrail_metadata: dict[str, Any],
    ) -> ConnectorActionResult | None:
        conflicts: list[str] = []
        for source_relpath, destination_path in zip(source_paths, destination_paths):
            _, source_path = _resolve_internal_path(self.base_dir, source_relpath)
            if destination_path.exists():
                try:
                    if not destination_path.is_file():
                        conflicts.append(f"{destination_path} is not a file.")
                        continue
                    if source_path.read_bytes() != destination_path.read_bytes():
                        conflicts.append(f"{destination_path} already exists with different content.")
                except Exception as exc:
                    return self._execution_failure(
                        "export",
                        request,
                        summary=(
                            f"Connector {self.definition.name} export failed while preparing file-drop output."
                        ),
                        error=exc,
                        artifact_paths=source_paths,
                        external_paths=[str(path) for path in destination_paths],
                        metadata={
                            "descriptor": descriptor,
                            "copied_count": 0,
                            "copied_external_paths": [],
                            "attempted_external_path": str(destination_path),
                            "attempted_source_path": source_relpath,
                            "transfer_mode": "failed",
                            **guardrail_metadata,
                        },
                    )
        if conflicts:
            return self._failure(
                "export",
                outcome="blocked",
                summary="File-drop export was blocked because destination files would be overwritten with different content.",
                failure_mode="sync_conflict",
                artifact_paths=source_paths,
                external_paths=[str(path) for path in destination_paths],
                metadata={"conflicts": conflicts},
            )
        return None

    def _execute_export(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        try:
            source_paths, descriptor = self._export_sources(request)
        except ConnectorRequestError as exc:
            issues = [exc.issue]
            return self._failure(
                "export",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} export request is invalid.",
                failure_mode="blocked_action",
                issues=issues,
            )

        guardrail_result, guardrail_metadata = self._enforce_execution_guardrails(
            "export",
            request,
            artifact_paths=source_paths,
        )
        if guardrail_result is not None:
            return guardrail_result

        destination_paths = self._planned_destinations(source_paths)
        conflict_result = self._copy_preflight(
            request,
            source_paths,
            destination_paths,
            descriptor=descriptor,
            guardrail_metadata=guardrail_metadata,
        )
        if conflict_result is not None:
            return conflict_result

        copied_count = 0
        copied_external_paths: list[str] = []
        if not request.dry_run:
            try:
                for source_relpath, destination_path in zip(source_paths, destination_paths):
                    _, source_path = _resolve_internal_path(self.base_dir, source_relpath)
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    if destination_path.exists():
                        continue
                    shutil.copy2(source_path, destination_path)
                    copied_count += 1
                    copied_external_paths.append(str(destination_path))
            except Exception as exc:
                attempted_external_path = str(destination_path)
                attempted_source_path = source_relpath
                return self._execution_failure(
                    "export",
                    request,
                    summary=(
                        f"Connector {self.definition.name} export failed while writing file-drop output."
                    ),
                    error=exc,
                    failure_mode="partial_result" if copied_count else "remote_failure",
                    artifact_paths=source_paths,
                    external_paths=[str(path) for path in destination_paths],
                    metadata={
                        "descriptor": descriptor,
                        "copied_count": copied_count,
                        "copied_external_paths": copied_external_paths,
                        "attempted_external_path": attempted_external_path,
                        "attempted_source_path": attempted_source_path,
                        "transfer_mode": "partial" if copied_count else "failed",
                        **guardrail_metadata,
                    },
                )

        transfer_mode = "planned" if request.dry_run else "copied"
        return self._success(
            "export",
            request,
            summary=(
                f"Connector {self.definition.name} {transfer_mode} {len(source_paths)} file-drop export file(s) for {descriptor}."
            ),
            artifact_paths=source_paths,
            external_paths=[str(path) for path in destination_paths],
            metadata={
                "descriptor": descriptor,
                "copied_count": copied_count,
                "transfer_mode": transfer_mode,
                **guardrail_metadata,
            },
        )

    def _execute_sync_status(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        destination_root = self._destination_root()
        if request.artifact_path is None:
            return self._success(
                "sync_status",
                request,
                summary=f"Connector {self.definition.name} is configured for file-drop sync status checks.",
                external_paths=[str(destination_root)],
                metadata={
                    "destination_exists": destination_root.exists(),
                    "destination_is_directory": destination_root.is_dir(),
                },
            )

        try:
            source_paths, descriptor = self._export_sources(request)
        except ConnectorRequestError as exc:
            issues = [exc.issue]
            return self._failure(
                "sync_status",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} sync status request is invalid.",
                failure_mode="blocked_action",
                issues=issues,
            )

        destination_paths = self._planned_destinations(source_paths)
        present = 0
        matching = 0
        for source_relpath, destination_path in zip(source_paths, destination_paths):
            _, source_path = _resolve_internal_path(self.base_dir, source_relpath)
            try:
                if destination_path.exists() and destination_path.is_file():
                    present += 1
                    if source_path.read_bytes() == destination_path.read_bytes():
                        matching += 1
            except Exception as exc:
                return self._execution_failure(
                    "sync_status",
                    request,
                    summary=(
                        f"Connector {self.definition.name} sync status failed while reading file-drop state."
                    ),
                    error=exc,
                    artifact_paths=source_paths,
                    external_paths=[str(path) for path in destination_paths],
                    metadata={
                        "destination_exists": destination_root.exists(),
                        "present_count": present,
                        "matching_count": matching,
                        "descriptor": descriptor,
                        "attempted_external_path": str(destination_path),
                        "attempted_source_path": source_relpath,
                    },
                )

        return self._success(
            "sync_status",
            request,
            summary=(
                f"Connector {self.definition.name} found {matching} in-sync file(s) out of {len(source_paths)} planned file-drop transfer(s) for {descriptor}."
            ),
            artifact_paths=source_paths,
            external_paths=[str(path) for path in destination_paths],
            metadata={
                "destination_exists": destination_root.exists(),
                "present_count": present,
                "matching_count": matching,
                "descriptor": descriptor,
            },
        )


class LIMSRestBridgeAdapter(ConnectorAdapter):
    def _endpoint_url(self, suffix: str) -> str:
        base_url = str(self.config["base_url"]).rstrip("/")
        project_slug = str(self.config["project_slug"]).strip()
        return f"{base_url}/projects/{project_slug}/{suffix.lstrip('/')}"

    def _payload_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        document = validate_artifact_payload(payload)
        if document.artifact_type not in self.definition.capabilities.artifact_domains:
            raise ConnectorRequestError(
                ConnectorValidationIssue(
                    field="payload",
                    code="invalid_field_value",
                    message=f"Artifact type {document.artifact_type!r} is not supported by connector {self.definition.name}.",
                )
            )
        return {
            "artifact_type": document.artifact_type,
            "artifact_id": document.id,
            "run_id": document.run_id,
        }

    def _artifact_preview_from_path(self, artifact_path: str) -> tuple[str, dict[str, Any]]:
        artifact_relpath, source_path = _resolve_internal_path(self.base_dir, artifact_path)
        if not artifact_relpath.startswith("artifacts/"):
            raise ConnectorRequestError(
                ConnectorValidationIssue(
                    field="artifact_path",
                    code="invalid_field_value",
                    message="artifact_path must point to a persisted file under artifacts/.",
                )
            )
        if not source_path.exists() or not source_path.is_file():
            raise ConnectorRequestError(
                ConnectorValidationIssue(
                    field="artifact_path",
                    code="invalid_field_value",
                    message=f"artifact_path does not exist as a file: {artifact_relpath}",
                )
            )
        try:
            document = load_artifact_document(source_path)
            artifact_type = document.artifact_type
            preview = {
                "artifact_type": artifact_type,
                "artifact_id": document.id,
                "run_id": document.run_id,
            }
        except Exception:
            artifact_type = _infer_domain_from_path(artifact_relpath) or "artifact_file"
            preview = {
                "artifact_type": artifact_type,
                "artifact_id": PurePosixPath(artifact_relpath).name,
                "run_id": None,
            }
        if artifact_type not in self.definition.capabilities.artifact_domains:
            raise ConnectorRequestError(
                ConnectorValidationIssue(
                    field="artifact_path",
                    code="invalid_field_value",
                    message=f"Artifact type {artifact_type!r} is not supported by connector {self.definition.name}.",
                )
            )
        return artifact_relpath, preview

    def _action_error(self, action: ConnectorExecutionAction, field: str, message: str) -> ConnectorActionResult:
        return self._failure(
            action,
            outcome="invalid_input",
            summary=f"Connector {self.definition.name} {action} request is invalid.",
            failure_mode="blocked_action",
            issues=[
                ConnectorValidationIssue(
                    field=field,
                    code="invalid_field_value" if field != "payload" else "missing_required_field",
                    message=message,
                )
            ],
        )

    def _execute_export(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        if request.artifact_path is None:
            return self._action_error("export", "artifact_path", "artifact_path is required for REST export preview.")
        try:
            artifact_relpath, preview = self._artifact_preview_from_path(request.artifact_path)
        except ConnectorRequestError as exc:
            issues = [exc.issue]
            return self._failure(
                "export",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} export request is invalid.",
                failure_mode="blocked_action",
                issues=issues,
            )
        guardrail_result, guardrail_metadata = self._enforce_execution_guardrails(
            "export",
            request,
            artifact_paths=[artifact_relpath],
        )
        if guardrail_result is not None:
            return guardrail_result
        endpoint_url = self._endpoint_url("exports")
        return self._success(
            "export",
            request,
            summary=f"Connector {self.definition.name} prepared a REST export preview for {preview['artifact_type']}.",
            artifact_paths=[artifact_relpath],
            external_paths=[endpoint_url],
            metadata={
                "endpoint_url": endpoint_url,
                "artifact_preview": preview,
                **guardrail_metadata,
            },
        )

    def _execute_import(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        if not request.payload:
            return self._action_error("import", "payload", "payload is required for REST import preview.")
        try:
            preview = self._payload_preview(request.payload)
        except ConnectorRequestError as exc:
            issues = [exc.issue]
            return self._failure(
                "import",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} import payload is invalid.",
                failure_mode="blocked_action",
                issues=issues,
            )
        guardrail_result, guardrail_metadata = self._enforce_execution_guardrails(
            "import",
            request,
            payload_run_id=preview["run_id"],
        )
        if guardrail_result is not None:
            return guardrail_result
        endpoint_url = self._endpoint_url("imports")
        return self._success(
            "import",
            request,
            summary=f"Connector {self.definition.name} validated a REST import payload for {preview['artifact_type']}.",
            external_paths=[endpoint_url],
            metadata={
                "endpoint_url": endpoint_url,
                "artifact_preview": preview,
                **guardrail_metadata,
            },
        )

    def _execute_sync_status(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        auth_strategy = str(self.config["auth_strategy"]).strip()
        credential_env_var = str(self.config.get("credential_env_var") or "").strip()
        credential_present = bool(os.environ.get(credential_env_var, "")) if credential_env_var else False
        endpoint_url = self._endpoint_url("health")
        if auth_strategy in {"token_env", "basic_auth_env"} and not credential_present:
            return self._failure(
                "sync_status",
                outcome="blocked",
                summary=f"Connector {self.definition.name} is missing the configured credential environment variable.",
                failure_mode="blocked_action",
                external_paths=[endpoint_url],
                metadata={
                    "endpoint_url": endpoint_url,
                    "auth_strategy": auth_strategy,
                    "credential_env_var": credential_env_var,
                    "credential_present": credential_present,
                },
            )

        return self._success(
            "sync_status",
            request,
            summary=f"Connector {self.definition.name} is ready for REST synchronization checks.",
            external_paths=[endpoint_url],
            metadata={
                "endpoint_url": endpoint_url,
                "auth_strategy": auth_strategy,
                "credential_env_var": credential_env_var or None,
                "credential_present": credential_present if credential_env_var else None,
            },
        )


class InstrumentWebhookAdapter(ConnectorAdapter):
    def _execute_import(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        if not request.payload:
            return self._failure(
                "import",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} import payload is invalid.",
                failure_mode="blocked_action",
                issues=[
                    ConnectorValidationIssue(
                        field="payload",
                        code="missing_required_field",
                        message="payload is required for webhook import preview.",
                    )
                ],
            )
        if request.event_type is None:
            return self._failure(
                "import",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} import payload is invalid.",
                failure_mode="blocked_action",
                issues=[
                    ConnectorValidationIssue(
                        field="event_type",
                        code="missing_required_field",
                        message="event_type is required for webhook import preview.",
                    )
                ],
            )
        if request.delivery_signature is None:
            return self._failure(
                "import",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} import payload is invalid.",
                failure_mode="blocked_action",
                issues=[
                    ConnectorValidationIssue(
                        field="delivery_signature",
                        code="missing_required_field",
                        message="delivery_signature is required for webhook import preview.",
                    )
                ],
            )
        accepted_event_types = [str(item).strip() for item in self.config["accepted_event_types"]]
        if request.event_type not in accepted_event_types:
            return self._failure(
                "import",
                outcome="blocked",
                summary=f"Connector {self.definition.name} rejected the webhook event type.",
                failure_mode="blocked_action",
                issues=[
                    ConnectorValidationIssue(
                        field="event_type",
                        code="invalid_field_value",
                        message=f"event_type {request.event_type!r} is not allowed for connector {self.definition.name}.",
                    )
                ],
                metadata={
                    "event_type": request.event_type,
                    "accepted_event_types": accepted_event_types,
                },
            )
        shared_secret_env = str(self.config["shared_secret_env"]).strip()
        secret_present = bool(os.environ.get(shared_secret_env, ""))
        if not secret_present:
            return self._failure(
                "import",
                outcome="blocked",
                summary=f"Connector {self.definition.name} is missing the configured webhook secret environment variable.",
                failure_mode="blocked_action",
                metadata={
                    "callback_path": self.config["callback_path"],
                    "shared_secret_env": shared_secret_env,
                    "secret_present": secret_present,
                    "accepted_event_types": accepted_event_types,
                    "event_type": request.event_type,
                },
            )
        try:
            preview = validate_artifact_payload(request.payload)
        except Exception as exc:
            return self._failure(
                "import",
                outcome="invalid_input",
                summary=f"Connector {self.definition.name} import payload is invalid.",
                failure_mode="blocked_action",
                issues=[
                    ConnectorValidationIssue(
                        field="payload",
                        code="invalid_field_value",
                        message=str(exc),
                    )
                ],
            )
        if preview.artifact_type not in self.definition.capabilities.artifact_domains:
            return self._failure(
                "import",
                outcome="unsupported",
                summary=f"Artifact type {preview.artifact_type!r} is not supported by connector {self.definition.name}.",
                failure_mode="unsupported_capability",
                action_supported=False,
            )
        guardrail_result, guardrail_metadata = self._enforce_execution_guardrails(
            "import",
            request,
            payload_run_id=preview.run_id,
        )
        if guardrail_result is not None:
            return guardrail_result
        return self._success(
            "import",
            request,
            summary=f"Connector {self.definition.name} validated a webhook import payload for {preview.artifact_type}.",
            metadata={
                "artifact_preview": {
                    "artifact_type": preview.artifact_type,
                    "artifact_id": preview.id,
                    "run_id": preview.run_id,
                },
                "callback_path": self.config["callback_path"],
                "accepted_event_types": accepted_event_types,
                "event_type": request.event_type,
                "delivery_signature_present": True,
                "secret_present": secret_present,
                **guardrail_metadata,
            },
        )

    def _execute_sync_status(self, request: ConnectorActionRequest) -> ConnectorActionResult:
        shared_secret_env = str(self.config["shared_secret_env"]).strip()
        secret_present = bool(os.environ.get(shared_secret_env, ""))
        if not secret_present:
            return self._failure(
                "sync_status",
                outcome="blocked",
                summary=f"Connector {self.definition.name} is missing the configured webhook secret environment variable.",
                failure_mode="blocked_action",
                metadata={
                    "callback_path": self.config["callback_path"],
                    "shared_secret_env": shared_secret_env,
                    "secret_present": secret_present,
                    "accepted_event_types": self.config["accepted_event_types"],
                },
            )

        return self._success(
            "sync_status",
            request,
            summary=f"Connector {self.definition.name} is ready to receive webhook callbacks.",
            metadata={
                "callback_path": self.config["callback_path"],
                "shared_secret_env": shared_secret_env,
                "secret_present": secret_present,
                "accepted_event_types": self.config["accepted_event_types"],
            },
        )


_ADAPTERS = {
    "eln_file_drop": ELNFileDropAdapter,
    "lims_rest_bridge": LIMSRestBridgeAdapter,
    "instrument_webhook_ingest": InstrumentWebhookAdapter,
}


def _run_id_from_artifact_paths(base_dir: Path, artifact_paths: list[str]) -> str | None:
    for artifact_relpath in artifact_paths:
        try:
            cleaned_relpath, artifact_path = _resolve_internal_path(base_dir, artifact_relpath)
        except Exception:
            continue
        if not cleaned_relpath.startswith("artifacts/") or not artifact_path.exists() or not artifact_path.is_file():
            continue
        try:
            document = load_artifact_document(artifact_path)
        except Exception:
            continue
        run_id = getattr(document, "run_id", None)
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
    return None


def _resolve_result_run_id(
    *,
    base_dir: Path,
    request: ConnectorActionRequest,
    result: ConnectorActionResult,
) -> str | None:
    if request.run_id is not None:
        return request.run_id
    artifact_preview = result.metadata.get("artifact_preview")
    if isinstance(artifact_preview, dict):
        preview_run_id = artifact_preview.get("run_id")
        if isinstance(preview_run_id, str) and preview_run_id.strip():
            return preview_run_id.strip()
    expected_run_id = result.metadata.get("expected_run_id")
    if isinstance(expected_run_id, str) and expected_run_id.strip():
        return expected_run_id.strip()
    return _run_id_from_artifact_paths(base_dir, result.artifact_paths)


def execute_connector_action(
    connector_name: str,
    *,
    action: ConnectorExecutionAction,
    request: ConnectorActionRequest,
    base_dir: Path | str,
) -> ConnectorActionResult:
    definition = get_connector_definition(connector_name)
    stored = cfg.get_connector_entry(definition.name)
    config_summary = summarize_connector_config(definition, stored["config"])
    if not stored["enabled"]:
        result = ConnectorActionResult(
            connector_name=definition.name,
            action=action,
            status="failed",
            outcome="blocked",
            summary=f"Connector {definition.name} is disabled and cannot execute {action}.",
            failure_mode="blocked_action",
            config_summary=config_summary,
            metadata={
                "transport_patterns": definition.capabilities.transport_patterns,
                "artifact_domains": definition.capabilities.artifact_domains,
                "guardrails": definition.capabilities.guardrails.model_dump(mode="json"),
                "configured_fields": config_summary.configured_fields,
            },
        )
    else:
        adapter_cls = _ADAPTERS[definition.name]
        adapter = adapter_cls(
            base_dir=Path(base_dir),
            definition=definition,
            config=stored["config"],
        )
        try:
            result = adapter.execute(action, request)
        except Exception as exc:
            result = adapter._execution_failure(
                action,
                request,
                summary=f"Connector {definition.name} {action} failed during execution.",
                error=exc,
            )

    resolved_run_id = _resolve_result_run_id(
        base_dir=Path(base_dir),
        request=request,
        result=result,
    )

    append_connector_action_event(
        base_dir,
        connector_name=definition.name,
        action=action,
        outcome=result.outcome,
        status=result.status,
        failure_mode=result.failure_mode,
        session_id=request.session_id,
        run_id=resolved_run_id,
        workflow_id=request.workflow_id,
        artifact_paths=result.artifact_paths,
        external_systems=[definition.external_system],
        details={
            "issues": [issue.model_dump(mode="json") for issue in result.issues],
            "config_summary": result.config_summary.model_dump(mode="json") if result.config_summary else None,
            "external_paths": result.external_paths,
            "metadata": result.metadata,
        },
    )
    return result
