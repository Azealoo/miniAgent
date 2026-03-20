"""Tests for deterministic claim-graph materialization."""

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import ClaimGraphArtifact, load_artifact_document, lookup_artifact_registry  # noqa: E402
from artifacts.schemas import SCHEMA_PACK_VERSION  # noqa: E402
from evidence.claim_graph import ClaimGraphInput, run_claim_graph  # noqa: E402
from tools.claim_graph_tool import ClaimGraphTool  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _stage_evidence_card(
    base_dir: Path,
    *,
    relpath: str,
    artifact_id: str,
    stable_identifier: str,
    claim_id: str,
    statement: str,
    grounded_entity_identifier: str = "ensembl:ENSG00000141510",
    grounded_label: str = "TP53",
) -> str:
    _write_yaml(
        base_dir / relpath,
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "evidence_card",
            "id": artifact_id,
            "run_id": "run-20260318T193000Z-deadbeef",
            "created_at": "2026-03-18T19:30:00Z",
            "source_workflow": "literature-retrieval",
            "related_artifacts": [],
            "source_database": "pubmed",
            "stable_identifier": stable_identifier,
            "title": f"Evidence card {artifact_id}",
            "study_type": "observational_study",
            "claims": [
                {
                    "id": claim_id,
                    "statement": statement,
                    "confidence": "high",
                }
            ],
            "confidence": "high",
            "limitations": ["Demonstration artifact."],
            "entity_tags": [],
            "grounded_entities": [
                {
                    "entity_type": "gene",
                    "source_database": "ensembl",
                    "stable_identifier": grounded_entity_identifier,
                    "preferred_label": grounded_label,
                    "aliases": [grounded_label],
                    "species": "Homo sapiens",
                    "taxon_id": "taxonomy:9606",
                }
            ],
            "grounding_results": [],
            "grounding_requires_clarification": False,
            "cached_raw_payload_path": "artifacts/literature-retrieval/cache/source.xml",
        },
    )
    return relpath


def _stage_evidence_review(
    base_dir: Path,
    *,
    relpath: str,
    evidence_card_relpath: str,
    evidence_card_id: str,
    evidence_card_claim_id: str,
) -> str:
    evidence_ref = {
        "artifact_type": "evidence_card",
        "path": evidence_card_relpath,
        "id": evidence_card_id,
        "run_id": "run-20260318T193000Z-deadbeef",
    }
    _write_json(
        base_dir / relpath,
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "evidence_review",
            "id": "evidence-review-demo-v1",
            "run_id": "run-20260318T194500Z-feedface",
            "created_at": "2026-03-18T19:45:00Z",
            "source_workflow": "evidence-review",
            "related_artifacts": [evidence_ref],
            "review_question": "What evidence supports TP53-linked interferon activity?",
            "review_status": "supported",
            "confidence": "medium",
            "evidence_included": [evidence_ref],
            "evidence_excluded": [],
            "limitations": ["Only one study was included."],
            "unresolved_conflicts": [],
            "source_facts": [
                {
                    "statement": "TP53 increased interferon response in treated cells.",
                    "claim_id": evidence_card_claim_id,
                    "stable_identifier": "pubmed:11111111",
                    "evidence": evidence_ref,
                    "confidence": "high",
                }
            ],
            "synthesized_conclusions": [
                {
                    "statement": "Retrieved evidence supports a medium-confidence TP53-linked interferon response conclusion.",
                    "support_status": "supported",
                    "confidence": "medium",
                    "supporting_evidence": [evidence_ref],
                    "limitation_notes": ["Only one study was included."],
                    "conflict_notes": [],
                }
            ],
            "unsupported_claims_present": False,
        },
    )
    return relpath


