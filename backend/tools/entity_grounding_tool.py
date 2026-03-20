"""Agent tool for durable biological entity grounding."""

from __future__ import annotations

from pathlib import Path
from typing import Type

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from entity_grounding import EntityGroundingInput, run_entity_grounding

from .contracts import (
    artifact_ref,
    empty_result,
    execution_error_result,
    invalid_input_result,
    retriable_error_result,
    success_result,
)


class EntityGroundingTool(BaseTool):
    name: str = "entity_grounding"
    description: str = (
        "Ground gene, protein, or transcript mentions to stable identifiers using "
        "the repo's Ensembl and UniProt integrations. Persists a durable "
        "entity_grounding artifact plus cached source payloads."
    )
    args_schema: Type[BaseModel] = EntityGroundingInput
    response_format: str = "content_and_artifact"
    base_dir: str = ""

    def _run(
        self,
        mentions: list[str],
        species: str | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[str, dict]:
        try:
            payload = EntityGroundingInput(
                mentions=mentions,
                species=species,
                entity_types=entity_types or ["gene"],
            )
        except Exception as exc:
            return invalid_input_result(self.name, str(exc))

        try:
            grounded = run_entity_grounding(Path(self.base_dir or ".").resolve(), payload)
        except httpx.TimeoutException:
            return retriable_error_result(self.name, "Entity grounding timed out.")
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            message = f"HTTP {status_code}: {exc.response.reason_phrase}"
            metadata = {"http_status": status_code, "request_url": str(exc.request.url)}
            if status_code == 429 or status_code >= 500:
                return retriable_error_result(self.name, message, metadata=metadata)
            if 400 <= status_code < 500:
                return invalid_input_result(self.name, message, metadata=metadata)
            return execution_error_result(self.name, message, metadata=metadata)
        except httpx.RequestError as exc:
            return retriable_error_result(
                self.name,
                f"Entity grounding failed: {exc}",
                metadata={"request_url": str(exc.request.url) if exc.request is not None else None},
            )
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

        resolved_count = sum(1 for result in grounded.artifact.results if result.status == "resolved")
        ambiguous_count = sum(1 for result in grounded.artifact.results if result.status == "ambiguous")
        unresolved_count = sum(1 for result in grounded.artifact.results if result.status == "unresolved")
        requires_clarification = grounded.artifact.requires_clarification

        structured_payload = {
            "artifact_path": grounded.artifact_relpath,
            "run_id": grounded.artifact.run_id,
            "input_mentions": grounded.artifact.input_mentions,
            "requested_species": grounded.artifact.requested_species,
            "requested_entity_types": grounded.artifact.requested_entity_types,
            "requires_clarification": requires_clarification,
            "resolved_entities": [
                entity.model_dump(mode="json") for entity in grounded.resolved_entities
            ],
            "results": [result.model_dump(mode="json") for result in grounded.artifact.results],
            "cached_payload_paths": [payload.relpath for payload in grounded.cached_payloads],
        }
        metadata = {
            "mention_count": len(grounded.artifact.input_mentions),
            "resolved_count": resolved_count,
            "ambiguous_count": ambiguous_count,
            "unresolved_count": unresolved_count,
            "requires_clarification": requires_clarification,
        }
        warnings: list[str] = []
        if ambiguous_count:
            warnings.append("ambiguous_matches")
        if unresolved_count:
            warnings.append("unresolved_mentions")
        refs = [
            artifact_ref(
                path=str(grounded.artifact_path),
                label="entity_grounding",
                artifact_type="entity_grounding",
                identifier=grounded.artifact.id,
            )
        ]
        refs.extend(
            artifact_ref(
                path=str(payload.path),
                label="grounding_source_payload",
                artifact_type="generated_output",
                identifier=grounded.artifact.run_id,
            )
            for payload in grounded.cached_payloads
        )
        if resolved_count == 0 and requires_clarification:
            summary = (
                f"Grounding requires clarification for {ambiguous_count} of "
                f"{len(grounded.artifact.input_mentions)} mention(s)."
            )
            return empty_result(
                self.name,
                summary,
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings,
                metadata=metadata,
            )
        if resolved_count == 0:
            summary = (
                f"No resolved entities were grounded from "
                f"{len(grounded.artifact.input_mentions)} mention(s)."
            )
            return empty_result(
                self.name,
                summary,
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings,
                metadata=metadata,
            )

        summary = (
            f"Grounded {resolved_count} of {len(grounded.artifact.input_mentions)} mention(s); "
            f"{ambiguous_count} ambiguous, {unresolved_count} unresolved."
        )
        return success_result(
            self.name,
            summary,
            structured_payload=structured_payload,
            artifact_refs=refs,
            warnings=warnings,
            metadata=metadata,
        )
