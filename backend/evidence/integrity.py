"""Citation integrity check for the assembled final-response text.

The check compares PMIDs cited in the assistant's final answer against the PMIDs
recorded on the cards included in the most recent persisted ``evidence_review``
artifact. A mismatch indicates the answer cited a study that was never reviewed
— the runtime surfaces this to the user as a warning block so they can inspect
the claim before trusting it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from artifacts import EvidenceReviewArtifact, load_artifact_document

logger = logging.getLogger(__name__)

# Matches PMID citations in free-form answer text, e.g. "PMID 12345678",
# "PMID: 12345678", "(pmid:12345678)". Also accepts the bare ``pmid:<digits>``
# stable-identifier shape. 4–10 digits covers the real PMID range with room
# to spare.
_ANSWER_PMID_RE = re.compile(r"(?i)\bpmid\s*[:#\-]?\s*(\d{4,10})\b")


@dataclass(frozen=True)
class CitationIntegrityResult:
    """Outcome of comparing cited PMIDs with the evidence review's included PMIDs."""

    cited_pmids: list[str]
    included_pmids: list[str]
    missing_pmids: list[str]
    review_artifact_relpath: str | None

    @property
    def has_mismatch(self) -> bool:
        return bool(self.missing_pmids)


def extract_pmids_from_text(text: str) -> list[str]:
    """Return the ordered, deduplicated list of PMIDs cited in ``text``."""
    if not isinstance(text, str) or not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _ANSWER_PMID_RE.finditer(text):
        pmid = match.group(1)
        if pmid and pmid not in seen:
            seen.add(pmid)
            ordered.append(pmid)
    return ordered


def _pmids_from_review(review: EvidenceReviewArtifact) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for fact in review.source_facts:
        identifier = fact.stable_identifier or ""
        prefix, _, value = identifier.partition(":")
        if prefix.strip().lower() != "pmid":
            continue
        pmid = value.strip()
        if pmid and pmid not in seen:
            seen.add(pmid)
            ordered.append(pmid)
    return ordered


def _iter_review_candidates(base_dir: Path) -> Iterable[Path]:
    reviews_root = base_dir / "artifacts" / "evidence-review"
    if not reviews_root.exists():
        return []
    return reviews_root.rglob("evidence_review.json")


def _find_latest_evidence_review(
    base_dir: Path,
    turn_started_at: datetime | None,
) -> tuple[EvidenceReviewArtifact, str] | None:
    best: tuple[datetime, EvidenceReviewArtifact, Path] | None = None
    for path in _iter_review_candidates(base_dir):
        try:
            artifact = load_artifact_document(path)
        except Exception:
            continue
        if not isinstance(artifact, EvidenceReviewArtifact):
            continue
        created_at = artifact.created_at
        if turn_started_at is not None and created_at < turn_started_at:
            continue
        if best is None or created_at > best[0]:
            best = (created_at, artifact, path)
    if best is None:
        return None
    _, artifact, path = best
    try:
        relpath = path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        relpath = str(path)
    return artifact, relpath


def check_citation_integrity(
    base_dir: Path | str,
    answer_text: str,
    *,
    turn_started_at: datetime | None = None,
) -> CitationIntegrityResult | None:
    """Compare cited PMIDs against the most recent evidence_review for this turn.

    Returns ``None`` when no ``evidence_review`` artifact exists for the turn or
    when any unexpected error is encountered — the check is defensive and must
    never interrupt response delivery.
    """
    try:
        base_path = Path(base_dir)
        if turn_started_at is not None and turn_started_at.tzinfo is None:
            turn_started_at = turn_started_at.replace(tzinfo=timezone.utc)
        found = _find_latest_evidence_review(base_path, turn_started_at)
    except Exception:  # pragma: no cover - defensive
        logger.debug("citation integrity: failed to locate evidence_review", exc_info=True)
        return None

    if found is None:
        return None

    review, relpath = found
    included_pmids = _pmids_from_review(review)
    cited_pmids = extract_pmids_from_text(answer_text)
    included_set = set(included_pmids)
    missing = [pmid for pmid in cited_pmids if pmid not in included_set]
    return CitationIntegrityResult(
        cited_pmids=cited_pmids,
        included_pmids=included_pmids,
        missing_pmids=missing,
        review_artifact_relpath=relpath,
    )


def build_citation_mismatch_event(
    result: CitationIntegrityResult,
) -> dict[str, object]:
    """Construct the runtime ``warning`` event payload for a citation mismatch."""
    missing_display = ", ".join(f"PMID {pmid}" for pmid in result.missing_pmids)
    message = (
        f"Answer cites {missing_display} but the evidence review for this turn "
        "does not include those sources."
    )
    payload: dict[str, object] = {
        "type": "warning",
        "kind": "citation_mismatch",
        "message": message,
        "missing": list(result.missing_pmids),
        "cited": list(result.cited_pmids),
        "included": list(result.included_pmids),
    }
    if result.review_artifact_relpath:
        payload["review_path"] = result.review_artifact_relpath
    return payload
