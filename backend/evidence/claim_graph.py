"""Deterministic claim-graph materialization from durable BioAPEX artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artifacts import (
    ArtifactReference,
    ClaimGraphArtifact,
    SCHEMA_PACK_VERSION,
    build_content_hash_manifest,
    load_artifact_document,
    normalize_identifier,
    prepare_run_directory,
    resolve_artifact_path,
)
from artifacts.schemas import (
    ClaimGraphClaimNode,
    ClaimGraphClaimProvenance,
    ClaimGraphEdge,
    ClaimGraphEntityNode,
    ClaimGraphEvidenceCardNode,
    ClaimGraphSummary,
    ClaimGraphWorkflowResultNode,
    EvidenceCard,
    EvidenceReviewArtifact,
    EntityGroundingArtifact,
    WorkflowRun,
)
from artifacts.naming import is_valid_run_id

CLAIM_GRAPH_WORKFLOW_NAME = "claim-graph"
CLAIM_GRAPH_CONTRADICTION_RULE_SET = "claim_graph_contradiction_v1"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_POSITIVE_CUES = {
    "activate",
    "activated",
    "activates",
    "associated",
    "association",
    "elevated",
    "higher",
    "increase",
    "increased",
    "increases",
    "induce",
    "induced",
    "induces",
    "maintain",
    "maintained",
    "maintains",
    "preserve",
    "preserved",
    "preserves",
    "promote",
    "promoted",
    "promotes",
    "shared",
    "support",
    "supported",
    "supports",
    "upregulate",
    "upregulated",
    "upregulates",
}
_NEGATIVE_CUES = {
    "absence",
    "absent",
    "contradict",
    "contradicted",
    "contradicts",
    "decrease",
    "decreased",
    "decreases",
    "didnt",
    "downregulate",
    "downregulated",
    "downregulates",
    "fail",
    "failed",
    "fails",
    "inhibit",
    "inhibited",
    "inhibits",
    "lack",
    "lacked",
    "lacks",
    "loss",
    "lower",
    "lowered",
    "lowers",
    "no",
    "not",
    "reduce",
    "reduced",
    "reduces",
    "suppress",
    "suppressed",
    "suppresses",
    "without",
}
_NEGATION_OVERRIDE_CUES = {"didnt", "no", "not", "without"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "with",
}


def _normalize_relative_path(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Paths must not be empty.")
    if "\\" in raw:
        raise ValueError("Paths must use forward slashes.")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise ValueError("Paths must be relative, not absolute.")
    if candidate.parts == (".",):
        raise ValueError("Paths must not resolve to '.'.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Paths must not contain '..'.")
    return str(candidate)


def _dedupe_paths(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_relative_path(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


class ClaimGraphInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_card_paths: list[str] = Field(default_factory=list)
    evidence_review_paths: list[str] = Field(default_factory=list)
    entity_grounding_paths: list[str] = Field(default_factory=list)
    workflow_run_paths: list[str] = Field(default_factory=list)
    include_related_artifacts: bool = True

    @field_validator(
        "evidence_card_paths",
        "evidence_review_paths",
        "entity_grounding_paths",
        "workflow_run_paths",
    )
    @classmethod
    def _validate_path_lists(cls, value: list[str]) -> list[str]:
        return _dedupe_paths(value)

    @model_validator(mode="after")
    def _validate_sources(self) -> "ClaimGraphInput":
        if (
            not self.evidence_card_paths
            and not self.evidence_review_paths
            and not self.workflow_run_paths
        ):
            raise ValueError(
                "Provide at least one evidence_card, evidence_review, or workflow_run artifact to build a claim graph."
            )
        return self


@dataclass(frozen=True)
class PersistedClaimGraph:
    graph: ClaimGraphArtifact
    artifact_path: Path
    artifact_relpath: str


@dataclass(frozen=True)
class _LoadedEvidenceCard:
    artifact: EvidenceCard
    artifact_path: Path
    artifact_relpath: str
    artifact_ref: ArtifactReference


@dataclass(frozen=True)
class _LoadedEvidenceReview:
    artifact: EvidenceReviewArtifact
    artifact_path: Path
    artifact_relpath: str
    artifact_ref: ArtifactReference


@dataclass(frozen=True)
class _LoadedEntityGrounding:
    artifact: EntityGroundingArtifact
    artifact_path: Path
    artifact_relpath: str
    artifact_ref: ArtifactReference


@dataclass(frozen=True)
class _LoadedWorkflowResult:
    artifact_path: Path
    artifact_relpath: str
    artifact_ref: ArtifactReference
    artifact_type: str
    label: str
    workflow_name: str | None
    workflow_slug: str | None
    result_status: str | None
    confidence: str | None = None
    summary_claims: tuple["_WorkflowSummaryClaim", ...] = ()


@dataclass(frozen=True)
class _WorkflowSummaryClaim:
    source_identifier: str
    statement: str
    confidence: str
    note: str | None = None


def run_claim_graph(
    base_dir: Path | str,
    payload: ClaimGraphInput,
) -> PersistedClaimGraph:
    base_path = Path(base_dir).resolve()
    inputs = _collect_inputs(base_path, payload)

    graph_payload = _build_claim_graph_payload(inputs)
    layout = prepare_run_directory(base_path, CLAIM_GRAPH_WORKFLOW_NAME)
    graph = ClaimGraphArtifact.model_validate(
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "claim_graph",
            "id": normalize_identifier(f"claim-graph-{layout.run_id}"),
            "run_id": layout.run_id,
            "created_at": layout.created_at,
            "source_workflow": CLAIM_GRAPH_WORKFLOW_NAME,
            "related_artifacts": [
                ref.model_dump(mode="json") for ref in graph_payload["source_artifacts"]
            ],
            "source_artifacts": [
                ref.model_dump(mode="json") for ref in graph_payload["source_artifacts"]
            ],
            "contradiction_rule_set": CLAIM_GRAPH_CONTRADICTION_RULE_SET,
            "claim_nodes": [
                node.model_dump(mode="json") for node in graph_payload["claim_nodes"]
            ],
            "evidence_card_nodes": [
                node.model_dump(mode="json") for node in graph_payload["evidence_card_nodes"]
            ],
            "entity_nodes": [
                node.model_dump(mode="json") for node in graph_payload["entity_nodes"]
            ],
            "workflow_result_nodes": [
                node.model_dump(mode="json") for node in graph_payload["workflow_result_nodes"]
            ],
            "edges": [edge.model_dump(mode="json") for edge in graph_payload["edges"]],
            "summary": graph_payload["summary"].model_dump(mode="json"),
        }
    )

    artifact_path = layout.stable_artifact_path("claim_graph")
    artifact_relpath = layout.stable_artifact_relpath("claim_graph").as_posix()
    artifact_path.write_text(
        json.dumps(graph.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_content_hash_manifest(layout)
    return PersistedClaimGraph(graph=graph, artifact_path=artifact_path, artifact_relpath=artifact_relpath)


def _collect_inputs(base_path: Path, payload: ClaimGraphInput) -> dict[str, Any]:
    evidence_cards: dict[str, _LoadedEvidenceCard] = {}
    evidence_reviews: dict[str, _LoadedEvidenceReview] = {}
    entity_groundings: dict[str, _LoadedEntityGrounding] = {}
    workflow_results: dict[str, _LoadedWorkflowResult] = {}

    pending_cards = list(payload.evidence_card_paths)
    pending_reviews = list(payload.evidence_review_paths)
    pending_groundings = list(payload.entity_grounding_paths)
    pending_workflows = list(payload.workflow_run_paths)

    while pending_cards or pending_reviews or pending_groundings or pending_workflows:
        while pending_cards:
            relpath = pending_cards.pop(0)
            if relpath in evidence_cards:
                continue
            record = _load_evidence_card(base_path, relpath)
            evidence_cards[relpath] = record
            if payload.include_related_artifacts:
                for ref in record.artifact.related_artifacts:
                    if ref.artifact_type == "entity_grounding":
                        pending_groundings.append(ref.path)
                    elif ref.artifact_type == "workflow_run":
                        pending_workflows.append(ref.path)

        while pending_reviews:
            relpath = pending_reviews.pop(0)
            if relpath in evidence_reviews:
                continue
            record = _load_evidence_review(base_path, relpath)
            evidence_reviews[relpath] = record
            if payload.include_related_artifacts:
                for ref in [*record.artifact.evidence_included, *record.artifact.related_artifacts]:
                    if ref.artifact_type == "evidence_card":
                        pending_cards.append(ref.path)
                    elif ref.artifact_type == "entity_grounding":
                        pending_groundings.append(ref.path)
                    elif ref.artifact_type == "workflow_run":
                        pending_workflows.append(ref.path)

        while pending_groundings:
            relpath = pending_groundings.pop(0)
            if relpath in entity_groundings:
                continue
            record = _load_entity_grounding(base_path, relpath)
            entity_groundings[relpath] = record

        while pending_workflows:
            relpath = pending_workflows.pop(0)
            if relpath in workflow_results:
                continue
            workflow_results[relpath] = _load_workflow_run(base_path, relpath)

    for relpath, review in evidence_reviews.items():
        workflow_results.setdefault(
            relpath,
            _workflow_result_from_review(review),
        )

    source_artifacts = _dedupe_refs(
        [
            *(record.artifact_ref for record in evidence_cards.values()),
            *(record.artifact_ref for record in evidence_reviews.values()),
            *(record.artifact_ref for record in entity_groundings.values()),
            *(record.artifact_ref for record in workflow_results.values()),
        ]
    )
    return {
        "evidence_cards": dict(sorted(evidence_cards.items())),
        "evidence_reviews": dict(sorted(evidence_reviews.items())),
        "entity_groundings": dict(sorted(entity_groundings.items())),
        "workflow_results": dict(sorted(workflow_results.items())),
        "source_artifacts": source_artifacts,
    }


def _build_claim_graph_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    evidence_cards: dict[str, _LoadedEvidenceCard] = inputs["evidence_cards"]
    evidence_reviews: dict[str, _LoadedEvidenceReview] = inputs["evidence_reviews"]
    entity_groundings: dict[str, _LoadedEntityGrounding] = inputs["entity_groundings"]
    workflow_results: dict[str, _LoadedWorkflowResult] = inputs["workflow_results"]
    source_artifacts: list[ArtifactReference] = inputs["source_artifacts"]

    evidence_card_nodes: dict[str, ClaimGraphEvidenceCardNode] = {}
    evidence_card_node_ids_by_path: dict[str, str] = {}
    entity_nodes: dict[str, ClaimGraphEntityNode] = {}
    workflow_result_nodes: dict[str, ClaimGraphWorkflowResultNode] = {}

    card_entity_ids: dict[str, set[str]] = {}
    grounding_entities_by_path: dict[str, set[str]] = {}

    for relpath, record in evidence_cards.items():
        node_id = _evidence_card_node_id(record.artifact.id)
        evidence_card_node_ids_by_path[relpath] = node_id
        evidence_card_nodes[node_id] = ClaimGraphEvidenceCardNode(
            node_id=node_id,
            artifact=record.artifact_ref,
            stable_identifier=record.artifact.stable_identifier,
            source_database=record.artifact.source_database,
            title=record.artifact.title,
            confidence=record.artifact.confidence,
        )
        entity_ids = set()
        for entity in record.artifact.grounded_entities:
            entity_node = _entity_node_from_grounded_entity(entity)
            entity_nodes[entity_node.node_id] = entity_node
            entity_ids.add(entity_node.node_id)
        card_entity_ids[relpath] = entity_ids

    for relpath, record in entity_groundings.items():
        entity_ids = set()
        for result in record.artifact.results:
            if result.grounded_entity is None:
                continue
            entity_node = _entity_node_from_grounded_entity(result.grounded_entity)
            entity_nodes[entity_node.node_id] = entity_node
            entity_ids.add(entity_node.node_id)
        grounding_entities_by_path[relpath] = entity_ids

    for relpath, record in evidence_cards.items():
        related_grounding_paths = [
            ref.path for ref in record.artifact.related_artifacts if ref.artifact_type == "entity_grounding"
        ]
        for grounding_path in related_grounding_paths:
            card_entity_ids.setdefault(relpath, set()).update(
                grounding_entities_by_path.get(grounding_path, set())
            )

    for relpath, record in workflow_results.items():
        node_id = _workflow_result_node_id(record.artifact_type, record.artifact_ref.id or record.artifact_relpath)
        workflow_result_nodes[node_id] = ClaimGraphWorkflowResultNode(
            node_id=node_id,
            artifact=record.artifact_ref,
            artifact_type=record.artifact_type,
            label=record.label,
            workflow_name=record.workflow_name,
            workflow_slug=record.workflow_slug,
            result_status=record.result_status,
            confidence=record.confidence,
        )

    claim_nodes: dict[str, ClaimGraphClaimNode] = {}
    claim_entity_ids: dict[str, set[str]] = {}
    claim_nodes_by_source: dict[tuple[str, str], str] = {}
    edges: dict[tuple[str, str, str], ClaimGraphEdge] = {}

    for relpath, record in evidence_cards.items():
        card_node_id = _evidence_card_node_id(record.artifact.id)
        entity_ids = sorted(card_entity_ids.get(relpath, set()))
        for claim in record.artifact.claims:
            node_id = _claim_node_id(record.artifact.id, claim.id)
            claim_nodes[node_id] = ClaimGraphClaimNode(
                node_id=node_id,
                statement=claim.statement,
                confidence=claim.confidence,
                status="proposed",
                provenance=[
                    ClaimGraphClaimProvenance(
                        source_type="evidence_card_claim",
                        artifact=record.artifact_ref,
                        source_identifier=claim.id,
                    )
                ],
            )
            claim_nodes_by_source[(relpath, claim.id)] = node_id
            claim_entity_ids[node_id] = set(entity_ids)
            _add_edge(
                edges,
                edge_type="supports",
                source_node_id=card_node_id,
                source_node_type="evidence_card",
                target_node_id=node_id,
                target_node_type="claim",
                provenance_artifact=record.artifact_ref,
                rationale="Evidence card contains the extracted claim statement.",
            )
            _add_edge(
                edges,
                edge_type="derived_from",
                source_node_id=node_id,
                source_node_type="claim",
                target_node_id=card_node_id,
                target_node_type="evidence_card",
                provenance_artifact=record.artifact_ref,
                rationale="Claim text was extracted from the evidence card artifact.",
            )
            for entity_id in entity_ids:
                _add_edge(
                    edges,
                    edge_type="mentions",
                    source_node_id=node_id,
                    source_node_type="claim",
                    target_node_id=entity_id,
                    target_node_type="entity",
                    provenance_artifact=record.artifact_ref,
                    rationale="The evidence card links this claim to the grounded entity context.",
                )

    for record in workflow_results.values():
        if record.artifact_type != "workflow_run":
            continue

        workflow_identifier = record.artifact_ref.id or record.artifact_relpath
        workflow_node_id = _workflow_result_node_id(record.artifact_type, workflow_identifier)
        for workflow_claim in record.summary_claims:
            node_id = _claim_node_id(workflow_identifier, workflow_claim.source_identifier)
            claim_nodes[node_id] = ClaimGraphClaimNode(
                node_id=node_id,
                statement=workflow_claim.statement,
                confidence=workflow_claim.confidence,
                status="proposed",
                provenance=[
                    ClaimGraphClaimProvenance(
                        source_type="workflow_summary",
                        artifact=record.artifact_ref,
                        source_identifier=workflow_claim.source_identifier,
                        note=workflow_claim.note,
                    )
                ],
            )
            claim_entity_ids[node_id] = set()
            _add_edge(
                edges,
                edge_type="supports",
                source_node_id=workflow_node_id,
                source_node_type="workflow_result",
                target_node_id=node_id,
                target_node_type="claim",
                provenance_artifact=record.artifact_ref,
                rationale="The workflow run recorded this summarized internal result.",
            )
            _add_edge(
                edges,
                edge_type="derived_from",
                source_node_id=node_id,
                source_node_type="claim",
                target_node_id=workflow_node_id,
                target_node_type="workflow_result",
                provenance_artifact=record.artifact_ref,
                rationale="Claim text was derived from the workflow-run summary fields.",
            )

    for relpath, record in evidence_reviews.items():
        review_node_id = _workflow_result_node_id("evidence_review", record.artifact.id)
        supporting_card_paths = {
            ref.path for ref in record.artifact.evidence_included if ref.artifact_type == "evidence_card"
        }

        for fact in record.artifact.source_facts:
            claim_node_id = claim_nodes_by_source.get((fact.evidence.path, fact.claim_id))
            if claim_node_id is None:
                continue
            _add_edge(
                edges,
                edge_type="evaluated_by",
                source_node_id=claim_node_id,
                source_node_type="claim",
                target_node_id=review_node_id,
                target_node_type="workflow_result",
                provenance_artifact=record.artifact_ref,
                rationale="Evidence review recorded this claim as a source fact.",
            )

        fallback_review_entity_ids = set()
        for card_path in supporting_card_paths:
            fallback_review_entity_ids.update(card_entity_ids.get(card_path, set()))

        for index, conclusion in enumerate(record.artifact.synthesized_conclusions, start=1):
            source_identifier = normalize_identifier(f"conclusion-{index}")
            node_id = _claim_node_id(record.artifact.id, source_identifier)
            claim_nodes[node_id] = ClaimGraphClaimNode(
                node_id=node_id,
                statement=conclusion.statement,
                confidence=conclusion.confidence,
                status=_claim_status_from_review(record.artifact.review_status),
                provenance=[
                    ClaimGraphClaimProvenance(
                        source_type="evidence_review_conclusion",
                        artifact=record.artifact_ref,
                        source_identifier=source_identifier,
                    )
                ],
            )
            claim_entity_ids[node_id] = set()
            _add_edge(
                edges,
                edge_type="derived_from",
                source_node_id=node_id,
                source_node_type="claim",
                target_node_id=review_node_id,
                target_node_type="workflow_result",
                provenance_artifact=record.artifact_ref,
                rationale="The synthesized conclusion was generated by the evidence-review workflow.",
            )
            _add_edge(
                edges,
                edge_type="evaluated_by",
                source_node_id=node_id,
                source_node_type="claim",
                target_node_id=review_node_id,
                target_node_type="workflow_result",
                provenance_artifact=record.artifact_ref,
                rationale="The evidence-review workflow evaluated this claim.",
            )

            supporting_refs = conclusion.supporting_evidence or list(record.artifact.evidence_included)
            for ref in supporting_refs:
                if ref.artifact_type != "evidence_card":
                    continue
                evidence_node_id = evidence_card_node_ids_by_path.get(ref.path)
                if evidence_node_id not in evidence_card_nodes:
                    continue
                _add_edge(
                    edges,
                    edge_type="supports",
                    source_node_id=evidence_node_id,
                    source_node_type="evidence_card",
                    target_node_id=node_id,
                    target_node_type="claim",
                    provenance_artifact=ref,
                    rationale="The evidence review cites this evidence card as supporting evidence.",
                )
                claim_entity_ids[node_id].update(card_entity_ids.get(ref.path, set()))

            if not claim_entity_ids[node_id]:
                claim_entity_ids[node_id].update(fallback_review_entity_ids)

            for entity_id in sorted(claim_entity_ids[node_id]):
                _add_edge(
                    edges,
                    edge_type="mentions",
                    source_node_id=node_id,
                    source_node_type="claim",
                    target_node_id=entity_id,
                    target_node_type="entity",
                    provenance_artifact=record.artifact_ref,
                    rationale="The review conclusion inherits grounded entity context from its supporting evidence.",
                )

    contradiction_count = _apply_contradiction_rules(
        claim_nodes=claim_nodes,
        claim_entity_ids=claim_entity_ids,
        edges=edges,
    )

    claim_node_list = sorted(claim_nodes.values(), key=lambda node: node.node_id)
    evidence_card_node_list = sorted(evidence_card_nodes.values(), key=lambda node: node.node_id)
    entity_node_list = sorted(entity_nodes.values(), key=lambda node: node.node_id)
    workflow_result_node_list = sorted(workflow_result_nodes.values(), key=lambda node: node.node_id)
    edge_list = sorted(edges.values(), key=lambda edge: edge.id)

    summary = ClaimGraphSummary(
        claim_count=len(claim_node_list),
        evidence_card_count=len(evidence_card_node_list),
        entity_count=len(entity_node_list),
        workflow_result_count=len(workflow_result_node_list),
        edge_count=len(edge_list),
        contradiction_count=contradiction_count,
        source_artifact_count=len(source_artifacts),
    )
    return {
        "source_artifacts": source_artifacts,
        "claim_nodes": claim_node_list,
        "evidence_card_nodes": evidence_card_node_list,
        "entity_nodes": entity_node_list,
        "workflow_result_nodes": workflow_result_node_list,
        "edges": edge_list,
        "summary": summary,
    }


def _load_evidence_card(base_path: Path, relpath: str) -> _LoadedEvidenceCard:
    artifact_path = resolve_artifact_path(base_path, relpath)
    artifact = load_artifact_document(artifact_path)
    if not isinstance(artifact, EvidenceCard):
        raise ValueError(f"{relpath!r} is not an evidence_card artifact.")
    return _LoadedEvidenceCard(
        artifact=artifact,
        artifact_path=artifact_path,
        artifact_relpath=relpath,
        artifact_ref=ArtifactReference(
            artifact_type="evidence_card",
            path=relpath,
            id=artifact.id,
            run_id=artifact.run_id,
        ),
    )


def _load_evidence_review(base_path: Path, relpath: str) -> _LoadedEvidenceReview:
    artifact_path = resolve_artifact_path(base_path, relpath)
    artifact = load_artifact_document(artifact_path)
    if not isinstance(artifact, EvidenceReviewArtifact):
        raise ValueError(f"{relpath!r} is not an evidence_review artifact.")
    return _LoadedEvidenceReview(
        artifact=artifact,
        artifact_path=artifact_path,
        artifact_relpath=relpath,
        artifact_ref=ArtifactReference(
            artifact_type="evidence_review",
            path=relpath,
            id=artifact.id,
            run_id=artifact.run_id,
        ),
    )


def _load_entity_grounding(base_path: Path, relpath: str) -> _LoadedEntityGrounding:
    artifact_path = resolve_artifact_path(base_path, relpath)
    artifact = load_artifact_document(artifact_path)
    if not isinstance(artifact, EntityGroundingArtifact):
        raise ValueError(f"{relpath!r} is not an entity_grounding artifact.")
    return _LoadedEntityGrounding(
        artifact=artifact,
        artifact_path=artifact_path,
        artifact_relpath=relpath,
        artifact_ref=ArtifactReference(
            artifact_type="entity_grounding",
            path=relpath,
            id=artifact.id,
            run_id=artifact.run_id,
        ),
    )


def _load_workflow_run(base_path: Path, relpath: str) -> _LoadedWorkflowResult:
    artifact_path = resolve_artifact_path(base_path, relpath)
    try:
        artifact = load_artifact_document(artifact_path)
    except Exception:
        artifact = None

    if isinstance(artifact, WorkflowRun):
        summary_claims = _workflow_summary_claims_from_payload(
            artifact.model_dump(mode="json"),
            label=artifact.workflow.name,
        )
        return _LoadedWorkflowResult(
            artifact_path=artifact_path,
            artifact_relpath=relpath,
            artifact_ref=ArtifactReference(
                artifact_type="workflow_run",
                path=relpath,
                id=artifact.id,
                run_id=artifact.run_id,
            ),
            artifact_type="workflow_run",
            label=artifact.workflow.name,
            workflow_name=artifact.workflow.name,
            workflow_slug=artifact.workflow.slug,
            result_status=artifact.lifecycle_status,
            summary_claims=summary_claims,
        )

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("artifact_type") != "workflow_run":
        raise ValueError(f"{relpath!r} is not a workflow_run artifact.")

    run_id = payload.get("run_id")
    run_id_value = run_id if isinstance(run_id, str) and is_valid_run_id(run_id) else None
    workflow = payload.get("workflow")
    workflow_name = None
    workflow_slug = None
    if isinstance(workflow, dict):
        raw_name = workflow.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            workflow_name = raw_name.strip()
        raw_slug = workflow.get("slug")
        if isinstance(raw_slug, str) and raw_slug.strip():
            workflow_slug = _normalize_optional_identifier(raw_slug)
    source_workflow = payload.get("source_workflow")
    if workflow_name is None and isinstance(source_workflow, str) and source_workflow.strip():
        workflow_name = source_workflow.strip()
    if workflow_slug is None and isinstance(source_workflow, str) and source_workflow.strip():
        workflow_slug = _normalize_optional_identifier(source_workflow)

    label = workflow_name or run_id_value or relpath
    summary_claims = _workflow_summary_claims_from_payload(payload, label=label)
    result_status = None
    raw_status = payload.get("lifecycle_status")
    if isinstance(raw_status, str) and raw_status.strip():
        result_status = _normalize_optional_identifier(raw_status)

    artifact_id = None
    raw_id = payload.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        artifact_id = _normalize_optional_identifier(raw_id)
    elif run_id_value is not None:
        artifact_id = normalize_identifier(f"workflow_run:{run_id_value.lower()}")

    return _LoadedWorkflowResult(
        artifact_path=artifact_path,
        artifact_relpath=relpath,
        artifact_ref=ArtifactReference(
            artifact_type="workflow_run",
            path=relpath,
            id=artifact_id,
            run_id=run_id_value,
        ),
        artifact_type="workflow_run",
        label=label,
        workflow_name=workflow_name,
        workflow_slug=workflow_slug,
        result_status=result_status,
        summary_claims=summary_claims,
    )


def _workflow_result_from_review(record: _LoadedEvidenceReview) -> _LoadedWorkflowResult:
    return _LoadedWorkflowResult(
        artifact_path=record.artifact_path,
        artifact_relpath=record.artifact_relpath,
        artifact_ref=record.artifact_ref,
        artifact_type="evidence_review",
        label=record.artifact.review_question,
        workflow_name="Evidence Review",
        workflow_slug="evidence-review",
        result_status=record.artifact.review_status,
        confidence=record.artifact.confidence,
    )


def _workflow_summary_claims_from_payload(
    payload: dict[str, Any],
    *,
    label: str,
) -> tuple[_WorkflowSummaryClaim, ...]:
    claims: list[_WorkflowSummaryClaim] = []

    lifecycle_status = _clean_optional_text(payload.get("lifecycle_status"))
    if lifecycle_status is not None:
        claims.append(
            _WorkflowSummaryClaim(
                source_identifier="lifecycle-status",
                statement=(
                    f"Workflow {label} reached lifecycle status "
                    f"{_humanize_identifier(lifecycle_status)}."
                ),
                confidence="high",
            )
        )

    qc_status = _clean_optional_text(payload.get("qc_status"))
    if qc_status is not None:
        claims.append(
            _WorkflowSummaryClaim(
                source_identifier="qc-status",
                statement=f"Workflow {label} reported QC status {_humanize_identifier(qc_status)}.",
                confidence="high",
            )
        )

    qc_summary = _clean_optional_text(payload.get("qc_summary"))
    if qc_summary is not None:
        claims.append(
            _WorkflowSummaryClaim(
                source_identifier="qc-summary",
                statement=qc_summary,
                confidence="high",
            )
        )

    raw_metrics = payload.get("summary_metrics")
    if isinstance(raw_metrics, list):
        for index, raw_metric in enumerate(raw_metrics, start=1):
            claim = _workflow_summary_metric_claim(raw_metric, index=index, label=label)
            if claim is not None:
                claims.append(claim)

    raw_warnings = payload.get("warnings")
    if isinstance(raw_warnings, list):
        for index, raw_warning in enumerate(raw_warnings, start=1):
            warning = _clean_optional_text(raw_warning)
            if warning is None:
                continue
            claims.append(
                _WorkflowSummaryClaim(
                    source_identifier=f"warning-{index}",
                    statement=f"Workflow {label} recorded warning: {warning}",
                    confidence="high",
                )
            )

    if not claims:
        claims.append(
            _WorkflowSummaryClaim(
                source_identifier="workflow-recorded",
                statement=f"Workflow {label} produced a recorded result artifact.",
                confidence="high",
            )
        )

    return tuple(claims)


def _workflow_summary_metric_claim(
    raw_metric: Any,
    *,
    index: int,
    label: str,
) -> _WorkflowSummaryClaim | None:
    if not isinstance(raw_metric, dict):
        return None

    metric_name = _clean_optional_text(raw_metric.get("metric_name"))
    if metric_name is None:
        return None
    stage = _clean_optional_text(raw_metric.get("stage"))
    value_text = _workflow_metric_value_text(raw_metric.get("value"))

    source_identifier_parts = [f"summary-metric-{index}"]
    if stage is not None:
        source_identifier_parts.append(stage)
    source_identifier_parts.append(metric_name)

    statement = f"Workflow {label} reported metric {metric_name}={value_text}"
    if stage is not None:
        statement += f" at the {_humanize_identifier(stage)} stage."
    else:
        statement += "."

    note_parts: list[str] = []
    if stage is not None:
        note_parts.append(f"stage={stage}")
    source_artifact_path = _artifact_path_from_reference(raw_metric.get("source_artifact"))
    if source_artifact_path is not None:
        note_parts.append(f"source_artifact={source_artifact_path}")

    return _WorkflowSummaryClaim(
        source_identifier=normalize_identifier("-".join(source_identifier_parts)),
        statement=statement,
        confidence="high",
        note="; ".join(note_parts) if note_parts else None,
    )


def _artifact_path_from_reference(value: Any) -> str | None:
    if isinstance(value, ArtifactReference):
        return value.path
    if isinstance(value, dict):
        return _clean_optional_text(value.get("path"))
    return None


def _workflow_metric_value_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or '""'
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _humanize_identifier(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip()


def _entity_node_from_grounded_entity(entity) -> ClaimGraphEntityNode:
    return ClaimGraphEntityNode(
        node_id=_entity_node_id(entity.stable_identifier),
        entity_type=entity.entity_type,
        source_database=entity.source_database,
        stable_identifier=entity.stable_identifier,
        preferred_label=entity.preferred_label,
        aliases=entity.aliases,
        species=entity.species,
        taxon_id=entity.taxon_id,
    )


def _claim_status_from_review(review_status: str) -> str:
    if review_status == "supported":
        return "supported"
    if review_status == "mixed":
        return "mixed"
    return "insufficient_evidence"


def _claim_node_id(artifact_id: str, source_identifier: str) -> str:
    return normalize_identifier(f"claim-{artifact_id}-{source_identifier}")


def _evidence_card_node_id(artifact_id: str) -> str:
    return normalize_identifier(f"evidence-card-{artifact_id}")


def _entity_node_id(stable_identifier: str) -> str:
    return normalize_identifier(f"entity-{stable_identifier}")


def _workflow_result_node_id(artifact_type: str, identifier: str) -> str:
    return normalize_identifier(f"workflow-result-{artifact_type}-{identifier}")


def _normalize_optional_identifier(value: str) -> str:
    return normalize_identifier(value)


def _dedupe_refs(refs: list[ArtifactReference]) -> list[ArtifactReference]:
    deduped: list[ArtifactReference] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for ref in refs:
        key = (ref.artifact_type, ref.path, ref.id, ref.run_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return sorted(deduped, key=lambda ref: (ref.path, ref.artifact_type, ref.id or "", ref.run_id or ""))


def _add_edge(
    edges: dict[tuple[str, str, str], ClaimGraphEdge],
    *,
    edge_type: str,
    source_node_id: str,
    source_node_type: str,
    target_node_id: str,
    target_node_type: str,
    provenance_artifact: ArtifactReference | None = None,
    rationale: str | None = None,
) -> None:
    key = (edge_type, source_node_id, target_node_id)
    if key in edges:
        return
    edge_id = normalize_identifier(f"{edge_type}-{source_node_id}-{target_node_id}")
    edges[key] = ClaimGraphEdge(
        id=edge_id,
        edge_type=edge_type,
        source_node_id=source_node_id,
        source_node_type=source_node_type,
        target_node_id=target_node_id,
        target_node_type=target_node_type,
        provenance_artifact=provenance_artifact,
        rationale=rationale,
    )


def _apply_contradiction_rules(
    *,
    claim_nodes: dict[str, ClaimGraphClaimNode],
    claim_entity_ids: dict[str, set[str]],
    edges: dict[tuple[str, str, str], ClaimGraphEdge],
) -> int:
    contradiction_count = 0
    ordered_claims = sorted(claim_nodes.values(), key=lambda node: node.node_id)
    for index, left in enumerate(ordered_claims):
        for right in ordered_claims[index + 1 :]:
            left_polarity = _claim_polarity(left.statement)
            right_polarity = _claim_polarity(right.statement)
            if left_polarity == 0 or right_polarity == 0 or left_polarity == right_polarity:
                continue

            shared_entities = sorted(claim_entity_ids.get(left.node_id, set()) & claim_entity_ids.get(right.node_id, set()))
            shared_tokens = sorted(_claim_topic_tokens(left.statement) & _claim_topic_tokens(right.statement))
            if shared_entities:
                if not shared_tokens:
                    continue
            elif len(shared_tokens) < 2:
                continue

            rationale_parts = []
            if shared_entities:
                rationale_parts.append(f"shared entity nodes: {', '.join(shared_entities)}")
            if shared_tokens:
                rationale_parts.append(f"shared topic tokens: {', '.join(shared_tokens[:6])}")
            rationale_parts.append("opposing polarity cues were detected in the paired claim statements")
            _add_edge(
                edges,
                edge_type="contradicts",
                source_node_id=left.node_id,
                source_node_type="claim",
                target_node_id=right.node_id,
                target_node_type="claim",
                rationale="; ".join(rationale_parts) + ".",
            )
            contradiction_count += 1
            left.status = _status_with_contradiction(left.status)
            right.status = _status_with_contradiction(right.status)
    return contradiction_count


def _status_with_contradiction(status: str) -> str:
    if status == "insufficient_evidence":
        return status
    return "mixed"


def _claim_polarity(statement: str) -> int:
    tokens = set(_tokenize(statement))
    if tokens & _NEGATION_OVERRIDE_CUES:
        return -1
    positive = len(tokens & _POSITIVE_CUES)
    negative = len(tokens & _NEGATIVE_CUES)
    if positive == negative:
        return 0
    return 1 if positive > negative else -1


def _claim_topic_tokens(statement: str) -> set[str]:
    return {
        token
        for token in _tokenize(statement)
        if token not in _STOPWORDS and token not in _POSITIVE_CUES and token not in _NEGATIVE_CUES
    }


def _tokenize(statement: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(statement.casefold()) if len(token) > 2]


def _refresh_content_hash_manifest(layout) -> None:
    entries: dict[str, bytes] = {}
    for path in sorted(layout.run_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(layout.run_dir).as_posix()
        if relative == "content_hashes.json":
            continue
        entries[relative] = path.read_bytes()

    manifest = build_content_hash_manifest(
        run_id=layout.run_id,
        schema_version=SCHEMA_PACK_VERSION,
        created_at=layout.created_at,
        source_workflow=layout.workflow,
        entries=entries,
    )
    layout.content_hash_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