def _stage_workflow_run(
    base_dir: Path,
    *,
    relpath: str,
    artifact_id: str = "workflow-run-demo-v1",
    workflow_name: str = "RNA Seq QC",
    workflow_slug: str = "rna-seq-qc",
) -> str:
    _write_json(
        base_dir / relpath,
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "workflow_run",
            "id": artifact_id,
            "run_id": "run-20260318T200500Z-abcddcba",
            "created_at": "2026-03-18T20:05:00Z",
            "source_workflow": "internal-dag-runner",
            "related_artifacts": [],
            "workflow": {
                "name": workflow_name,
                "slug": workflow_slug,
            },
            "lifecycle_status": "completed",
            "qc_status": "warning",
            "engine": "internal_dag_runner_v1",
            "parameters": {"min_genes": 200},
            "environment": {"conda_env": "miniAgent"},
            "inputs": [],
            "outputs": [],
            "summary_metrics": [
                {
                    "stage": "qc-summary",
                    "metric_name": "donor_balance_ratio",
                    "value": 0.74,
                    "source_artifact": {
                        "artifact_type": "qa_report",
                        "path": "artifacts/rna-seq-qc/2026-03-18/run-20260318T200500Z-abcddcba/qa_report.json",
                    },
                }
            ],
            "qc_summary": "Single-cell default QC policy [warn] Batch-effect warnings: donor_balance_ratio=0.74 did not meet >= 0.8.",
            "warnings": ["qc warning threshold exceeded for one donor replicate"],
        },
    )
    return relpath


def _stage_partial_workflow_run(
    base_dir: Path,
    *,
    relpath: str,
    artifact_id: str = "workflow-run-partial-demo-v1",
) -> str:
    _write_json(
        base_dir / relpath,
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "workflow_run",
            "id": artifact_id,
            "run_id": "run-20260318T201500Z-deadfade",
            "created_at": "2026-03-18T20:15:00Z",
            "source_workflow": "internal-dag-runner",
            "workflow": {
                "name": "RNA Seq QC",
                "slug": "rna-seq-qc",
            },
            "lifecycle_status": "completed",
            "qc_status": "warning",
            "qc_summary": "Fallback workflow summary remained available.",
            "warnings": ["partial run record preserved workflow summary text"],
        },
    )
    return relpath


def test_run_claim_graph_materializes_artifact_from_review_and_related_evidence(tmp_path):
    evidence_card_relpath = _stage_evidence_card(
        tmp_path,
        relpath="artifacts/literature-retrieval/2026-03-18/run-20260318T193000Z-deadbeef/evidence_card.yaml",
        artifact_id="evidence-demo-v1",
        stable_identifier="pubmed:11111111",
        claim_id="tp53-interferon-claim",
        statement="TP53 increased interferon response in treated cells.",
    )
    evidence_review_relpath = _stage_evidence_review(
        tmp_path,
        relpath="artifacts/evidence-review/2026-03-18/run-20260318T194500Z-feedface/evidence_review.json",
        evidence_card_relpath=evidence_card_relpath,
        evidence_card_id="evidence-demo-v1",
        evidence_card_claim_id="tp53-interferon-claim",
    )

    result = run_claim_graph(
        tmp_path,
        ClaimGraphInput(
            evidence_review_paths=[evidence_review_relpath],
            include_related_artifacts=True,
        ),
    )

    assert result.graph.summary.claim_count == 2
    assert result.graph.summary.evidence_card_count == 1
    assert result.graph.summary.entity_count == 1
    assert result.graph.summary.workflow_result_count == 1
    assert {edge.edge_type for edge in result.graph.edges} >= {
        "supports",
        "derived_from",
        "mentions",
        "evaluated_by",
    }

    persisted = load_artifact_document(result.artifact_path)
    assert isinstance(persisted, ClaimGraphArtifact)

    registry = lookup_artifact_registry(tmp_path, artifact_type="claim_graph")
    assert registry.matched_count == 1
    assert registry.records[0].path == result.artifact_relpath


def test_run_claim_graph_materializes_workflow_only_claims_from_workflow_run(tmp_path):
    workflow_run_relpath = _stage_workflow_run(
        tmp_path,
        relpath="artifacts/rna-seq-qc/2026-03-18/run-20260318T200500Z-abcddcba/run.json",
    )

    result = run_claim_graph(
        tmp_path,
        ClaimGraphInput(
            workflow_run_paths=[workflow_run_relpath],
            include_related_artifacts=False,
        ),
    )

    assert result.graph.summary.claim_count == 5
    assert result.graph.summary.evidence_card_count == 0
    assert result.graph.summary.entity_count == 0
    assert result.graph.summary.workflow_result_count == 1
    assert {node.provenance[0].source_type for node in result.graph.claim_nodes} == {"workflow_summary"}
    assert {
        node.statement for node in result.graph.claim_nodes
    } >= {
        "Workflow RNA Seq QC reached lifecycle status completed.",
        "Workflow RNA Seq QC reported QC status warning.",
        "Single-cell default QC policy [warn] Batch-effect warnings: donor_balance_ratio=0.74 did not meet >= 0.8.",
        "Workflow RNA Seq QC reported metric donor_balance_ratio=0.74 at the qc summary stage.",
        "Workflow RNA Seq QC recorded warning: qc warning threshold exceeded for one donor replicate",
    }

    supporting_edges = [
        edge
        for edge in result.graph.edges
        if edge.edge_type == "supports"
        and edge.source_node_type == "workflow_result"
        and edge.target_node_type == "claim"
    ]
    derived_edges = [
        edge
        for edge in result.graph.edges
        if edge.edge_type == "derived_from"
        and edge.source_node_type == "claim"
        and edge.target_node_type == "workflow_result"
    ]
    assert len(supporting_edges) == result.graph.summary.claim_count
    assert len(derived_edges) == result.graph.summary.claim_count

    metric_claim = next(
        node
        for node in result.graph.claim_nodes
        if node.statement.startswith("Workflow RNA Seq QC reported metric donor_balance_ratio=0.74")
    )
    assert metric_claim.provenance[0].note == (
        "stage=qc-summary; "
        "source_artifact=artifacts/rna-seq-qc/2026-03-18/run-20260318T200500Z-abcddcba/qa_report.json"
    )


