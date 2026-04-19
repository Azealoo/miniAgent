"""Agent tool for deterministic evidence review over durable evidence cards.

Selection rule vs ``claim_graph`` (issue #126): ``evidence_review`` answers a
single biology question over a curated set of evidence cards and emits one
durable ``evidence_review`` artifact. ``claim_graph`` is a different shape of
output — it aggregates claims across many evidence cards, reviews, and
workflow runs into a multi-artifact graph with contradiction edges, and is
currently not registered in the runtime tool catalog (it remains available as
an internal library entry point via ``evidence.run_claim_graph``). Use
``evidence_review`` for single-question synthesis; reach for ``claim_graph``
only when the task is explicit multi-artifact claim aggregation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Type

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from evidence.review import EvidenceReviewInput, run_evidence_review

from .contracts import (
    artifact_ref,
    empty_result,
    execution_error_result,
    invalid_input_result,
    retriable_error_result,
    success_result,
)


class EvidenceReviewTool(BaseTool):
    name: str = "evidence_review"
    description: str = (
        "Run BioAPEX evidence-review mode for a single biology question. Canonical "
        "tool for answering 'what does the literature say about X?' over one or more "
        "evidence cards. For multi-artifact claim aggregation across many reviews and "
        "workflow runs with contradiction detection, use claim_graph (library entry "
        "point). The tool can reuse existing evidence_card artifacts or retrieve "
        "PubMed-backed evidence cards, then emits a durable evidence_review artifact "
        "that separates extracted source facts from synthesized conclusions and marks "
        "unsupported claims explicitly."
    )
    args_schema: Type[BaseModel] = EvidenceReviewInput
    response_format: str = "content_and_artifact"
    base_dir: str = ""

    def _run(
        self,
        question: str,
        query: str | None = None,
        pmids: list[str] | None = None,
        evidence_card_paths: list[str] | None = None,
        max_results: int = 5,
        max_evidence_cards: int = 3,
    ) -> tuple[str, dict]:
        try:
            payload = EvidenceReviewInput(
                question=question,
                query=query,
                pmids=pmids or [],
                evidence_card_paths=evidence_card_paths or [],
                max_results=max_results,
                max_evidence_cards=max_evidence_cards,
            )
        except Exception as exc:
            return invalid_input_result(self.name, str(exc))

        try:
            result = run_evidence_review(Path(self.base_dir or ".").resolve(), payload)
        except httpx.TimeoutException:
            return retriable_error_result(self.name, "Evidence review retrieval timed out.")
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            message = f"HTTP {status_code}: {exc.response.reason_phrase}"
            metadata = {
                "http_status": status_code,
                "request_url": str(exc.request.url),
            }
            if status_code == 429 or status_code >= 500:
                return retriable_error_result(self.name, message, metadata=metadata)
            if 400 <= status_code < 500:
                return invalid_input_result(self.name, message, metadata=metadata)
            return execution_error_result(self.name, message, metadata=metadata)
        except httpx.RequestError as exc:
            return retriable_error_result(
                self.name,
                f"Evidence review retrieval failed: {exc}",
                metadata={"request_url": str(exc.request.url) if exc.request is not None else None},
            )
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

        review = result.review
        structured_payload = {
            "question": review.review_question,
            "review_status": review.review_status,
            "confidence": review.confidence,
            "unsupported_claims_present": review.unsupported_claims_present,
            "artifact_path": result.artifact_relpath,
            "evidence_included": [item.model_dump(mode="json") for item in review.evidence_included],
            "evidence_excluded": [item.model_dump(mode="json") for item in review.evidence_excluded],
            "limitations": review.limitations,
            "unresolved_conflicts": review.unresolved_conflicts,
            "source_facts": [item.model_dump(mode="json") for item in review.source_facts],
            "synthesized_conclusions": [
                item.model_dump(mode="json") for item in review.synthesized_conclusions
            ],
        }
        metadata = {
            "review_status": review.review_status,
            "confidence": review.confidence,
            "included_evidence_count": len(review.evidence_included),
            "excluded_evidence_count": len(review.evidence_excluded),
            "source_fact_count": len(review.source_facts),
            "conclusion_count": len(review.synthesized_conclusions),
            "unsupported_claims_present": review.unsupported_claims_present,
            "artifact_path": result.artifact_relpath,
        }

        refs = [
            artifact_ref(
                path=str(result.artifact_path),
                label="evidence_review",
                artifact_type="evidence_review",
                identifier=review.id,
            )
        ]
        for ref in review.evidence_included:
            refs.append(
                artifact_ref(
                    path=ref.path,
                    label="evidence_card",
                    artifact_type=ref.artifact_type,
                    identifier=ref.id,
                )
            )
        for ref in review.related_artifacts:
            refs.append(
                artifact_ref(
                    path=ref.path,
                    label=ref.artifact_type,
                    artifact_type=ref.artifact_type,
                    identifier=ref.id,
                )
            )

        warnings: list[str] = []
        if review.unsupported_claims_present:
            warnings.append("unsupported_claims_present")
        if review.unresolved_conflicts:
            warnings.append("unresolved_conflicts")
        if any(card.card.grounding_requires_clarification for card in result.included_cards):
            warnings.append("grounding_clarification_required")

        summary = (
            f"Reviewed {len(review.evidence_included)} evidence card(s); "
            f"support status: {review.review_status.replace('_', ' ')}; "
            f"confidence: {review.confidence}."
        )

        if not review.evidence_included:
            return empty_result(
                self.name,
                summary,
                structured_payload=structured_payload,
                artifact_refs=refs,
                warnings=warnings + ["no_evidence_included"],
                metadata=metadata,
            )

        return success_result(
            self.name,
            summary,
            structured_payload=structured_payload,
            artifact_refs=refs,
            warnings=warnings,
            metadata=metadata,
        )
