"""Session-scoped file workspace summaries for the Files browser."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from artifacts.registry import ArtifactRegistry, ArtifactRegistryRecord
from graph.session_manager import SessionManager


@dataclass(frozen=True)
class FilesWorkspaceItem:
    path: str
    name: str
    artifact_type: str | None
    workflow: str | None
    run_id: str | None
    source_tool: str | None
    step_label: str | None
    output_name: str | None
    size_bytes: int | None
    materialized_at: float | None


@dataclass
class _ObservedArtifact:
    path: str
    artifact_type: str | None
    workflow: str | None
    run_id: str | None
    source_tool: str | None
    step_label: str | None
    output_name: str | None
    last_seen_order: int


@dataclass(frozen=True)
class _RunContext:
    workflow: str | None
    run_id: str | None


def list_session_files_workspace_items(
    *,
    base_dir: str | Path,
    session_manager: SessionManager,
    session_id: str,
) -> list[dict[str, Any]]:
    resolved_base_dir = Path(base_dir).resolve()
    messages = session_manager.load_session(session_id)
    registry_records = _registry_records_by_path(resolved_base_dir)
    run_context = _latest_workflow_run_context(messages)
    observed = _collect_session_artifacts(messages, run_context=run_context)

    items: list[FilesWorkspaceItem] = []
    for artifact in observed.values():
        target = resolved_base_dir / artifact.path
        if not target.is_file():
            continue

        record = registry_records.get(artifact.path)
        materialized_at = _materialized_timestamp(target, record)
        items.append(
            FilesWorkspaceItem(
                path=artifact.path,
                name=target.name,
                artifact_type=artifact.artifact_type or (record.artifact_type if record is not None else None),
                workflow=(record.workflow if record is not None else None) or artifact.workflow,
                run_id=(record.run_id if record is not None else None) or artifact.run_id,
                source_tool=artifact.source_tool or (record.source_tool if record is not None else None),
                step_label=artifact.step_label,
                output_name=artifact.output_name,
                size_bytes=target.stat().st_size,
                materialized_at=materialized_at,
            )
        )

    ordered = sorted(
        items,
        key=lambda item: (
            item.materialized_at is not None,
            item.materialized_at or 0.0,
            observed[item.path].last_seen_order,
            item.path,
        ),
        reverse=True,
    )
    return [asdict(item) for item in ordered]


def _registry_records_by_path(base_dir: Path) -> dict[str, ArtifactRegistryRecord]:
    snapshot = ArtifactRegistry(base_dir).ensure_snapshot()
    by_path: dict[str, ArtifactRegistryRecord] = {}
    for record in snapshot.records:
        existing = by_path.get(record.path)
        if existing is None or (existing.status != "valid" and record.status == "valid"):
            by_path[record.path] = record
    return by_path


def _collect_session_artifacts(
    messages: list[dict[str, Any]],
    *,
    run_context: _RunContext | None,
) -> dict[str, _ObservedArtifact]:
    observed: dict[str, _ObservedArtifact] = {}
    order = 0

    def observe(
        *,
        path: str | None,
        artifact_type: str | None = None,
        workflow: str | None = None,
        run_id: str | None = None,
        source_tool: str | None = None,
        step_label: str | None = None,
        output_name: str | None = None,
    ) -> None:
        nonlocal order

        normalized_path = _clean_path(path)
        if normalized_path is None or not normalized_path.startswith("artifacts/"):
            return

        existing = observed.get(normalized_path)
        observed[normalized_path] = _ObservedArtifact(
            path=normalized_path,
            artifact_type=artifact_type or (existing.artifact_type if existing is not None else None),
            workflow=workflow or (existing.workflow if existing is not None else None),
            run_id=run_id or (existing.run_id if existing is not None else None),
            source_tool=source_tool or (existing.source_tool if existing is not None else None),
            step_label=step_label or (existing.step_label if existing is not None else None),
            output_name=output_name or (existing.output_name if existing is not None else None),
            last_seen_order=order,
        )
        order += 1

    for message in messages:
        workflow_events = message.get("workflow_events")
        if isinstance(workflow_events, list):
            for event in workflow_events:
                if not isinstance(event, Mapping):
                    continue

                event_type = _clean_text(event.get("type"))
                if event_type == "workflow_artifact":
                    if _clean_text(event.get("scope")) == "run_record":
                        continue

                    if not _event_matches_run_context(event, run_context):
                        continue

                    artifact = event.get("artifact")
                    if not isinstance(artifact, Mapping):
                        continue

                    observe(
                        path=_clean_text(artifact.get("path")),
                        artifact_type=_clean_text(artifact.get("artifact_type")),
                        workflow=_clean_text(event.get("workflow_id")),
                        run_id=_clean_text(event.get("run_id")) or _clean_text(artifact.get("run_id")),
                        step_label=_clean_text(event.get("step_label")),
                        output_name=_clean_text(event.get("output_name")),
                    )
                    continue

                if event_type != "workflow_step_end":
                    continue

                if not _event_matches_run_context(event, run_context):
                    continue

                artifact_refs = event.get("artifact_refs")
                if not isinstance(artifact_refs, list):
                    continue

                for artifact_ref in artifact_refs:
                    if not isinstance(artifact_ref, Mapping):
                        continue
                    observe(
                        path=_clean_text(artifact_ref.get("path")),
                        artifact_type=_clean_text(artifact_ref.get("artifact_type")),
                        workflow=_clean_text(event.get("workflow_id")),
                        run_id=_clean_text(event.get("run_id")) or _clean_text(artifact_ref.get("run_id")),
                        step_label=_clean_text(event.get("step_label")),
                    )

        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue

        for tool_call in tool_calls:
            if not isinstance(tool_call, Mapping):
                continue

            result = tool_call.get("result")
            if not isinstance(result, Mapping):
                continue

            artifact_refs = result.get("artifact_refs")
            if not isinstance(artifact_refs, list):
                continue

            source_tool = _clean_text(result.get("tool_name")) or _clean_text(tool_call.get("tool"))
            call_run_id = _clean_text(tool_call.get("run_id"))

            for artifact_ref in artifact_refs:
                if not isinstance(artifact_ref, Mapping):
                    continue

                artifact_path = _clean_text(artifact_ref.get("path"))
                artifact_run_id = _clean_text(artifact_ref.get("run_id")) or call_run_id
                if not _artifact_matches_run_context(
                    path=artifact_path,
                    run_id=artifact_run_id,
                    run_context=run_context,
                ):
                    continue

                observe(
                    path=artifact_path,
                    artifact_type=_clean_text(artifact_ref.get("artifact_type")),
                    run_id=artifact_run_id,
                    source_tool=source_tool,
                )

    return observed


def _latest_workflow_run_context(messages: list[dict[str, Any]]) -> _RunContext | None:
    latest_workflow_id: str | None = None
    latest_run_id: str | None = None

    for message in messages:
        workflow_events = message.get("workflow_events")
        if not isinstance(workflow_events, list):
            continue

        for event in workflow_events:
            if not isinstance(event, Mapping):
                continue

            event_run_id = _clean_text(event.get("run_id"))
            if event_run_id is None:
                continue

            latest_run_id = event_run_id
            latest_workflow_id = _clean_text(event.get("workflow_id"))

    if latest_run_id is None:
        return None

    return _RunContext(
        workflow=latest_workflow_id,
        run_id=latest_run_id,
    )


def _event_matches_run_context(
    event: Mapping[str, Any],
    run_context: _RunContext | None,
) -> bool:
    if run_context is None or run_context.run_id is None:
        return True

    event_run_id = _clean_text(event.get("run_id"))
    if event_run_id != run_context.run_id:
        return False

    if run_context.workflow is None:
        return True

    return _clean_text(event.get("workflow_id")) == run_context.workflow


def _artifact_matches_run_context(
    *,
    path: str | None,
    run_id: str | None,
    run_context: _RunContext | None,
) -> bool:
    if run_context is None or run_context.run_id is None:
        return True

    if run_id == run_context.run_id:
        return True

    artifact_context = _artifact_path_context(path)
    if artifact_context is None or artifact_context.run_id != run_context.run_id:
        return False

    if run_context.workflow is None:
        return True

    return artifact_context.workflow == run_context.workflow


def _artifact_path_context(path: str | None) -> _RunContext | None:
    normalized_path = _clean_path(path)
    if normalized_path is None:
        return None

    parts = normalized_path.split("/")
    if len(parts) < 4 or parts[0] != "artifacts":
        return None

    return _RunContext(
        workflow=parts[1] or None,
        run_id=parts[3] or None,
    )


def _materialized_timestamp(
    target: Path,
    record: ArtifactRegistryRecord | None,
) -> float:
    if record is not None and record.created_at is not None:
        return record.created_at.timestamp()
    return target.stat().st_mtime


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_path(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return cleaned.lstrip("/").removeprefix("./")
