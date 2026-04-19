"""Agent tool for durable PubMed-backed evidence retrieval.

Canonical PubMed entry point (issue #126). Wraps the same NCBI E-utilities
calls as ``ncbi_eutils`` but also persists durable BioAPEX evidence cards and
cached raw PubMed payloads, so it should be preferred whenever the retrieval
output belongs in the evidence-card pipeline. The raw ``ncbi_eutils`` tool is
hidden from the planner helper agent for this reason; use it only when
evidence-card persistence is NOT wanted or for non-PubMed DBs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Type

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel, TypeAdapter

from evidence import EvidenceRetrievalInput, run_evidence_retrieval

from .contracts import (
    artifact_ref,
    empty_result,
    execution_error_result,
    invalid_input_result,
    retriable_error_result,
    success_result,
)

_FAILURE_LIST_ADAPTER = TypeAdapter(list[dict[str, str]])


class EvidenceRetrievalTool(BaseTool):
    name: str = "evidence_retrieval"
    description: str = (
        "Canonical PubMed retrieval tool: searches PubMed with NCBI E-utilities, "
        "fetches authoritative article metadata, and persists durable BioAPEX "
        "evidence cards plus cached raw PubMed payloads. Prefer this over raw "
        "ncbi_eutils for any literature work that should land as an evidence "
        "card. Provide a query, explicit PMIDs, or both."
    )
    args_schema: Type[BaseModel] = EvidenceRetrievalInput
    response_format: str = "content_and_artifact"
    base_dir: str = ""

    def _run(
        self,
        query: str | None = None,
        pmids: list[str] | None = None,
        max_results: int = 5,
        max_evidence_cards: int = 3,
    ) -> tuple[str, dict]:
        try:
            payload = EvidenceRetrievalInput(
                query=query,
                pmids=pmids or [],
                max_results=max_results,
                max_evidence_cards=max_evidence_cards,
            )
        except Exception as exc:
            return invalid_input_result(self.name, str(exc))

        try:
            result = run_evidence_retrieval(Path(self.base_dir or ".").resolve(), payload)
        except httpx.TimeoutException:
            return retriable_error_result(self.name, "PubMed evidence retrieval timed out.")
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
                f"PubMed evidence retrieval failed: {exc}",
                metadata={"request_url": str(exc.request.url) if exc.request is not None else None},
            )
        except Exception as exc:
            return execution_error_result(self.name, str(exc))

        structured_payload = {
            "query": result.query,
            "candidate_records": result.candidate_records,
            "selected_pmids": result.selected_pmids,
            "retrieval_context_run_id": result.persisted_context.run_id if result.persisted_context is not None else None,
            "retrieval_context_path": (
                result.persisted_context.retrieval_context_relpath if result.persisted_context is not None else None
            ),
            "esearch_payload_path": (
                result.persisted_context.esearch_payload_relpath if result.persisted_context is not None else None
            ),
            "esummary_payload_path": (
                result.persisted_context.esummary_payload_relpath if result.persisted_context is not None else None
            ),
            "cards": [
                {
                    "pmid": card.pmid,
                    "title": card.card.title,
                    "stable_identifier": card.card.stable_identifier,
                    "study_type": card.card.study_type,
                    "artifact_path": card.artifact_relpath,
                    "cached_raw_payload_path": card.cached_raw_payload_relpath,
                    "retrieval_context_path": card.retrieval_context_relpath,
                    "esearch_payload_path": card.esearch_payload_relpath,
                    "esummary_payload_path": card.esummary_payload_relpath,
                    "run_id": card.card.run_id,
                    "claim_count": len(card.card.claims),
                    "limitation_count": len(card.card.limitations),
                    "entity_tags": card.card.entity_tags,
                    "grounded_entities": [
                        entity.model_dump(mode="json") for entity in card.card.grounded_entities
                    ],
                    "grounding_results": [
                        result.model_dump(mode="json") for result in card.card.grounding_results
                    ],
                    "grounding_requires_clarification": card.card.grounding_requires_clarification,
                    "entity_grounding_path": card.entity_grounding_relpath,
                }
                for card in result.cards
            ],
            "failures": [
                {"pmid": failure.pmid, "error": failure.error}
                for failure in result.failures
            ],
        }
        metadata = {
            "query_provided": result.query is not None,
            "candidate_count": len(result.candidate_records),
            "selected_pmid_count": len(result.selected_pmids),
            "evidence_card_count": len(result.cards),
            "failure_count": len(result.failures),
        }
        refs = []
        for card in result.cards:
            refs.append(
                artifact_ref(
                    path=str(card.artifact_path),
                    label="evidence_card",
                    artifact_type="evidence_card",
                    identifier=card.card.id,
                )
            )
            refs.append(
                artifact_ref(
                    path=str(card.cached_raw_payload_path),
                    label="cached_pubmed_payload",
                    artifact_type="generated_output",
                    identifier=card.card.stable_identifier,
                )
            )
            if card.retrieval_context_path is not None:
                refs.append(
                    artifact_ref(
                        path=str(card.retrieval_context_path),
                        label="retrieval_context",
                        artifact_type="retrieval_context",
                        identifier=card.card.run_id,
                    )
                )
            if card.esearch_payload_path is not None:
                refs.append(
                    artifact_ref(
                        path=str(card.esearch_payload_path),
                        label="ncbi_esearch_payload",
                        artifact_type="retrieval_search_payload",
                        identifier=card.card.run_id,
                    )
                )
            if card.esummary_payload_path is not None:
                refs.append(
                    artifact_ref(
                        path=str(card.esummary_payload_path),
                        label="ncbi_esummary_payload",
                        artifact_type="retrieval_summary_payload",
                        identifier=card.card.run_id,
                    )
                )
            if card.entity_grounding_path is not None:
                refs.append(
                    artifact_ref(
                        path=str(card.entity_grounding_path),
                        label="entity_grounding",
                        artifact_type="entity_grounding",
                        identifier=card.card.run_id,
                    )
                )

        if result.persisted_context is not None:
            refs.append(
                artifact_ref(
                    path=str(result.persisted_context.retrieval_context_path),
                    label="retrieval_context",
                    artifact_type="retrieval_context",
                    identifier=result.persisted_context.run_id,
                )
            )
            if result.persisted_context.esearch_payload_path is not None:
                refs.append(
                    artifact_ref(
                        path=str(result.persisted_context.esearch_payload_path),
                        label="ncbi_esearch_payload",
                        artifact_type="retrieval_search_payload",
                        identifier=result.persisted_context.run_id,
                    )
                )
            if result.persisted_context.esummary_payload_path is not None:
                refs.append(
                    artifact_ref(
                        path=str(result.persisted_context.esummary_payload_path),
                        label="ncbi_esummary_payload",
                        artifact_type="retrieval_summary_payload",
                        identifier=result.persisted_context.run_id,
                    )
                )

        if not result.cards and not result.failures:
            return empty_result(
                self.name,
                "No PubMed records matched the requested evidence retrieval inputs.",
                structured_payload=structured_payload,
                artifact_refs=refs,
                metadata=metadata,
            )

        if not result.cards and result.failures:
            return execution_error_result(
                self.name,
                "Evidence retrieval did not materialize any evidence cards.",
                structured_payload=structured_payload,
                artifact_refs=refs,
                metadata=metadata,
            )

        summary = (
            f"Retrieved {len(result.cards)} evidence card(s) for PMID(s) "
            f"{', '.join(card.pmid for card in result.cards)}."
        )
        warnings: list[str] = []
        if result.failures:
            warnings.append("partial_retrieval")
            summary += f" Failed PMIDs: {', '.join(failure.pmid for failure in result.failures)}."

        return success_result(
            self.name,
            summary,
            structured_payload=structured_payload,
            artifact_refs=refs,
            warnings=warnings,
            metadata=metadata,
            source_payload={
                "query": result.query,
                "selected_pmids": result.selected_pmids,
                "failures": _FAILURE_LIST_ADAPTER.dump_python(
                    [
                        {"pmid": failure.pmid, "error": failure.error}
                        for failure in result.failures
                    ],
                    mode="json",
                ),
            },
        )
