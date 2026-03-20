"""RO-Crate and PROV-compatible workflow provenance export helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .naming import (
    RunLayout,
    build_artifact_header,
    compute_content_hash,
    resolve_artifact_path,
    stable_artifact_name,
)
from .schemas import ArtifactReference, WorkflowRun, load_artifact_document, normalize_identifier

_RO_CRATE_CONTEXT_URL = "https://w3id.org/ro/crate/1.2/context"
_RO_CRATE_SPEC_URL = "https://w3id.org/ro/crate/1.2"
_PROV_SPEC_URL = "https://www.w3.org/TR/prov-overview/"
_RO_CRATE_METADATA_FILENAME = "ro-crate-metadata.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def expected_provenance_export_paths(layout: RunLayout) -> list[str]:
    return [
        (layout.relative_run_dir / stable_artifact_name("provenance")).as_posix(),
        (layout.relative_run_dir / stable_artifact_name("ro_crate") / _RO_CRATE_METADATA_FILENAME).as_posix(),
    ]


def materialize_provenance_bundle(
    *,
    base_dir: Path,
    layout: RunLayout,
    run_document: WorkflowRun,
    workflow_version: str | None = None,
) -> list[str]:
    exported_at = _utcnow()
    export_paths = expected_provenance_export_paths(layout)
    provenance_relpath = PurePosixPath(stable_artifact_name("provenance"))
    ro_crate_relpath = PurePosixPath(stable_artifact_name("ro_crate")) / _RO_CRATE_METADATA_FILENAME

    content_hashes = _load_content_hashes(layout)
    run_ref = ArtifactReference(
        artifact_type="workflow_run",
        path=layout.run_record_relpath.as_posix(),
        id=run_document.id,
        run_id=run_document.run_id,
    )
    content_hash_ref = ArtifactReference(
        artifact_type="content_hash_manifest",
        path=layout.content_hash_manifest_relpath.as_posix(),
        id=normalize_identifier(f"content-hashes-{layout.workflow}-{layout.run_id.lower()}"),
        run_id=layout.run_id,
    )

    all_refs = _collect_references(run_document, run_ref=run_ref, content_hash_ref=content_hash_ref)
    entity_payloads, entity_agents = _build_entity_payloads(
        base_dir=base_dir,
        layout=layout,
        refs=all_refs,
        content_hashes=content_hashes,
    )
    agents, tool_versions, artifact_agents = _build_agent_payloads(
        base_dir=base_dir,
        refs=all_refs,
        workflow_engine=run_document.engine,
    )
    entity_ids_by_path = {
        payload["path"]: entity_id
        for entity_id, payload in entity_payloads.items()
        if isinstance(payload.get("path"), str)
    }
    step_agent_ids = _step_agent_ids(
        run_document,
        entity_ids_by_path,
        entity_agents,
        artifact_agents,
        agents,
    )

    workflow_activity_id = normalize_identifier(f"activity-workflow-{layout.workflow}-{layout.run_id.lower()}")
    workflow_generated_ids = [
        entity_ids_by_path[ref.path]
        for ref in [run_ref, *run_document.outputs]
        if ref.path in entity_ids_by_path
    ]
    workflow_used_ids = [
        entity_ids_by_path[ref.path]
        for ref in run_document.inputs
        if ref.path in entity_ids_by_path
    ]
    workflow_start_time = _workflow_start_time(run_document)
    workflow_end_time = _workflow_end_time(run_document)

    activities: dict[str, dict[str, Any]] = {
        workflow_activity_id: {
            "type": "workflow_run",
            "workflow_id": run_document.source_workflow or layout.workflow,
            "workflow_name": run_document.workflow.name,
            "workflow_slug": run_document.workflow.slug,
            "workflow_version": workflow_version,
            "status": run_document.lifecycle_status,
            "started_at": _isoformat_z(workflow_start_time),
            "ended_at": _isoformat_z(workflow_end_time),
            "used_entities": workflow_used_ids,
            "generated_entities": workflow_generated_ids,
            "warnings": list(run_document.warnings),
        }
    }

    used_relations = [
        {"activity": workflow_activity_id, "entity": entity_id}
        for entity_id in workflow_used_ids
    ]
    generated_relations = [
        {"entity": entity_id, "activity": workflow_activity_id}
        for entity_id in workflow_generated_ids
    ]
    associated_relations = [
        {
            "activity": workflow_activity_id,
            "agent": normalize_identifier(f"agent-workflow-engine-{run_document.engine}"),
            "role": "workflow_engine",
        }
    ]

    for record in run_document.steps:
        activity_id = normalize_identifier(f"activity-step-{record.id}-{layout.run_id.lower()}")
        step_used_ids = [
            entity_ids_by_path[ref.path]
            for ref in record.inputs_resolved
            if ref.path in entity_ids_by_path
        ]
        step_generated_ids = [
            entity_ids_by_path[ref.path]
            for ref in record.outputs_produced
            if ref.path in entity_ids_by_path
        ]
        activities[activity_id] = {
            "type": "workflow_step",
            "step_id": record.id,
            "name": record.name,
            "status": record.status,
            "started_at": _isoformat_z(record.start_time or workflow_start_time),
            "ended_at": _isoformat_z(record.end_time or record.start_time or workflow_end_time),
            "used_entities": step_used_ids,
            "generated_entities": step_generated_ids,
            "warnings": list(record.warnings),
            "errors": list(record.errors),
        }
        used_relations.extend({"activity": activity_id, "entity": entity_id} for entity_id in step_used_ids)
        generated_relations.extend(
            {"entity": entity_id, "activity": activity_id}
            for entity_id in step_generated_ids
        )
        for agent_id in sorted(step_agent_ids.get(record.id, set())):
            associated_relations.append(
                {
                    "activity": activity_id,
                    "agent": agent_id,
                    "role": "step_executor",
                }
            )

    provenance_payload = build_artifact_header(
        schema_version=run_document.schema_version,
        artifact_type="provenance",
        run_id=run_document.run_id,
        created_at=exported_at,
        source_workflow=run_document.source_workflow or layout.workflow,
    )
    provenance_payload["id"] = normalize_identifier(f"provenance-{layout.workflow}-{layout.run_id.lower()}")
    provenance_payload["related_artifacts"] = [
        ref.model_dump(mode="json")
        for ref in _dedupe_refs([run_ref, content_hash_ref, *run_document.inputs, *run_document.outputs])
    ]
    provenance_payload["bundle_format"] = {
        "primary_package": "ro_crate",
        "ro_crate_version": "1.2",
        "lineage_model": "prov_compatible",
    }
    provenance_payload["workflow"] = {
        "workflow_id": run_document.source_workflow or layout.workflow,
        "name": run_document.workflow.name,
        "slug": run_document.workflow.slug,
        "version": workflow_version,
        "engine": run_document.engine,
        "run_record_path": layout.run_record_relpath.as_posix(),
        "lifecycle_status": run_document.lifecycle_status,
        "qc_status": run_document.qc_status,
    }
    provenance_payload["terminal_state"] = {
        "lifecycle_status": run_document.lifecycle_status,
        "representation": (
            "Completed runs include persisted inputs, outputs, and step lineage. "
            "Blocked or failed runs keep only the entities and activity records that were materialized on disk "
            "before termination; missing outputs are omitted rather than inferred."
        ),
        "is_partial": run_document.lifecycle_status != "completed",
    }
    provenance_payload["environment"] = run_document.environment.model_dump(mode="json")
    provenance_payload["tool_versions"] = tool_versions
    provenance_payload["exports"] = {
        "provenance_path": export_paths[0],
        "ro_crate_metadata_path": export_paths[1],
        "exported_at": _isoformat_z(exported_at),
    }
    provenance_payload["entity"] = entity_payloads
    provenance_payload["activity"] = activities
    provenance_payload["agent"] = agents
    provenance_payload["used"] = used_relations
    provenance_payload["wasGeneratedBy"] = generated_relations
    provenance_payload["wasAssociatedWith"] = associated_relations
    provenance_payload["conforms_to"] = {
        "ro_crate": _RO_CRATE_SPEC_URL,
        "prov": _PROV_SPEC_URL,
    }

    provenance_target = layout._track_path(resolve_artifact_path(layout.run_dir, provenance_relpath))
    provenance_target.write_text(json.dumps(provenance_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ro_crate_target = layout._track_path(resolve_artifact_path(layout.run_dir, ro_crate_relpath))
    ro_crate_target.parent.mkdir(parents=True, exist_ok=True)
    ro_crate_payload = _build_ro_crate_payload(
        base_dir=base_dir,
        layout=layout,
        run_document=run_document,
        workflow_version=workflow_version,
        exported_at=exported_at,
        entity_payloads=entity_payloads,
        agents=agents,
        step_agent_ids=step_agent_ids,
        workflow_activity_id=workflow_activity_id,
        activities=activities,
    )
    ro_crate_target.write_text(json.dumps(ro_crate_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return export_paths


def _collect_references(
    run_document: WorkflowRun,
    *,
    run_ref: ArtifactReference,
    content_hash_ref: ArtifactReference,
) -> list[ArtifactReference]:
    refs = [run_ref, content_hash_ref, *run_document.inputs, *run_document.outputs, *run_document.related_artifacts]
    for record in run_document.steps:
        refs.extend(record.inputs_resolved)
        refs.extend(record.outputs_produced)
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[ArtifactReference]) -> list[ArtifactReference]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for ref in refs:
        key = (ref.artifact_type, ref.path, ref.id, ref.run_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _workflow_start_time(run_document: WorkflowRun) -> datetime:
    start_times = [record.start_time for record in run_document.steps if record.start_time is not None]
    return min(start_times, default=run_document.created_at)


def _workflow_end_time(run_document: WorkflowRun) -> datetime:
    end_times = [record.end_time for record in run_document.steps if record.end_time is not None]
    return max(end_times, default=run_document.created_at)


def _load_content_hashes(layout: RunLayout) -> dict[str, dict[str, str]]:
    if not layout.content_hash_manifest_path.exists():
        return {}
    payload = json.loads(layout.content_hash_manifest_path.read_text(encoding="utf-8"))
    hashes = payload.get("hashes")
    if not isinstance(hashes, dict):
        return {}
    return {
        str(path): value
        for path, value in hashes.items()
        if isinstance(path, str) and isinstance(value, dict)
    }


def _entity_id(ref: ArtifactReference) -> str:
    base = ref.id or f"{ref.artifact_type}-{ref.path}"
    return normalize_identifier(f"entity-{base}")


def _build_entity_payloads(
    *,
    base_dir: Path,
    layout: RunLayout,
    refs: list[ArtifactReference],
    content_hashes: dict[str, dict[str, str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    role_map = {ref.path: set() for ref in refs}
    doc_cache: dict[str, Any | None] = {}
    for ref in refs:
        doc_cache[ref.path] = _load_document_or_none(base_dir, ref.path)

    entities: dict[str, dict[str, Any]] = {}
    entity_agents: dict[str, set[str]] = {}
    for ref in refs:
        entity_id = _entity_id(ref)
        role_map[ref.path].add(ref.artifact_type)
        if ref.path == layout.run_record_relpath.as_posix():
            role_map[ref.path].add("run_record")
        if ref.path == layout.content_hash_manifest_relpath.as_posix():
            role_map[ref.path].add("content_hash_manifest")

        hash_payload = _hash_payload_for_ref(
            base_dir=base_dir,
            layout=layout,
            ref=ref,
            content_hashes=content_hashes,
        )
        document = doc_cache[ref.path]
        source_workflow = getattr(document, "source_workflow", None) if document is not None else None
        source_tool = getattr(document, "source_tool", None) if document is not None else None
        source_agent = getattr(document, "source_agent", None) if document is not None else None
        entity_agents[entity_id] = set()
        if isinstance(source_tool, str) and source_tool.strip():
            entity_agents[entity_id].add(normalize_identifier(f"agent-source-tool-{source_tool}"))
        if isinstance(source_agent, str) and source_agent.strip():
            entity_agents[entity_id].add(normalize_identifier(f"agent-source-agent-{source_agent}"))

        entities[entity_id] = {
            "artifact_type": ref.artifact_type,
            "path": ref.path,
            "artifact_id": ref.id,
            "run_id": ref.run_id,
            "roles": sorted(role_map[ref.path]),
            "hash": hash_payload,
            "source_workflow": source_workflow,
            "source_tool": source_tool,
            "source_agent": source_agent,
        }
    return entities, entity_agents


def _hash_payload_for_ref(
    *,
    base_dir: Path,
    layout: RunLayout,
    ref: ArtifactReference,
    content_hashes: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    if ref.path == layout.content_hash_manifest_relpath.as_posix():
        # content_hashes.json includes the final provenance files, so exporting a digest for the
        # manifest itself would create an unresolvable cycle and immediately go stale.
        return None
    try:
        absolute_path = resolve_artifact_path(base_dir, ref.path)
    except Exception:
        return None
    if not absolute_path.exists() or not absolute_path.is_file():
        return None

    try:
        run_relative = absolute_path.relative_to(layout.run_dir).as_posix()
    except ValueError:
        run_relative = None
    if run_relative is not None and run_relative in content_hashes:
        payload = content_hashes[run_relative]
        algorithm = payload.get("algorithm")
        digest = payload.get("digest")
        if isinstance(algorithm, str) and isinstance(digest, str):
            return {"algorithm": algorithm, "digest": digest}
    return {
        "algorithm": "sha256",
        "digest": compute_content_hash(absolute_path.read_bytes()),
    }


def _load_document_or_none(base_dir: Path, path: str) -> Any | None:
    suffix = Path(path).suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        return None
    try:
        return load_artifact_document(base_dir / path)
    except Exception:
        return None


def _build_agent_payloads(
    *,
    base_dir: Path,
    refs: list[ArtifactReference],
    workflow_engine: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, set[str]]]:
    agents: dict[str, dict[str, Any]] = {
        normalize_identifier(f"agent-workflow-engine-{workflow_engine}"): {
            "type": "software",
            "name": workflow_engine,
        }
    }
    tool_versions: list[dict[str, Any]] = []
    artifact_agents: dict[str, set[str]] = {}
    seen_versions: set[tuple[str, str | None]] = set()
    seen_source_agents: set[str] = set()

    for ref in refs:
        artifact_agents.setdefault(ref.path, set())
        document = _load_document_or_none(base_dir, ref.path)
        if document is None:
            continue

        tool_name = getattr(document, "tool_name", None)
        tool_version = getattr(document, "tool_version", None)
        if isinstance(tool_name, str) and tool_name.strip():
            agent_id = normalize_identifier(
                f"agent-tool-{tool_name}-{tool_version}" if isinstance(tool_version, str) else f"agent-tool-{tool_name}"
            )
            if agent_id not in agents:
                agents[agent_id] = {
                    "type": "software",
                    "name": tool_name,
                    "version": tool_version if isinstance(tool_version, str) and tool_version.strip() else None,
                }
            artifact_agents[ref.path].add(agent_id)
            key = (tool_name, tool_version if isinstance(tool_version, str) and tool_version.strip() else None)
            if key not in seen_versions:
                seen_versions.add(key)
                tool_versions.append(
                    {
                        "name": tool_name,
                        "version": key[1],
                        "agent_id": agent_id,
                        "source_artifact_path": ref.path,
                    }
                )

        engine_name = getattr(document, "engine_name", None)
        engine_version = getattr(document, "engine_version", None)
        if isinstance(engine_name, str) and engine_name.strip():
            agent_id = normalize_identifier(
                f"agent-engine-{engine_name}-{engine_version}"
                if isinstance(engine_version, str)
                else f"agent-engine-{engine_name}"
            )
            if agent_id not in agents:
                agents[agent_id] = {
                    "type": "software",
                    "name": engine_name,
                    "version": engine_version if isinstance(engine_version, str) and engine_version.strip() else None,
                }
            artifact_agents[ref.path].add(agent_id)
            key = (engine_name, engine_version if isinstance(engine_version, str) and engine_version.strip() else None)
            if key not in seen_versions:
                seen_versions.add(key)
                tool_versions.append(
                    {
                        "name": engine_name,
                        "version": key[1],
                        "agent_id": agent_id,
                        "source_artifact_path": ref.path,
                    }
                )

        source_tool = getattr(document, "source_tool", None)
        if isinstance(source_tool, str) and source_tool.strip():
            agent_id = normalize_identifier(f"agent-source-tool-{source_tool}")
            agents.setdefault(agent_id, {"type": "software", "name": source_tool})
            artifact_agents[ref.path].add(agent_id)
        source_agent = getattr(document, "source_agent", None)
        if isinstance(source_agent, str) and source_agent.strip():
            agent_id = normalize_identifier(f"agent-source-agent-{source_agent}")
            if agent_id not in seen_source_agents:
                seen_source_agents.add(agent_id)
                agents.setdefault(agent_id, {"type": "software", "name": source_agent})
            artifact_agents[ref.path].add(agent_id)

    return agents, tool_versions, artifact_agents


def _step_agent_ids(
    run_document: WorkflowRun,
    entity_ids_by_path: dict[str, str],
    entity_agents: dict[str, set[str]],
    artifact_agents: dict[str, set[str]],
    agents: dict[str, dict[str, Any]],
) -> dict[str, set[str]]:
    default_agent_id = normalize_identifier(f"agent-workflow-engine-{run_document.engine}")
    step_agents: dict[str, set[str]] = {}
    for record in run_document.steps:
        associated: set[str] = set()
        for ref in record.outputs_produced:
            entity_id = entity_ids_by_path.get(ref.path)
            if entity_id is None:
                continue
            associated.update(entity_agents.get(entity_id, set()))
            associated.update(artifact_agents.get(ref.path, set()))

        step_agents[record.id] = {agent_id for agent_id in associated if agent_id in agents} or {default_agent_id}
    return step_agents


def _build_ro_crate_payload(
    *,
    base_dir: Path,
    layout: RunLayout,
    run_document: WorkflowRun,
    workflow_version: str | None,
    exported_at: datetime,
    entity_payloads: dict[str, dict[str, Any]],
    agents: dict[str, dict[str, Any]],
    step_agent_ids: dict[str, set[str]],
    workflow_activity_id: str,
    activities: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ro_crate_dir = layout.run_dir / stable_artifact_name("ro_crate")
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "../"},
            "conformsTo": {"@id": _RO_CRATE_SPEC_URL},
        }
    ]

    has_part: list[dict[str, str]] = []
    mentions: list[dict[str, str]] = []
    file_ids: set[str] = set()

    for entity_id, entity in entity_payloads.items():
        path = entity.get("path")
        if not isinstance(path, str):
            continue
        file_id = _ro_crate_id_for_path(base_dir=base_dir, ro_crate_dir=ro_crate_dir, path=path)
        if file_id in file_ids:
            continue
        file_ids.add(file_id)
        entry: dict[str, Any] = {
            "@id": file_id,
            "@type": "File",
            "name": Path(path).name,
            "encodingFormat": _encoding_format(path),
            "identifier": entity_id,
            "description": f"{entity.get('artifact_type', 'artifact')} ({', '.join(entity.get('roles', []))})",
        }
        hash_payload = entity.get("hash")
        if isinstance(hash_payload, dict) and isinstance(hash_payload.get("digest"), str):
            entry["sha256"] = hash_payload["digest"]
        graph.append(entry)

        absolute_path = resolve_artifact_path(base_dir, path)
        try:
            absolute_path.relative_to(layout.run_dir)
        except ValueError:
            mentions.append({"@id": file_id})
        else:
            has_part.append({"@id": file_id})

    for agent_id, agent in agents.items():
        agent_entry: dict[str, Any] = {
            "@id": f"#{agent_id}",
            "@type": "SoftwareApplication",
            "name": agent["name"],
        }
        if isinstance(agent.get("version"), str) and agent["version"]:
            agent_entry["version"] = agent["version"]
        graph.append(agent_entry)

    prov_id = "../prov.json"
    prov_path = layout.run_dir / stable_artifact_name("provenance")
    if prov_path.exists() and prov_path.is_file():
        graph.append(
            {
                "@id": prov_id,
                "@type": "File",
                "name": prov_path.name,
                "encodingFormat": "application/json",
                "sha256": compute_content_hash(prov_path.read_bytes()),
                "description": "PROV-compatible lineage export for this workflow run.",
            }
        )
        has_part.append({"@id": prov_id})

    workflow_activity = activities[workflow_activity_id]
    graph.append(
        {
            "@id": f"#{workflow_activity_id}",
            "@type": "CreateAction",
            "name": f"{run_document.workflow.name} workflow execution",
            "instrument": [{"@id": f"#{normalize_identifier(f'agent-workflow-engine-{run_document.engine}')}" }],
            "object": [
                {"@id": _ro_crate_id_for_path(base_dir=base_dir, ro_crate_dir=ro_crate_dir, path=ref.path)}
                for ref in run_document.inputs
            ],
            "result": [
                {"@id": _ro_crate_id_for_path(base_dir=base_dir, ro_crate_dir=ro_crate_dir, path=ref.path)}
                for ref in run_document.outputs
            ],
            "startTime": workflow_activity["started_at"],
            "endTime": workflow_activity["ended_at"],
            "actionStatus": _schema_action_status(run_document.lifecycle_status),
        }
    )

    for record in run_document.steps:
        activity_id = normalize_identifier(f"activity-step-{record.id}-{layout.run_id.lower()}")
        step_activity = activities[activity_id]
        graph.append(
            {
                "@id": f"#{activity_id}",
                "@type": "CreateAction",
                "name": record.name,
                "instrument": [{"@id": f"#{agent_id}"} for agent_id in sorted(step_agent_ids.get(record.id, set()))],
                "object": [
                    {"@id": _ro_crate_id_for_path(base_dir=base_dir, ro_crate_dir=ro_crate_dir, path=ref.path)}
                    for ref in record.inputs_resolved
                ],
                "result": [
                    {"@id": _ro_crate_id_for_path(base_dir=base_dir, ro_crate_dir=ro_crate_dir, path=ref.path)}
                    for ref in record.outputs_produced
                ],
                "startTime": step_activity["started_at"],
                "endTime": step_activity["ended_at"],
                "actionStatus": _schema_action_status(record.status),
            }
        )

    root_dataset: dict[str, Any] = {
        "@id": "../",
        "@type": "Dataset",
        "name": f"{run_document.workflow.name} provenance bundle",
        "description": (
            f"Portable RO-Crate export for workflow run {run_document.run_id} "
            f"with {run_document.lifecycle_status} lifecycle status."
        ),
        "dateCreated": _isoformat_z(run_document.created_at),
        "dateModified": _isoformat_z(exported_at),
        "conformsTo": [{"@id": _RO_CRATE_SPEC_URL}, {"@id": _PROV_SPEC_URL}],
        "hasPart": has_part,
        "mentions": mentions,
        "mainEntity": {"@id": "../prov.json"},
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "workflow_id", "value": run_document.source_workflow or layout.workflow},
            {"@type": "PropertyValue", "name": "workflow_version", "value": workflow_version or "unknown"},
            {"@type": "PropertyValue", "name": "workflow_engine", "value": run_document.engine},
            {"@type": "PropertyValue", "name": "run_id", "value": run_document.run_id},
            {"@type": "PropertyValue", "name": "lifecycle_status", "value": run_document.lifecycle_status},
            {"@type": "PropertyValue", "name": "qc_status", "value": run_document.qc_status},
            {"@type": "PropertyValue", "name": "conda_env", "value": run_document.environment.conda_env or "unknown"},
            {"@type": "PropertyValue", "name": "python_version", "value": run_document.environment.python_version or "unknown"},
            {"@type": "PropertyValue", "name": "platform", "value": run_document.environment.platform or "unknown"},
            {"@type": "PropertyValue", "name": "hostname", "value": run_document.environment.hostname or "unknown"},
        ],
    }
    graph.append(root_dataset)

    return {
        "@context": [_RO_CRATE_CONTEXT_URL],
        "@graph": graph,
    }


def _ro_crate_id_for_path(*, base_dir: Path, ro_crate_dir: Path, path: str) -> str:
    absolute_path = resolve_artifact_path(base_dir, path)
    relative = os.path.relpath(absolute_path, start=ro_crate_dir)
    return PurePosixPath(relative).as_posix()


def _encoding_format(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".json": "application/json",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".tsv": "text/tab-separated-values",
        ".csv": "text/csv",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
    }.get(suffix, "application/octet-stream")


def _schema_action_status(status: str) -> str:
    return {
        "completed": "CompletedActionStatus",
        "failed": "FailedActionStatus",
        "running": "ActiveActionStatus",
        "blocked": "PotentialActionStatus",
        "created": "PotentialActionStatus",
        "waiting": "PotentialActionStatus",
        "preflight_checked": "PotentialActionStatus",
    }.get(status, "PotentialActionStatus")
