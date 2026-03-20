"""Deterministic evidence review flow built on durable evidence cards."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from artifacts import (
    ArtifactReference,
    EvidenceCard,
    EvidenceReviewArtifact,
    SCHEMA_PACK_VERSION,
    build_content_hash_manifest,
    load_artifact_document,
    normalize_identifier,
    prepare_run_directory,
    resolve_artifact_path,
)
from artifacts.schemas import (
    EvidenceReviewConclusion,
    EvidenceReviewSourceFact,
    ExcludedEvidenceItem,
)

from .retrieval import (
    EvidenceRetrievalFailure,
    EvidenceRetrievalInput,
    EvidenceRetrievalResult,
    RetrievedEvidenceCard,
    run_evidence_retrieval,
)

EVIDENCE_REVIEW_WORKFLOW_NAME = "evidence-review"
_PMID_RE = re.compile(r"^\d+$")


def _normalize_relative_path(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Paths must not be empty.")
    if "\\" in raw:
        raise ValueError("Paths must use forward slashes.")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise ValueError("Paths must be relative, not absolute.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("Paths must not contain '..'.")
    if candidate.parts == (".",):
        raise ValueError("Paths must not resolve to '.'.")
    return str(candidate)


class EvidenceReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    query: str | None = None
    pmids: list[str] = Field(default_factory=list)
    evidence_card_paths: list[str] = Field(default_factory=list)
    max_results: int = 5
    max_evidence_cards: int = 3

    @field_validator("question")
    @classmethod
    def _validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be empty.")
        return cleaned

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("pmids")
    @classmethod
    def _validate_pmids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate = item.strip()
            if not candidate:
                continue
            if not _PMID_RE.fullmatch(candidate):
                raise ValueError(f"Invalid PMID: {item!r}")
            if candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        return cleaned

    @field_validator("evidence_card_paths")
    @classmethod
    def _validate_evidence_card_paths(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = _normalize_relative_path(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)
        return cleaned

    @field_validator("max_results")
    @classmethod
    def _validate_max_results(cls, value: int) -> int:
        if value < 1 or value > 20:
            raise ValueError("max_results must be between 1 and 20.")
        return value

    @field_validator("max_evidence_cards")
    @classmethod
    def _validate_max_evidence_cards(cls, value: int) -> int:
        if value < 1 or value > 10:
            raise ValueError("max_evidence_cards must be between 1 and 10.")
        return value


@dataclass(frozen=True)
class EvidenceReviewCardRecord:
    card: EvidenceCard
    artifact_path: Path
    artifact_relpath: str

    @property
    def artifact_ref(self) -> ArtifactReference:
        return ArtifactReference(
            artifact_type="evidence_card",
            path=self.artifact_relpath,
            id=self.card.id,
            run_id=self.card.run_id,
        )


@dataclass(frozen=True)
class EvidenceReviewResult:
    review: EvidenceReviewArtifact
    artifact_path: Path
    artifact_relpath: str
    included_cards: list[EvidenceReviewCardRecord]
    excluded_evidence: list[ExcludedEvidenceItem]
    retrieval_result: EvidenceRetrievalResult | None = None


def run_evidence_review(
    base_dir: Path | str,
    payload: EvidenceReviewInput,
) -> EvidenceReviewResult:
    base_path = Path(base_dir).resolve()
    explicit_cards = _load_explicit_evidence_cards(base_path, payload.evidence_card_paths)
    retrieved_cards: list[EvidenceReviewCardRecord] = []
    retrieval_result: EvidenceRetrievalResult | None = None

    should_retrieve = bool(payload.query or payload.pmids or not explicit_cards)
    if should_retrieve:
        retrieval_result = run_evidence_retrieval(
            base_path,
            EvidenceRetrievalInput(
                query=payload.query or payload.question,
                pmids=payload.pmids,
                max_results=payload.max_results,
                max_evidence_cards=payload.max_evidence_cards,
            ),
        )
        retrieved_cards = [
            EvidenceReviewCardRecord(
                card=record.card,
                artifact_path=record.artifact_path,
                artifact_relpath=record.artifact_relpath,
            )
            for record in retrieval_result.cards
        ]

    candidate_cards = _dedupe_cards(explicit_cards + retrieved_cards)
    included_cards, excluded_evidence = _partition_cards(
        candidate_cards,
        max_evidence_cards=payload.max_evidence_cards,
    )
    if retrieval_result is not None:
        excluded_evidence.extend(_excluded_from_failures(retrieval_result.failures))

    source_facts = _build_source_facts(included_cards)
    limitations = _build_limitations(included_cards, retrieval_result=retrieval_result)
    unresolved_conflicts = _detect_unresolved_conflicts(source_facts)
    review_status, confidence = _review_status(
        included_cards,
        unresolved_conflicts=unresolved_conflicts,
    )
    synthesized_conclusions = _build_conclusions(
        payload.question,
        included_cards,
        source_facts=source_facts,
        review_status=review_status,
        confidence=confidence,
        limitations=limitations,
        unresolved_conflicts=unresolved_conflicts,
    )

    layout = prepare_run_directory(base_path, EVIDENCE_REVIEW_WORKFLOW_NAME)
    review = EvidenceReviewArtifact.model_validate(
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "evidence_review",
            "id": normalize_identifier(f"evidence-review-{layout.run_id}"),
            "run_id": layout.run_id,
            "created_at": layout.created_at,
            "source_workflow": EVIDENCE_REVIEW_WORKFLOW_NAME,
            "related_artifacts": [
                ref.model_dump(mode="json")
                for ref in _collect_related_artifacts(
                    included_cards,
                    excluded_evidence=excluded_evidence,
                    retrieval_result=retrieval_result,
                )
            ],
            "review_question": payload.question,
            "review_status": review_status,
            "confidence": confidence,
            "evidence_included": [
                record.artifact_ref.model_dump(mode="json") for record in included_cards
            ],
            "evidence_excluded": [
                item.model_dump(mode="json") for item in excluded_evidence
            ],
            "limitations": limitations,
            "unresolved_conflicts": unresolved_conflicts,
            "source_facts": [
                fact.model_dump(mode="json") for fact in source_facts
            ],
            "synthesized_conclusions": [
                conclusion.model_dump(mode="json") for conclusion in synthesized_conclusions
            ],
            "unsupported_claims_present": review_status != "supported",
        }
    )

    artifact_path = layout.stable_artifact_path("evidence_review")
    artifact_relpath = layout.stable_artifact_relpath("evidence_review").as_posix()
    artifact_path.write_text(
        json.dumps(review.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_content_hash_manifest(layout)

    return EvidenceReviewResult(
        review=review,
        artifact_path=artifact_path,
        artifact_relpath=artifact_relpath,
        included_cards=included_cards,
        excluded_evidence=excluded_evidence,
        retrieval_result=retrieval_result,
    )


def _load_explicit_evidence_cards(
    base_path: Path,
    evidence_card_paths: list[str],
) -> list[EvidenceReviewCardRecord]:
    records: list[EvidenceReviewCardRecord] = []
    for relative_path in evidence_card_paths:
        resolved = resolve_artifact_path(base_path, relative_path)
        artifact = load_artifact_document(resolved)
        if not isinstance(artifact, EvidenceCard):
            raise ValueError(f"{relative_path!r} is not an evidence_card artifact.")
        records.append(
            EvidenceReviewCardRecord(
                card=artifact,
                artifact_path=resolved,
                artifact_relpath=Path(relative_path).as_posix(),
            )
        )
    return records


def _dedupe_cards(records: list[EvidenceReviewCardRecord]) -> list[EvidenceReviewCardRecord]:
    deduped: list[EvidenceReviewCardRecord] = []
    seen: set[str] = set()
    for record in records:
        key = record.card.stable_identifier.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _partition_cards(
    records: list[EvidenceReviewCardRecord],
    *,
    max_evidence_cards: int,
) -> tuple[list[EvidenceReviewCardRecord], list[ExcludedEvidenceItem]]:
    included = records[:max_evidence_cards]
    overflow = records[max_evidence_cards:]
    excluded = [
        ExcludedEvidenceItem(
            evidence_id=record.card.stable_identifier,
            artifact=record.artifact_ref,
            reason=(
                f"Evidence was available but excluded because the review limit was "
                f"{max_evidence_cards} evidence card(s) for this turn."
            ),
        )
        for record in overflow
    ]
    return included, excluded


def _excluded_from_failures(
    failures: list[EvidenceRetrievalFailure],
) -> list[ExcludedEvidenceItem]:
    return [
        ExcludedEvidenceItem(
            evidence_id=f"pmid:{failure.pmid}",
            reason=f"Retrieval failed before an evidence card could be materialized: {failure.error}",
        )
        for failure in failures
    ]


def _build_source_facts(
    records: list[EvidenceReviewCardRecord],
) -> list[EvidenceReviewSourceFact]:
    facts: list[EvidenceReviewSourceFact] = []
    for record in records:
        evidence_ref = record.artifact_ref
        for claim in record.card.claims:
            facts.append(
                EvidenceReviewSourceFact(
                    statement=claim.statement,
                    claim_id=claim.id,
                    stable_identifier=record.card.stable_identifier,
                    evidence=evidence_ref,
                    confidence=claim.confidence,
                )
            )
    return facts


def _build_limitations(
    records: list[EvidenceReviewCardRecord],
    *,
    retrieval_result: EvidenceRetrievalResult | None,
) -> list[str]:
    limitations: list[str] = []
    for record in records:
        limitations.extend(record.card.limitations)
        if record.card.grounding_requires_clarification:
            limitations.append(
                f"{record.card.stable_identifier} contains ambiguous grounded entities that may require clarification."
            )
    if retrieval_result is not None and retrieval_result.failures:
        limitations.append(
            "Some requested evidence records could not be materialized deterministically and were excluded."
        )
    if not records:
        limitations.append(
            "No adequate evidence cards were available for review, so unsupported claims must remain explicit."
        )
    return _dedupe_text(limitations)


def _detect_unresolved_conflicts(
    source_facts: list[EvidenceReviewSourceFact],
) -> list[str]:
    conflicts: list[str] = []
    grouped: dict[str, set[str]] = {}
    for fact in source_facts:
        key_terms = _fact_key(fact.statement)
        if key_terms is None:
            continue
        grouped.setdefault(key_terms, set()).add(_fact_polarity(fact.statement))
    for key_terms, polarities in grouped.items():
        if {"positive", "negative"} <= polarities:
            conflicts.append(
                f"Retrieved source facts disagreed on {key_terms.replace('|', ' ')} and were left unresolved."
            )
    return _dedupe_text(conflicts)


def _fact_key(statement: str) -> str | None:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "by",
        "for",
        "in",
        "is",
        "of",
        "or",
        "the",
        "to",
        "was",
        "were",
        "with",
    }
    tokens = [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", statement.casefold()).split()
        if token and token not in stopwords
    ]
    if len(tokens) < 3:
        return None
    return "|".join(tokens[:4])


def _fact_polarity(statement: str) -> str:
    lowered = statement.casefold()
    negative_markers = ("no ", "not ", "failed to", "did not", "without ", "lack of")
    if any(marker in lowered for marker in negative_markers):
        return "negative"
    return "positive"


def _review_status(
    records: list[EvidenceReviewCardRecord],
    *,
    unresolved_conflicts: list[str],
) -> tuple[str, str]:
    if not records:
        return "insufficient_evidence", "low"
    if unresolved_conflicts:
        return "mixed", "medium" if len(records) > 1 else "low"
    if any(record.card.confidence == "low" for record in records):
        return "mixed", "medium" if len(records) > 1 else "low"
    if any(record.card.grounding_requires_clarification for record in records):
        return "mixed", "medium"
    if len(records) >= 2 and all(record.card.confidence == "high" for record in records):
        return "supported", "high"
    return "supported", "medium"


def _build_conclusions(
    question: str,
    records: list[EvidenceReviewCardRecord],
    *,
    source_facts: list[EvidenceReviewSourceFact],
    review_status: str,
    confidence: str,
    limitations: list[str],
    unresolved_conflicts: list[str],
) -> list[EvidenceReviewConclusion]:
    supporting_evidence = [record.artifact_ref for record in records]
    if review_status == "supported":
        if source_facts:
            statement = (
                f"For the review question '{question}', the retrieved evidence supports a "
                f"{confidence}-confidence conclusion consistent with the included source facts."
            )
        else:
            statement = (
                f"For the review question '{question}', retrieved evidence was available and "
                f"supports a {confidence}-confidence conclusion."
            )
    elif review_status == "mixed":
        statement = (
            f"For the review question '{question}', the retrieved evidence remains mixed or "
            "context-dependent, so unsupported claims should stay explicitly provisional."
        )
    else:
        statement = (
            f"For the review question '{question}', adequate evidence was not found to support "
            "a confident conclusion."
        )

    return [
        EvidenceReviewConclusion(
            statement=statement,
            support_status=review_status,
            confidence=confidence,
            supporting_evidence=supporting_evidence,
            limitation_notes=limitations,
            conflict_notes=unresolved_conflicts,
        )
    ]


def _collect_related_artifacts(
    records: list[EvidenceReviewCardRecord],
    *,
    excluded_evidence: list[ExcludedEvidenceItem],
    retrieval_result: EvidenceRetrievalResult | None,
) -> list[ArtifactReference]:
    refs: list[ArtifactReference] = []
    seen: set[tuple[str, str]] = set()

    def _append(ref: ArtifactReference) -> None:
        key = (ref.artifact_type, ref.path)
        if key in seen:
            return
        seen.add(key)
        refs.append(ref)

    for record in records:
        _append(record.artifact_ref)
        for related in record.card.related_artifacts:
            _append(related)

    for excluded in excluded_evidence:
        if excluded.artifact is not None:
            _append(excluded.artifact)

    if retrieval_result is not None and retrieval_result.persisted_context is not None:
        _append(
            ArtifactReference(
                artifact_type="retrieval_context",
                path=retrieval_result.persisted_context.retrieval_context_relpath,
                run_id=retrieval_result.persisted_context.run_id,
            )
        )
        if retrieval_result.persisted_context.esearch_payload_relpath is not None:
            _append(
                ArtifactReference(
                    artifact_type="retrieval_search_payload",
                    path=retrieval_result.persisted_context.esearch_payload_relpath,
                    run_id=retrieval_result.persisted_context.run_id,
                )
            )
        if retrieval_result.persisted_context.esummary_payload_relpath is not None:
            _append(
                ArtifactReference(
                    artifact_type="retrieval_summary_payload",
                    path=retrieval_result.persisted_context.esummary_payload_relpath,
                    run_id=retrieval_result.persisted_context.run_id,
                )
            )

    return refs


def _dedupe_text(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


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
