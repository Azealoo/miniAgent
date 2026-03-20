"""BioCompute export helpers derived from canonical workflow and provenance artifacts."""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5

from workflow_specs import ExternalEngineExecutor, PythonExecutor, ToolExecutor, WorkflowSpec

from .naming import (
    RunLayout,
    build_artifact_header,
    compute_content_hash,
    resolve_artifact_path,
    stable_artifact_name,
)
from .public_urls import public_raw_file_url
from .schema_validation import validate_biocompute_payload_against_reference_schemas
from .schemas import (
    ArtifactReference,
    BioComputeArtifact,
    BioComputeExportStatus,
    DatasetManifest,
    ProvenanceArtifact,
    WorkflowRun,
    load_artifact_document,
    normalize_identifier,
)

_BIOCOMPUTE_SPEC_VERSION_URL = "https://w3id.org/ieee/ieee-2791-schema/2791object.json"
_BIOAPEX_BIOCOMPUTE_EXTENSION_SCHEMA_PATH = (
    "artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json"
)
_BIOAPEX_EMPIRICAL_ERROR_URI = "urn:bioapex:biocompute:error:observed-run-state:1.0.0"
_BIOAPEX_ALGORITHMIC_ERROR_URI = "urn:bioapex:biocompute:error:export-completeness:1.0.0"
_NOASSERTION_LICENSE = "NOASSERTION"
_SUPPORTED_BIOCOMPUTE_WORKFLOWS: dict[str, dict[str, Any]] = {
    "rnaseq_qc_de": {
        "object_type": "rna_seq_differential_expression",
        "keywords": [
            "bioapex",
            "bulk_rna_seq",
            "rna_seq_qc",
            "differential_expression",
        ],
    }
}
_ORGANISM_TAXONOMY_IDS = {
    "homo_sapiens": "9606",
    "mus_musculus": "10090",
    "rattus_norvegicus": "10116",
    "danio_rerio": "7955",
    "drosophila_melanogaster": "7227",
    "caenorhabditis_elegans": "6239",
    "saccharomyces_cerevisiae": "559292",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def supports_biocompute_export(workflow_id: str | None) -> bool:
    return workflow_id in _SUPPORTED_BIOCOMPUTE_WORKFLOWS


def expected_biocompute_export_paths(
    layout: RunLayout,
    *,
    workflow_id: str | None,
) -> list[str]:
    if not supports_biocompute_export(workflow_id):
        return []
    return [(layout.relative_run_dir / stable_artifact_name("biocompute")).as_posix()]


def materialize_biocompute_bundle(
    *,
    base_dir: Path,
    layout: RunLayout,
    run_document: WorkflowRun,
    spec: WorkflowSpec,
) -> list[str]:
    workflow_id = run_document.source_workflow or layout.workflow
    config = _SUPPORTED_BIOCOMPUTE_WORKFLOWS.get(workflow_id)
    if config is None:
        return []

    export_paths = expected_biocompute_export_paths(layout, workflow_id=workflow_id)
    exported_at = _workflow_end_time(run_document)
    run_ref = ArtifactReference(
        artifact_type="workflow_run",
        path=layout.run_record_relpath.as_posix(),
        id=run_document.id,
        run_id=run_document.run_id,
    )
    dataset_manifest = _load_dataset_manifest(base_dir, run_document)
    provenance = _load_provenance_artifact(base_dir, run_document)
    warnings: list[str] = []

    if dataset_manifest is None:
        warnings.append(
            "Dataset manifest could not be loaded from the canonical workflow inputs; the BioCompute export is partial."
        )
    if provenance is None:
        warnings.append(
            "Canonical provenance exports could not be loaded from disk; the BioCompute export is partial."
        )
    if not run_document.inputs:
        warnings.append("Workflow run did not retain canonical input references; the BioCompute export is partial.")
    if not run_document.outputs:
        warnings.append("Workflow run did not retain canonical output references; the BioCompute export is partial.")

    provenance_ref = _provenance_ref(run_document, provenance)
    related_artifacts = _dedupe_refs(
        [
            run_ref,
            provenance_ref,
            *run_document.inputs,
            *run_document.outputs,
        ]
    )
    usability_domain = _build_usability_domain(
        spec=spec,
        run_document=run_document,
        dataset_manifest=dataset_manifest,
    )
    description_domain = _build_description_domain(
        spec=spec,
        run_document=run_document,
        dataset_manifest=dataset_manifest,
        config=config,
        exported_at=exported_at,
    )
    execution_domain = _build_execution_domain(
        spec=spec,
        run_document=run_document,
        dataset_manifest=dataset_manifest,
        provenance=provenance,
        warnings=warnings,
    )
    parametric_domain = _build_parametric_domain(run_document)
    io_domain = _build_io_domain(
        base_dir=base_dir,
        run_document=run_document,
        warnings=warnings,
    )
    export_warnings = _dedupe_text(warnings)
    error_domain = _build_error_domain(run_document, export_warnings=export_warnings)

    payload = build_artifact_header(
        schema_version=run_document.schema_version,
        artifact_type="biocompute",
        run_id=run_document.run_id,
        created_at=exported_at,
        source_workflow=workflow_id,
    )
    payload["id"] = normalize_identifier(f"biocompute-{layout.workflow}-{layout.run_id.lower()}")
    payload["related_artifacts"] = [ref.model_dump(mode="json") for ref in related_artifacts]
    payload["spec_version"] = _BIOCOMPUTE_SPEC_VERSION_URL
    payload["object_id"] = f"urn:uuid:{uuid5(NAMESPACE_URL, export_paths[0])}"
    payload["type"] = config["object_type"]
    payload["provenance_domain"] = {
        "name": f"{spec.name} BioCompute export",
        "version": spec.version,
        "created": _workflow_start_time(run_document),
        "modified": exported_at,
        "contributors": [
            {
                "name": run_document.engine,
                "contribution": ["createdBy"],
            }
        ],
        "license": _NOASSERTION_LICENSE,
    }
    payload["usability_domain"] = usability_domain
    payload["description_domain"] = description_domain
    payload["execution_domain"] = execution_domain
    payload["parametric_domain"] = parametric_domain
    payload["io_domain"] = io_domain
    payload["error_domain"] = error_domain
    payload["extension_domain"] = _build_extension_domain(
        run_ref=run_ref,
        provenance_ref=provenance_ref,
        related_artifacts=related_artifacts,
        provenance_exports=run_document.provenance_exports,
        export_warnings=export_warnings,
    )
    payload["etag"] = _etag_for_payload(payload)

    validated = BioComputeArtifact.model_validate(payload)
    serialized = validated.model_dump(mode="json", exclude_none=True)
    validate_biocompute_payload_against_reference_schemas(serialized)
    target = layout._track_path(resolve_artifact_path(layout.run_dir, PurePosixPath(stable_artifact_name("biocompute"))))
    target.write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return export_paths


def _dedupe_refs(refs: Iterable[ArtifactReference | None]) -> list[ArtifactReference]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for ref in refs:
        if ref is None:
            continue
        key = (ref.artifact_type, ref.path, ref.id, ref.run_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _workflow_start_time(run_document: WorkflowRun) -> datetime:
    step_start_times = [record.start_time for record in run_document.steps if record.start_time is not None]
    return min(step_start_times, default=run_document.created_at)


def _workflow_end_time(run_document: WorkflowRun) -> datetime:
    step_end_times = [record.end_time for record in run_document.steps if record.end_time is not None]
    return max(step_end_times, default=run_document.created_at)


def _load_dataset_manifest(base_dir: Path, run_document: WorkflowRun) -> DatasetManifest | None:
    dataset_ref = next((ref for ref in run_document.inputs if ref.artifact_type == "dataset_manifest"), None)
    if dataset_ref is None:
        dataset_ref = next((ref for ref in run_document.related_artifacts if ref.artifact_type == "dataset_manifest"), None)
    if dataset_ref is None:
        return None
    try:
        document = load_artifact_document(resolve_artifact_path(base_dir, dataset_ref.path))
    except Exception:
        return None
    return document if isinstance(document, DatasetManifest) else None


def _load_provenance_artifact(base_dir: Path, run_document: WorkflowRun) -> ProvenanceArtifact | None:
    provenance_path = next((path for path in run_document.provenance_exports if path.endswith("/prov.json") or path == "prov.json"), None)
    if provenance_path is None:
        provenance_path = next((path for path in run_document.provenance_exports if path.endswith("prov.json")), None)
    if provenance_path is None:
        return None
    try:
        document = load_artifact_document(resolve_artifact_path(base_dir, provenance_path))
    except Exception:
        return None
    return document if isinstance(document, ProvenanceArtifact) else None


def _provenance_ref(run_document: WorkflowRun, provenance: ProvenanceArtifact | None) -> ArtifactReference | None:
    provenance_path = next((path for path in run_document.provenance_exports if path.endswith("prov.json")), None)
    if provenance_path is None:
        return None
    return ArtifactReference(
        artifact_type="provenance",
        path=provenance_path,
        id=provenance.id if provenance is not None else None,
        run_id=run_document.run_id,
    )


def _build_usability_domain(
    *,
    spec: WorkflowSpec,
    run_document: WorkflowRun,
    dataset_manifest: DatasetManifest | None,
) -> list[str]:
    lines = [spec.purpose]
    if dataset_manifest is not None:
        design = dataset_manifest.design
        lines.append(
            "Study "
            f"'{design.study_name}' uses assay '{dataset_manifest.assay_type}' in organism '{dataset_manifest.organism}'."
        )
        if dataset_manifest.reference_build:
            lines.append(f"Reference build: '{dataset_manifest.reference_build}'.")
    condition_field = run_document.parameters.get("condition_field")
    baseline = run_document.parameters.get("baseline_condition")
    comparison = run_document.parameters.get("comparison_condition")
    if all(isinstance(item, str) and item for item in (condition_field, baseline, comparison)):
        lines.append(
            f"Requested contrast compares '{comparison}' against '{baseline}' using condition field '{condition_field}'."
        )
    lines.append(
        f"Terminal workflow status is '{run_document.lifecycle_status}' with QC status '{run_document.qc_status}'."
    )
    return lines


def _build_description_domain(
    *,
    spec: WorkflowSpec,
    run_document: WorkflowRun,
    dataset_manifest: DatasetManifest | None,
    config: dict[str, Any],
    exported_at: datetime,
) -> dict[str, Any]:
    keywords = _dedupe_text(
        [
            *config.get("keywords", []),
            spec.workflow_id,
            run_document.lifecycle_status,
            run_document.qc_status,
            dataset_manifest.assay_type if dataset_manifest is not None else None,
            dataset_manifest.organism if dataset_manifest is not None else None,
        ]
    )
    xref = _build_description_xrefs(dataset_manifest, accessed_at=exported_at)

    record_by_id = {record.id: record for record in run_document.steps}
    pipeline_steps: list[dict[str, Any]] = []
    for index, step in enumerate(spec.steps, start=1):
        record = record_by_id.get(step.id)
        description = f"{step.label}. Recorded status: {record.status if record is not None else 'not_recorded'}."
        if step.prerequisites:
            description += f" Prerequisites: {', '.join(step.prerequisites)}."
        pipeline_steps.append(
            {
                "step_number": index,
                "name": step.label,
                "description": description,
                "version": spec.version,
                "prerequisite": [
                    {
                        "name": prerequisite,
                        "uri": {
                            "uri": f"urn:bioapex:step:{spec.workflow_id}:{prerequisite}",
                        },
                    }
                    for prerequisite in step.prerequisites
                ],
                "input_list": [
                    _uri_payload_for_ref(record_input)
                    for record_input in (record.inputs_resolved if record is not None else [])
                ],
                "output_list": [
                    _uri_payload_for_ref(record_output)
                    for record_output in (record.outputs_produced if record is not None else [])
                ],
            }
        )
    return {
        "keywords": keywords,
        "xref": xref,
        "platform": _dedupe_text(
            [
                run_document.environment.platform,
                run_document.environment.conda_env,
                run_document.engine,
            ]
        ),
        "pipeline_steps": pipeline_steps,
    }


def _build_execution_domain(
    *,
    spec: WorkflowSpec,
    run_document: WorkflowRun,
    dataset_manifest: DatasetManifest | None,
    provenance: ProvenanceArtifact | None,
    warnings: list[str],
) -> dict[str, Any]:
    script_entries: list[dict[str, Any]] = []
    seen_scripts: set[str] = set()
    for step in spec.steps:
        script_uri = _executor_uri(step.executor)
        if script_uri in seen_scripts:
            continue
        seen_scripts.add(script_uri)
        script_entries.append(
            {
                "uri": {
                    "uri": script_uri,
                    "filename": _executor_filename(step.executor),
                }
            }
        )

    software_prerequisites: list[dict[str, Any]] = []
    if provenance is not None and provenance.tool_versions:
        for tool in provenance.tool_versions:
            tool_uri = tool.source_artifact_path or f"tool://{tool.name}"
            if "://" not in tool_uri and not tool_uri.startswith("urn:"):
                tool_uri = public_raw_file_url(tool_uri)
            software_prerequisites.append(
                {
                    "name": tool.name,
                    "version": tool.version,
                    "uri": {
                        "uri": tool_uri,
                        "filename": PurePosixPath(tool.source_artifact_path).name if tool.source_artifact_path else None,
                    },
                }
            )
    else:
        warnings.append(
            "Software prerequisites were inferred from the workflow engine because canonical provenance tool versions were unavailable."
        )
        software_prerequisites.append(
            {
                "name": run_document.engine,
                "version": spec.version,
                "uri": {"uri": f"tool://{run_document.engine}"},
            }
        )

    external_data_endpoints: list[dict[str, Any]] = []
    if dataset_manifest is not None and dataset_manifest.reference_resource:
        external_data_endpoints.append(
            {
                "name": "reference_resource",
                "url": dataset_manifest.reference_resource,
            }
        )

    environment_variables = {
        key: value
        for key, value in {
            "CONDA_DEFAULT_ENV": run_document.environment.conda_env,
            "HOSTNAME": run_document.environment.hostname,
            "PLATFORM": run_document.environment.platform,
            "PYTHON_VERSION": run_document.environment.python_version,
        }.items()
        if isinstance(value, str) and value
    }
    return {
        "script": script_entries,
        "script_driver": run_document.engine,
        "software_prerequisites": software_prerequisites,
        "external_data_endpoints": external_data_endpoints,
        "environment_variables": environment_variables,
    }


def _build_parametric_domain(run_document: WorkflowRun) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for key in sorted(run_document.parameters):
        parameters.append(
            {
                "param": str(key),
                "value": _serialize_parameter_value(run_document.parameters[key]),
                "step": "workflow",
            }
        )
    return parameters


def _build_io_domain(
    *,
    base_dir: Path,
    run_document: WorkflowRun,
    warnings: list[str],
) -> dict[str, Any]:
    input_subdomain: list[dict[str, Any]] = []
    output_subdomain: list[dict[str, Any]] = []

    for ref in run_document.inputs:
        uri_payload = _uri_payload_for_ref(ref, base_dir=base_dir, warnings=warnings)
        input_subdomain.append({"uri": uri_payload})
    for ref in run_document.outputs:
        uri_payload = _uri_payload_for_ref(ref, base_dir=base_dir, warnings=warnings)
        output_subdomain.append(
            {
                "mediatype": _guess_mediatype(ref.path),
                "uri": uri_payload,
            }
        )

    return {
        "input_subdomain": input_subdomain,
        "output_subdomain": output_subdomain,
    }


def _build_error_domain(
    run_document: WorkflowRun,
    *,
    export_warnings: Iterable[str] = (),
) -> dict[str, Any]:
    export_warning_list = _dedupe_text(export_warnings)
    workflow_warnings = _dedupe_text(
        [
            *export_warning_list,
            *run_document.warnings,
            *(warning for record in run_document.steps for warning in record.warnings),
        ]
    )
    workflow_errors = _dedupe_text([error for record in run_document.steps for error in record.errors])
    return {
        "empirical_error": {
            _BIOAPEX_EMPIRICAL_ERROR_URI: {
                "title": "Observed workflow state",
                "description": "Observed terminal workflow warnings and errors carried into this BioCompute export.",
                "observed": {
                    "lifecycle_status": run_document.lifecycle_status,
                    "qc_status": run_document.qc_status,
                    "warning_count": len(workflow_warnings),
                    "error_count": len(workflow_errors),
                },
                "severity": "error" if workflow_errors else ("warning" if workflow_warnings else "info"),
                "messages": [*workflow_warnings, *workflow_errors],
            }
        },
        "algorithmic_error": {
            _BIOAPEX_ALGORITHMIC_ERROR_URI: {
                "title": "Export completeness",
                "description": "Algorithmic limits encountered while deriving the BioCompute export from canonical persisted artifacts.",
                "observed": {
                    "export_status": _export_status(export_warning_list),
                    "warning_count": len(export_warning_list),
                },
                "expected": {
                    "export_status": "full",
                    "warning_count": 0,
                },
                "severity": "warning" if export_warning_list else "info",
                "messages": export_warning_list,
            }
        },
    }


def _export_status(warnings: list[str]) -> BioComputeExportStatus:
    return "partial" if warnings else "full"


def _build_extension_domain(
    *,
    run_ref: ArtifactReference,
    provenance_ref: ArtifactReference | None,
    related_artifacts: Iterable[ArtifactReference],
    provenance_exports: Iterable[str],
    export_warnings: list[str],
) -> list[dict[str, Any]]:
    internal_references = [
        ref.model_dump(mode="json")
        for ref in related_artifacts
        if ref.artifact_type not in {"workflow_run", "provenance"}
    ]
    return [
        {
            "extension_schema": public_raw_file_url(_BIOAPEX_BIOCOMPUTE_EXTENSION_SCHEMA_PATH),
            "bioapex_extension": {
                "export_status": _export_status(export_warnings),
                "export_warnings": export_warnings,
                "workflow_run": run_ref.model_dump(mode="json"),
                "provenance_exports": list(provenance_exports),
                "provenance_artifact": provenance_ref.model_dump(mode="json") if provenance_ref is not None else None,
                "internal_references": internal_references,
            },
        }
    ]


def _build_description_xrefs(
    dataset_manifest: DatasetManifest | None,
    *,
    accessed_at: datetime,
) -> list[dict[str, Any]]:
    if dataset_manifest is None:
        return []
    taxonomy_id = _ORGANISM_TAXONOMY_IDS.get(dataset_manifest.organism.lower())
    if taxonomy_id is None:
        return []
    return [
        {
            "namespace": "taxonomy",
            "name": "NCBI Taxonomy",
            "ids": [taxonomy_id],
            "access_time": accessed_at,
        }
    ]


def _executor_uri(executor: ToolExecutor | PythonExecutor | ExternalEngineExecutor) -> str:
    if isinstance(executor, ToolExecutor):
        return f"tool://{executor.tool_name}"
    if isinstance(executor, PythonExecutor):
        return f"python://{executor.module}.{executor.function}"
    return executor.entrypoint


def _executor_filename(executor: ToolExecutor | PythonExecutor | ExternalEngineExecutor) -> str | None:
    if isinstance(executor, ToolExecutor):
        return f"{executor.tool_name}.tool"
    if isinstance(executor, PythonExecutor):
        return executor.module.split(".")[-1] + ".py"
    return PurePosixPath(executor.entrypoint).name


def _serialize_parameter_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _uri_payload_for_ref(
    ref: ArtifactReference,
    *,
    base_dir: Path | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "uri": public_raw_file_url(ref.path),
        "filename": PurePosixPath(ref.path).name,
    }
    if base_dir is not None:
        try:
            target = resolve_artifact_path(base_dir, ref.path)
        except Exception:
            if warnings is not None:
                warnings.append(f"Artifact reference '{ref.path}' could not be resolved while building the BioCompute export.")
            return payload
        if target.exists():
            payload["access_time"] = _isoformat_z(datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc))
        elif warnings is not None:
            warnings.append(f"Artifact reference '{ref.path}' did not exist on disk when the BioCompute export was generated.")
    return payload


def _guess_mediatype(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    if guessed:
        return guessed
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".tsv":
        return "text/tab-separated-values"
    if suffix == ".md":
        return "text/markdown"
    return "application/octet-stream"


def _etag_for_payload(payload: dict[str, Any]) -> str:
    without_etag = dict(payload)
    without_etag.pop("etag", None)
    canonical = json.dumps(
        _json_compatible(without_etag),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return compute_content_hash(canonical)


def _dedupe_text(values: Iterable[str | None]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _json_compatible(value: Any) -> Any:
    if isinstance(value, datetime):
        return _isoformat_z(value)
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    return value
