import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evidence.integrity import (
    build_citation_mismatch_event,
    check_citation_integrity,
    extract_pmids_from_text,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REVIEW = BACKEND_ROOT / "artifacts" / "examples" / "evidence_review.json"


def _write_review(
    base_dir: Path,
    *,
    created_at: str,
    source_facts: list[dict],
    run_id: str = "run-20260318T193000Z-deadbeef",
    date_dir: str = "2026-03-18",
) -> Path:
    payload = json.loads(EXAMPLE_REVIEW.read_text(encoding="utf-8"))
    payload["created_at"] = created_at
    payload["run_id"] = run_id
    payload["id"] = f"evidence-review-{run_id.lower()}"
    for related in payload.get("related_artifacts", []):
        related["run_id"] = run_id
    for included in payload.get("evidence_included", []):
        included["run_id"] = run_id
    for conclusion in payload.get("synthesized_conclusions", []):
        for entry in conclusion.get("supporting_evidence", []):
            entry["run_id"] = run_id
    payload["source_facts"] = source_facts
    target = (
        base_dir / "artifacts" / "evidence-review" / date_dir / run_id / "evidence_review.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


_FIXTURE_RUN_ID = "run-20260318T193000Z-deadbeef"


def _supported_source_facts(pmid: str, *, run_id: str = _FIXTURE_RUN_ID) -> list[dict]:
    return [
        {
            "statement": "Claim statement.",
            "claim_id": f"claim-{pmid}",
            "stable_identifier": f"pmid:{pmid}",
            "evidence": {
                "artifact_type": "evidence_card",
                "path": (
                    f"artifacts/literature-retrieval/2026-03-18/{run_id}/"
                    f"evidence_card-{pmid}.yaml"
                ),
                "id": f"evidence-pmid-{pmid}",
                "run_id": run_id,
            },
            "confidence": "medium",
        }
    ]


def test_extract_pmids_recognizes_common_inline_forms():
    text = (
        "A prior study (PMID 12345678) reported this; see also PMID: 23456789 "
        "and pmid:34567890, plus pmid-45678901. Duplicate PMID 12345678 should "
        "only appear once."
    )
    assert extract_pmids_from_text(text) == [
        "12345678",
        "23456789",
        "34567890",
        "45678901",
    ]


def test_extract_pmids_returns_empty_for_non_pmid_content():
    assert extract_pmids_from_text("") == []
    assert extract_pmids_from_text("No citations here.") == []
    # A bare digit run is not a citation — the 'pmid' anchor is required.
    assert extract_pmids_from_text("See reference 12345678 nearby.") == []


def test_check_citation_integrity_returns_none_when_no_review_exists(tmp_path):
    result = check_citation_integrity(tmp_path, "Cites PMID 12345678.")
    assert result is None


def test_check_citation_integrity_flags_pmids_not_in_review(tmp_path):
    turn_started = datetime(2026, 3, 18, 19, 0, 0, tzinfo=timezone.utc)
    _write_review(
        tmp_path,
        created_at="2026-03-18T19:30:00Z",
        source_facts=_supported_source_facts("12345678"),
    )

    result = check_citation_integrity(
        tmp_path,
        "Final answer cites PMID 12345678 and PMID 99999999.",
        turn_started_at=turn_started,
    )

    assert result is not None
    assert result.has_mismatch is True
    assert result.cited_pmids == ["12345678", "99999999"]
    assert result.included_pmids == ["12345678"]
    assert result.missing_pmids == ["99999999"]
    assert result.review_artifact_relpath is not None
    assert result.review_artifact_relpath.startswith("artifacts/evidence-review/")


def test_check_citation_integrity_no_mismatch_when_all_cited_are_included(tmp_path):
    turn_started = datetime(2026, 3, 18, 19, 0, 0, tzinfo=timezone.utc)
    _write_review(
        tmp_path,
        created_at="2026-03-18T19:30:00Z",
        source_facts=_supported_source_facts("12345678"),
    )

    result = check_citation_integrity(
        tmp_path,
        "The evidence comes from PMID 12345678.",
        turn_started_at=turn_started,
    )

    assert result is not None
    assert result.has_mismatch is False
    assert result.missing_pmids == []


def test_check_citation_integrity_prefers_latest_review_from_this_turn(tmp_path):
    turn_started = datetime(2026, 3, 18, 19, 0, 0, tzinfo=timezone.utc)
    old_run_id = "run-20260317T120000Z-0ddabcde"
    new_run_id = "run-20260318T193000Z-aaaaabcd"
    _write_review(
        tmp_path,
        created_at="2026-03-17T12:00:00Z",
        source_facts=_supported_source_facts("11111111", run_id=old_run_id),
        run_id=old_run_id,
        date_dir="2026-03-17",
    )
    _write_review(
        tmp_path,
        created_at="2026-03-18T19:30:00Z",
        source_facts=_supported_source_facts("22222222", run_id=new_run_id),
        run_id=new_run_id,
        date_dir="2026-03-18",
    )

    result = check_citation_integrity(
        tmp_path,
        "See PMID 22222222 for details.",
        turn_started_at=turn_started,
    )

    assert result is not None
    assert result.included_pmids == ["22222222"]
    assert result.has_mismatch is False


def test_check_citation_integrity_ignores_reviews_before_turn_start(tmp_path):
    turn_started = datetime(2026, 3, 18, 19, 0, 0, tzinfo=timezone.utc)
    old_run_id = "run-20260317T120000Z-0ddabcde"
    _write_review(
        tmp_path,
        created_at="2026-03-17T12:00:00Z",
        source_facts=_supported_source_facts("11111111", run_id=old_run_id),
        run_id=old_run_id,
        date_dir="2026-03-17",
    )

    result = check_citation_integrity(
        tmp_path,
        "See PMID 11111111.",
        turn_started_at=turn_started,
    )

    assert result is None


def test_build_citation_mismatch_event_shape():
    from evidence.integrity import CitationIntegrityResult

    result = CitationIntegrityResult(
        cited_pmids=["12345678", "99999999"],
        included_pmids=["12345678"],
        missing_pmids=["99999999"],
        review_artifact_relpath="artifacts/evidence-review/2026-03-18/run/evidence_review.json",
    )
    event = build_citation_mismatch_event(result)

    assert event["type"] == "warning"
    assert event["kind"] == "citation_mismatch"
    assert "PMID 99999999" in event["message"]
    assert event["missing"] == ["99999999"]
    assert event["cited"] == ["12345678", "99999999"]
    assert event["included"] == ["12345678"]
    assert event["review_path"] == (
        "artifacts/evidence-review/2026-03-18/run/evidence_review.json"
    )
