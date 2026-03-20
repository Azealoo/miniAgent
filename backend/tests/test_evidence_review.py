import shutil
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import EvidenceReviewArtifact, load_artifact_document, lookup_artifact_registry
from evidence.review import EvidenceReviewInput, run_evidence_review
from evidence.review_gate import EvidenceReviewGateInput, run_evidence_review_gate
from evidence.retrieval import EvidenceRetrievalResult
from tools.evidence_review_tool import EvidenceReviewTool


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _stage_example_evidence_card(base_dir: Path) -> str:
    relpath = (
        "artifacts/literature-retrieval/2026-03-18/"
        "run-20260318T193000Z-deadbeef/evidence_card.yaml"
    )
    target = base_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BACKEND_ROOT / "artifacts" / "examples" / "evidence_card.yaml", target)
    return relpath


def test_run_evidence_review_reuses_explicit_evidence_card_and_persists_artifact(tmp_path):
    evidence_card_relpath = _stage_example_evidence_card(tmp_path)

    result = run_evidence_review(
        tmp_path,
        EvidenceReviewInput(
            question="What evidence supports a shared interferon-response program across donors?",
            evidence_card_paths=[evidence_card_relpath],
        ),
    )

    assert result.review.review_status == "supported"
    assert result.review.unsupported_claims_present is False
    assert len(result.review.evidence_included) == 1
    assert result.review.source_facts
    assert result.artifact_path.exists()

    persisted = load_artifact_document(result.artifact_path)
    assert isinstance(persisted, EvidenceReviewArtifact)
    assert persisted.review_question.startswith("What evidence supports")

    registry = lookup_artifact_registry(tmp_path, artifact_type="evidence_review")
    assert registry.matched_count == 1
    assert registry.records[0].path == result.artifact_relpath


def test_run_evidence_review_marks_insufficient_evidence_when_no_cards_are_available(tmp_path):
    empty_result = EvidenceRetrievalResult(
        query="tp53 stress response",
        candidate_records=[],
        selected_pmids=[],
        cards=[],
        failures=[],
        persisted_context=None,
    )

    with patch("evidence.review.run_evidence_retrieval", return_value=empty_result):
        result = run_evidence_review(
            tmp_path,
            EvidenceReviewInput(
                question="What is the evidence for TP53 stress response?",
                query="tp53 stress response",
            ),
        )

    assert result.review.review_status == "insufficient_evidence"
    assert result.review.confidence == "low"
    assert result.review.unsupported_claims_present is True
    assert result.review.evidence_included == []
    assert "No adequate evidence cards were available for review" in result.review.limitations[0]


def test_evidence_review_tool_returns_structured_review_contract(tmp_path):
    evidence_card_relpath = _stage_example_evidence_card(tmp_path)
    tool = EvidenceReviewTool(base_dir=str(tmp_path))

    summary, artifact = tool._run(
        question="What evidence supports a shared interferon-response program across donors?",
        evidence_card_paths=[evidence_card_relpath],
    )

    assert "Reviewed 1 evidence card" in summary
    assert artifact["tool_name"] == "evidence_review"
    assert artifact["status"] == "success"
    assert artifact["structured_payload"]["review_status"] == "supported"
    assert artifact["structured_payload"]["source_facts"]
    assert artifact["artifact_refs"][0]["artifact_type"] == "evidence_review"


def test_evidence_review_gate_keeps_gene_symbol_questions_reviewable():
    result = run_evidence_review_gate(
        EvidenceReviewGateInput(user_message="What does TP53 do in stress response?")
    )

    assert result.requires_review is True
    assert "gene-symbol-signal" in result.reasons


def test_evidence_review_gate_skips_technical_json_schema_questions():
    result = run_evidence_review_gate(
        EvidenceReviewGateInput(user_message="What does JSON schema mean?")
    )

    assert result.requires_review is False
    assert "biology-signal" not in result.reasons


def test_evidence_review_gate_still_requires_review_for_biology_requests_with_json_output():
    result = run_evidence_review_gate(
        EvidenceReviewGateInput(user_message="Summarize the evidence for TP53 as JSON")
    )

    assert result.requires_review is True
    assert "biology-signal" in result.reasons
    assert "evidence-intent" in result.reasons