def test_run_claim_graph_supports_partial_workflow_run_fallback(tmp_path):
    workflow_run_relpath = _stage_partial_workflow_run(
        tmp_path,
        relpath="artifacts/rna-seq-qc/2026-03-18/run-20260318T201500Z-deadfade/run.json",
    )

    result = run_claim_graph(
        tmp_path,
        ClaimGraphInput(
            workflow_run_paths=[workflow_run_relpath],
            include_related_artifacts=False,
        ),
    )

    assert result.graph.summary.claim_count == 4
    assert result.graph.summary.workflow_result_count == 1
    assert result.graph.workflow_result_nodes[0].artifact.id == "workflow-run-partial-demo-v1"
    assert {
        node.statement for node in result.graph.claim_nodes
    } >= {
        "Workflow RNA Seq QC reached lifecycle status completed.",
        "Workflow RNA Seq QC reported QC status warning.",
        "Fallback workflow summary remained available.",
        "Workflow RNA Seq QC recorded warning: partial run record preserved workflow summary text",
    }


def test_run_claim_graph_adds_conservative_contradiction_edges(tmp_path):
    card_a = _stage_evidence_card(
        tmp_path,
        relpath="artifacts/literature-retrieval/2026-03-18/run-20260318T193000Z-aaaabbbb/evidence_card.yaml",
        artifact_id="evidence-a-v1",
        stable_identifier="pubmed:22222222",
        claim_id="tp53-positive",
        statement="TP53 increased interferon response in treated cells.",
    )
    card_b = _stage_evidence_card(
        tmp_path,
        relpath="artifacts/literature-retrieval/2026-03-18/run-20260318T193100Z-ccccdddd/evidence_card.yaml",
        artifact_id="evidence-b-v1",
        stable_identifier="pubmed:33333333",
        claim_id="tp53-negative",
        statement="TP53 did not increase interferon response in treated cells.",
    )

    result = run_claim_graph(
        tmp_path,
        ClaimGraphInput(
            evidence_card_paths=[card_a, card_b],
            include_related_artifacts=False,
        ),
    )

    contradiction_edges = [edge for edge in result.graph.edges if edge.edge_type == "contradicts"]
    assert len(contradiction_edges) == 1
    assert result.graph.summary.contradiction_count == 1
    assert {node.status for node in result.graph.claim_nodes} == {"mixed"}


def test_claim_graph_tool_returns_structured_result(tmp_path):
    evidence_card_relpath = _stage_evidence_card(
        tmp_path,
        relpath="artifacts/literature-retrieval/2026-03-18/run-20260318T193000Z-deadbeef/evidence_card.yaml",
        artifact_id="evidence-tool-v1",
        stable_identifier="pubmed:44444444",
        claim_id="tp53-tool-claim",
        statement="TP53 increased interferon response in treated cells.",
    )

    tool = ClaimGraphTool(base_dir=str(tmp_path))
    summary, artifact = tool._run(evidence_card_paths=[evidence_card_relpath], include_related_artifacts=False)

    assert "Built claim graph" in summary
    assert artifact["tool_name"] == "claim_graph"
    assert artifact["status"] == "success"
    assert artifact["structured_payload"]["summary"]["claim_count"] == 1
    assert artifact["artifact_refs"][0]["artifact_type"] == "claim_graph"
