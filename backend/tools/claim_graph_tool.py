"""Agent tool for deterministic claim-graph materialization.

Selection rule vs ``evidence_review`` (issue #126): ``claim_graph`` aggregates
claims across many evidence cards, evidence reviews, and workflow runs into a
multi-artifact graph with conservative contradiction edges. It is NOT a
drop-in substitute for ``evidence_review`` — if the task is answering a
single biology question over a curated evidence set, use ``evidence_review``
instead. ``ClaimGraphTool`` is intentionally NOT registered in the runtime
tool catalog (see ``tools/__init__.py._instantiate_all_tools`` and the
``test_runtime_tool_catalog_excludes_legacy_workflow_tools`` health check);
it is kept as a library entry point callable via
``evidence.run_claim_graph`` and via this tool class in tests / scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from evidence import ClaimGraphInput, run_claim_graph
from hardening import is_secret_like_path

from .contracts import (
    artifact_ref,
    blocked_result,
    execution_error_result,
    invalid_input_result,
    success_result,
)


class ClaimGraphTool(BaseTool):
    name: str = "claim_graph"
    description: str = (
        "Build a durable BioAPEX claim graph from evidence_card, evidence_review, "
        "and workflow_run artifacts. Use for multi-artifact claim aggregation with "
        "contradiction detection — NOT for single-question literature synthesis "
        "(use evidence_review for that). This tool is not registered in the "
        "runtime tool catalog; it is exposed as a library entry point. "
        "The graph keeps claim text separate from relationship edges, records "
        "provenance for both literature-backed and workflow-backed claims, links "
        "grounded entities, and adds conservative contradiction edges when obvious "
        "conflicts are detected."
    )
    args_schema: Type[BaseModel] = ClaimGraphInput
    response_format: str = "content_and_artifact"
    base_dir: str = ""

    def _run(
        self,
        evidence_card_paths: list[str] | None = None,
        evidence_review_paths: list[str] | None = None,
        entity_grounding_paths: list[str] | None = None,
        workflow_run_paths: list[str] | None = None,
        include_related_artifacts: bool = True,
    ) -> tuple[str, dict]:
        for field_name, candidates in (
            ("evidence_card_paths", evidence_card_paths or []),
            ("evidence_review_paths", evidence_review_paths or []),
            ("entity_grounding_paths", entity_grounding_paths or []),
            ("workflow_run_paths", workflow_run_paths or []),
        ):
            for candidate in candidates:
                if is_secret_like_path(candidate):
                    return blocked_result(
                        self.name,
                        "Reading credential / secret files is not allowed.",
                        metadata={"blocked_field": field_name, "blocked_path": candidate},
                    )
        try:
            payload = ClaimGraphInput(
                evidence_card_paths=evidence_card_paths or [],
                evidence_review_paths=evidence_review_paths or [],
                entity_grounding_paths=entity_grounding_paths or [],
                workflow_run_paths=workflow_run_paths or [],
                include_related_artifacts=include_related_artifacts,
            )
        except Exception as exc:
            return invalid_input_result(self.name, str(exc))

        try:
            result = run_claim_graph(Path(self.base_dir or ".").resolve(), payload)
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

        graph = result.graph
        structured_payload = {
            "artifact_path": result.artifact_relpath,
            "contradiction_rule_set": graph.contradiction_rule_set,
            "source_artifacts": [ref.model_dump(mode="json") for ref in graph.source_artifacts],
            "summary": graph.summary.model_dump(mode="json"),
            "claim_nodes": [
                {
                    "node_id": node.node_id,
                    "statement": node.statement,
                    "confidence": node.confidence,
                    "status": node.status,
                }
                for node in graph.claim_nodes
            ],
            "contradictions": [
                edge.model_dump(mode="json")
                for edge in graph.edges
                if edge.edge_type == "contradicts"
            ],
        }
        metadata = {
            "artifact_path": result.artifact_relpath,
            "claim_count": graph.summary.claim_count,
            "evidence_card_count": graph.summary.evidence_card_count,
            "entity_count": graph.summary.entity_count,
            "workflow_result_count": graph.summary.workflow_result_count,
            "edge_count": graph.summary.edge_count,
            "contradiction_count": graph.summary.contradiction_count,
        }
        refs = [
            artifact_ref(
                path=str(result.artifact_path),
                label="claim_graph",
                artifact_type="claim_graph",
                identifier=graph.id,
            )
        ]
        for ref in graph.source_artifacts:
            refs.append(
                artifact_ref(
                    path=ref.path,
                    label=ref.artifact_type,
                    artifact_type=ref.artifact_type,
                    identifier=ref.id,
                )
            )

        warnings: list[str] = []
        if graph.summary.contradiction_count:
            warnings.append("contradictions_detected")

        summary = (
            f"Built claim graph with {graph.summary.claim_count} claim node(s), "
            f"{graph.summary.evidence_card_count} evidence card node(s), "
            f"{graph.summary.workflow_result_count} workflow result node(s), and "
            f"{graph.summary.contradiction_count} contradiction edge(s)."
        )
        return success_result(
            self.name,
            summary,
            structured_payload=structured_payload,
            artifact_refs=refs,
            warnings=warnings,
            metadata=metadata,
        )
