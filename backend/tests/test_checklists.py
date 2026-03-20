"""Tests for file-first checklist definitions and deterministic scoring."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import ArtifactReference, load_artifact_document  # noqa: E402
from checklists import (  # noqa: E402
    available_checklist_ids,
    build_checklist_results_payload,
    checklist_failed_checks,
    checklist_warning_messages,
)


REPO_ROOT = Path(__file__).parent.parent.parent


class TestChecklists:
    def test_seeded_checklist_definitions_are_available(self):
        assert available_checklist_ids() == [
            "arrive_animal_study_reporting",
            "miqe_qpcr_completeness",
            "prisma_literature_screening_completeness",
        ]

    def test_prisma_checklist_warns_when_exclusion_log_is_missing(self, tmp_path):
        evidence_review = json.loads(
            (REPO_ROOT / "backend" / "artifacts" / "examples" / "evidence_review.json").read_text(
                encoding="utf-8"
            )
        )
        evidence_review["evidence_excluded"] = []
        evidence_review_path = (
            tmp_path
            / "artifacts"
            / "evidence-review"
            / "2026-03-20"
            / "run-20260320T210000Z-feedface"
            / "evidence_review.json"
        )
        evidence_review_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_review_path.write_text(json.dumps(evidence_review, indent=2) + "\n", encoding="utf-8")

        payload = build_checklist_results_payload(
            ["prisma_literature_screening_completeness"],
            run_id="run-20260320T220000Z-deadbeef",
            source_workflow="rnaseq_qc_de",
            subject_type="report_bundle",
            subject_label="RNA-seq report bundle",
            evaluated_artifacts=[
                ArtifactReference.model_validate(
                    {
                        "artifact_type": "evidence_review",
                        "path": evidence_review_path.relative_to(tmp_path).as_posix(),
                        "run_id": "run-20260320T210000Z-feedface",
                    }
                )
            ],
            base_dir=tmp_path,
        )

        assert payload["overall_status"] == "warning"
        assert payload["summary"]["failed_best_practice_item_count"] == 1
        assert checklist_failed_checks(payload) == []
        assert any("PRISMA-style literature screening completeness" in warning for warning in checklist_warning_messages(payload))

    def test_prisma_checklist_blocks_when_required_included_evidence_is_missing(self, tmp_path):
        evidence_review = json.loads(
            (REPO_ROOT / "backend" / "artifacts" / "examples" / "evidence_review.json").read_text(
                encoding="utf-8"
            )
        )
        evidence_review["review_status"] = "mixed"
        evidence_review["unsupported_claims_present"] = True
        evidence_review["evidence_included"] = []
        evidence_review["source_facts"] = []
        evidence_review_path = (
            tmp_path
            / "artifacts"
            / "evidence-review"
            / "2026-03-20"
            / "run-20260320T210500Z-feedface"
            / "evidence_review.json"
        )
        evidence_review_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_review_path.write_text(json.dumps(evidence_review, indent=2) + "\n", encoding="utf-8")

        payload = build_checklist_results_payload(
            ["prisma_literature_screening_completeness"],
            run_id="run-20260320T220500Z-deadbeef",
            source_workflow="rnaseq_qc_de",
            subject_type="report_bundle",
            subject_label="RNA-seq report bundle",
            evaluated_artifacts=[
                ArtifactReference.model_validate(
                    {
                        "artifact_type": "evidence_review",
                        "path": evidence_review_path.relative_to(tmp_path).as_posix(),
                        "run_id": "run-20260320T210500Z-feedface",
                    }
                )
            ],
            base_dir=tmp_path,
        )

        assert payload["overall_status"] == "blocked"
        assert payload["summary"]["failed_required_item_count"] == 1
        failed_checks = checklist_failed_checks(payload)
        assert len(failed_checks) == 1
        assert failed_checks[0]["artifact_type"] == "checklist_results"

    def test_prisma_checklist_blocks_when_some_linked_evidence_reviews_cannot_be_loaded(self, tmp_path):
        valid_evidence_review = json.loads(
            (REPO_ROOT / "backend" / "artifacts" / "examples" / "evidence_review.json").read_text(
                encoding="utf-8"
            )
        )
        missing_path = (
            "artifacts/evidence-review/2026-03-20/"
            "run-20260320T210700Z-missing/evidence_review.json"
        )
        valid_path = (
            tmp_path
            / "artifacts"
            / "evidence-review"
            / "2026-03-20"
            / "run-20260320T210701Z-valid"
            / "evidence_review.json"
        )
        valid_path.parent.mkdir(parents=True, exist_ok=True)
        valid_path.write_text(json.dumps(valid_evidence_review, indent=2) + "\n", encoding="utf-8")

        payload = build_checklist_results_payload(
            ["prisma_literature_screening_completeness"],
            run_id="run-20260320T220700Z-deadbeef",
            source_workflow="rnaseq_qc_de",
            subject_type="report_bundle",
            subject_label="RNA-seq report bundle",
            evaluated_artifacts=[
                ArtifactReference.model_validate(
                    {
                        "artifact_type": "evidence_review",
                        "path": missing_path,
                        "run_id": "run-20260320T210700Z-deadbeef",
                    }
                ),
                ArtifactReference.model_validate(
                    {
                        "artifact_type": "evidence_review",
                        "path": valid_path.relative_to(tmp_path).as_posix(),
                        "run_id": "run-20260320T210701Z-feedface",
                    }
                ),
            ],
            base_dir=tmp_path,
        )

        assert payload["overall_status"] == "blocked"
        review_question_item = next(
            item
            for item in payload["evaluations"][0]["items"]
            if item["item_id"] == "review_question_recorded"
        )
        assert review_question_item["status"] == "fail"
        assert "1 of 2 linked source records" in review_question_item["rationale"]
        assert {ref["path"] for ref in review_question_item["evidence_artifacts"]} == {
            missing_path,
            valid_path.relative_to(tmp_path).as_posix(),
        }
        assert any(missing_path in note for note in payload["notes"])

    def test_checklist_results_example_is_schema_valid(self):
        document = load_artifact_document(
            REPO_ROOT / "backend" / "artifacts" / "examples" / "checklist_results.json"
        )

        assert document.artifact_type == "checklist_results"
        assert document.overall_status == "passed"
