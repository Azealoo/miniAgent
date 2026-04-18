"""Deterministic PubMed-backed evidence retrieval and artifact persistence."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artifacts import (
    ArtifactReference,
    EvidenceCard,
    SCHEMA_PACK_VERSION,
    build_content_hash_manifest,
    load_artifact_document,
    normalize_identifier,
    prepare_run_directory,
)
from entity_grounding import (
    EntityGroundingMentionRequest,
    materialize_entity_grounding_requests,
)
from tools.ncbi_eutils_tool import fetch_ncbi_eutils_response

EVIDENCE_RETRIEVAL_WORKFLOW_NAME = "literature-retrieval"
PUBMED_SOURCE_DATABASE = "pubmed"
PUBMED_URL_TEMPLATE = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
_PMID_RE = re.compile(r"^\d+$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CLAIM_KEYWORDS = ("show", "shows", "showed", "demonstrate", "demonstrates", "reveals", "found", "suggest")
_LIMITATION_KEYWORDS = (
    "limitation",
    "limitations",
    "however",
    "although",
    "while",
    "may",
    "might",
    "small sample",
    "further study",
    "future study",
)
_STUDY_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("systematic review", "systematic_review"),
    ("meta-analysis", "meta_analysis"),
    ("randomized controlled trial", "randomized_controlled_trial"),
    ("clinical trial", "clinical_trial"),
    ("case report", "case_report"),
    ("review", "review_article"),
    ("protocol", "study_protocol"),
    ("observational study", "observational_study"),
)
_GENE_SYMBOL_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,23}$")
_ENSEMBL_ENTITY_ID_RE = re.compile(r"^ENS[A-Z0-9]*[GTP]\d+(?:\.\d+)?$", re.IGNORECASE)
_UNIPROT_ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-\d+)?$",
    re.IGNORECASE,
)
_UNIPROT_ENTRY_NAME_RE = re.compile(r"^[A-Z0-9]{1,10}_[A-Z0-9]{1,10}$", re.IGNORECASE)
_MESH_SPECIES_TO_GROUNDING_SPECIES: dict[str, str] = {
    "human": "human",
    "humans": "human",
    "homo sapiens": "human",
    "mouse": "mouse",
    "mice": "mouse",
    "mus musculus": "mouse",
    "rat": "rat",
    "rats": "rat",
    "rattus norvegicus": "rat",
}
_GENERIC_GROUNDING_LABELS = {
    "adult",
    "adults",
    "adolescent",
    "aged",
    "animal",
    "animals",
    "child",
    "children",
    "female",
    "human",
    "humans",
    "infant",
    "male",
    "mice",
    "middle aged",
    "mouse",
    "pregnancy",
    "rat",
    "rats",
    "young adult",
}
_PROTEIN_GROUNDING_KEYWORDS = (
    "antigen",
    "channel",
    "cyclin",
    "enzyme",
    "factor",
    "interleukin",
    "kinase",
    "ligase",
    "myosin",
    "peptide",
    "phosphatase",
    "protein",
    "receptor",
    "transferase",
    "transporter",
)


class EvidenceRetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    pmids: list[str] = Field(default_factory=list)
    max_results: int = 5
    max_evidence_cards: int = 3

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
            pmid = item.strip()
            if not pmid:
                continue
            if not _PMID_RE.fullmatch(pmid):
                raise ValueError(f"Invalid PMID: {item!r}")
            if pmid in seen:
                continue
            seen.add(pmid)
            cleaned.append(pmid)
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

    @model_validator(mode="after")
    def _validate_inputs(self) -> "EvidenceRetrievalInput":
        if self.query is None and not self.pmids:
            raise ValueError("Provide a PubMed query or at least one PMID.")
        return self


@dataclass(frozen=True)
class RetrievedEvidenceCard:
    pmid: str
    card: EvidenceCard
    artifact_path: Path
    artifact_relpath: str
    cached_raw_payload_path: Path
    cached_raw_payload_relpath: str
    retrieval_context_path: Path | None = None
    retrieval_context_relpath: str | None = None
    esearch_payload_path: Path | None = None
    esearch_payload_relpath: str | None = None
    esummary_payload_path: Path | None = None
    esummary_payload_relpath: str | None = None
    entity_grounding_path: Path | None = None
    entity_grounding_relpath: str | None = None


@dataclass(frozen=True)
class EvidenceRetrievalFailure:
    pmid: str
    error: str


@dataclass(frozen=True)
class PersistedRetrievalContext:
    run_id: str
    retrieval_context_path: Path
    retrieval_context_relpath: str
    esearch_payload_path: Path | None = None
    esearch_payload_relpath: str | None = None
    esummary_payload_path: Path | None = None
    esummary_payload_relpath: str | None = None


@dataclass(frozen=True)
class RetrievalContextSnapshot:
    query: str | None
    candidate_records: list[dict[str, Any]]
    selected_pmids: list[str]
    esearch_request_url: str | None
    esummary_request_url: str | None
    esearch_response_text: str | None
    esummary_response_text: str | None


@dataclass(frozen=True)
class EvidenceRetrievalResult:
    query: str | None
    candidate_records: list[dict[str, Any]]
    selected_pmids: list[str]
    cards: list[RetrievedEvidenceCard]
    failures: list[EvidenceRetrievalFailure]
    persisted_context: PersistedRetrievalContext | None = None


def run_evidence_retrieval(
    base_dir: Path | str,
    payload: EvidenceRetrievalInput,
) -> EvidenceRetrievalResult:
    base_path = Path(base_dir).resolve()

    searched_pmids: list[str] = []
    esearch_request_url: str | None = None
    esearch_response_text: str | None = None
    if payload.query:
        search_response = fetch_ncbi_eutils_response(
            operation="esearch",
            db=PUBMED_SOURCE_DATABASE,
            term=payload.query,
            retmax=payload.max_results,
            retmode="json",
        )
        esearch_request_url = search_response.url
        esearch_response_text = search_response.text
        searched_pmids = _extract_search_pmids(search_response.json_payload)

    selected_pmids = _dedupe_preserving_order([*payload.pmids, *searched_pmids])[: payload.max_evidence_cards]
    if not selected_pmids:
        retrieval_context = RetrievalContextSnapshot(
            query=payload.query,
            candidate_records=[],
            selected_pmids=[],
            esearch_request_url=esearch_request_url,
            esummary_request_url=None,
            esearch_response_text=esearch_response_text,
            esummary_response_text=None,
        )
        return EvidenceRetrievalResult(
            query=payload.query,
            candidate_records=[],
            selected_pmids=[],
            cards=[],
            failures=[],
            persisted_context=_materialize_retrieval_context_run(base_path, retrieval_context, selected_pmid=None),
        )

    summary_pmids = _dedupe_preserving_order([*searched_pmids, *selected_pmids])
    summary_by_pmid: dict[str, dict[str, Any]] = {}
    esummary_request_url: str | None = None
    esummary_response_text: str | None = None
    if summary_pmids:
        summary_by_pmid, esummary_request_url, esummary_response_text = _fetch_summary_map(summary_pmids)
    searched_set = set(searched_pmids)
    explicit_set = set(payload.pmids)
    selected_set = set(selected_pmids)
    candidate_records = [
        _build_candidate_record(
            pmid,
            summary_by_pmid.get(pmid),
            from_query=pmid in searched_set,
            from_explicit_pmids=pmid in explicit_set,
            selected=pmid in selected_set,
        )
        for pmid in summary_pmids
    ]
    retrieval_context = RetrievalContextSnapshot(
        query=payload.query,
        candidate_records=candidate_records,
        selected_pmids=selected_pmids,
        esearch_request_url=esearch_request_url,
        esummary_request_url=esummary_request_url,
        esearch_response_text=esearch_response_text,
        esummary_response_text=esummary_response_text,
    )

    cards: list[RetrievedEvidenceCard] = []
    failures: list[EvidenceRetrievalFailure] = []
    for pmid in selected_pmids:
        try:
            article = _fetch_pubmed_article(
                pmid,
                summary_record=summary_by_pmid.get(pmid),
            )
            prior_versions = _find_prior_evidence_versions(base_path, f"pmid:{pmid}")
            cards.append(
                _materialize_evidence_card(
                    base_path,
                    pmid=pmid,
                    article=article,
                    prior_versions=prior_versions,
                    retrieval_context=retrieval_context,
                )
            )
        except Exception as exc:
            failures.append(EvidenceRetrievalFailure(pmid=pmid, error=str(exc)))

    persisted_context = None
    if not cards:
        persisted_context = _materialize_retrieval_context_run(base_path, retrieval_context, selected_pmid=None)

    return EvidenceRetrievalResult(
        query=payload.query,
        candidate_records=candidate_records,
        selected_pmids=selected_pmids,
        cards=cards,
        failures=failures,
        persisted_context=persisted_context,
    )


def _extract_search_pmids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    result = payload.get("esearchresult")
    if not isinstance(result, dict):
        return []
    id_list = result.get("idlist")
    if not isinstance(id_list, list):
        return []
    return [str(item).strip() for item in id_list if str(item).strip()]


def _fetch_summary_map(pmids: list[str]) -> dict[str, dict[str, Any]]:
    if not pmids:
        return {}, None, None
    response = fetch_ncbi_eutils_response(
        operation="esummary",
        db=PUBMED_SOURCE_DATABASE,
        id=",".join(pmids),
        retmode="json",
    )
    payload = response.json_payload
    if not isinstance(payload, dict):
        return {}, response.url, response.text
    result = payload.get("result")
    if not isinstance(result, dict):
        return {}, response.url, response.text
    summary_map: dict[str, dict[str, Any]] = {}
    for pmid in pmids:
        record = result.get(str(pmid))
        if isinstance(record, dict):
            summary_map[pmid] = record
    return summary_map, response.url, response.text


def _build_candidate_record(
    pmid: str,
    summary_record: dict[str, Any] | None,
    *,
    from_query: bool,
    from_explicit_pmids: bool,
    selected: bool,
) -> dict[str, Any]:
    summary = summary_record or {}
    return {
        "pmid": pmid,
        "title": _clean_optional_text(summary.get("title")) or f"PMID {pmid}",
        "journal": _clean_optional_text(summary.get("fulljournalname")) or _clean_optional_text(summary.get("source")),
        "pubdate": _clean_optional_text(summary.get("pubdate")),
        "url": PUBMED_URL_TEMPLATE.format(pmid=pmid),
        "from_query": from_query,
        "from_explicit_pmids": from_explicit_pmids,
        "selected": selected,
    }


def _fetch_pubmed_article(
    pmid: str,
    *,
    summary_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = fetch_ncbi_eutils_response(
        operation="efetch",
        db=PUBMED_SOURCE_DATABASE,
        id=pmid,
        retmode="xml",
    )
    article = _parse_pubmed_article_xml(response.text, pmid=pmid)
    summary = summary_record or {}
    if not article["title"]:
        article["title"] = _clean_optional_text(summary.get("title")) or f"PMID {pmid}"
    if not article["journal"]:
        article["journal"] = _clean_optional_text(summary.get("fulljournalname")) or _clean_optional_text(summary.get("source"))
    if not article["pubdate"]:
        article["pubdate"] = _clean_optional_text(summary.get("pubdate"))
    article["raw_xml"] = response.text
    return article


def _parse_pubmed_article_xml(xml_text: str, *, pmid: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    article_node = root.find(".//PubmedArticle")
    if article_node is None:
        raise ValueError(f"PubMed article {pmid} did not contain a PubmedArticle record.")

    medline = article_node.find("./MedlineCitation")
    article = medline.find("./Article") if medline is not None else None
    if article is None:
        raise ValueError(f"PubMed article {pmid} did not contain an Article payload.")

    title = _collapse_xml_text(article.find("./ArticleTitle"))
    abstract_sections = article.findall("./Abstract/AbstractText")
    abstract = _join_abstract_sections(abstract_sections)
    publication_types = [
        _collapse_xml_text(node)
        for node in article.findall("./PublicationTypeList/PublicationType")
        if _collapse_xml_text(node)
    ]
    mesh_terms = []
    if medline is not None:
        for descriptor in medline.findall("./MeshHeadingList/MeshHeading/DescriptorName"):
            label = _collapse_xml_text(descriptor)
            if not label:
                continue
            mesh_terms.append(
                {
                    "label": label,
                    "identifier": f"mesh:{descriptor.attrib['UI']}" if descriptor.attrib.get("UI") else None,
                }
            )

    journal = _collapse_xml_text(article.find("./Journal/Title"))
    pubdate = _extract_pubdate(article)

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "journal": journal,
        "pubdate": pubdate,
        "publication_types": publication_types,
        "mesh_terms": mesh_terms,
    }


def _collapse_xml_text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    parts = [" ".join(text.split()) for text in node.itertext() if text and text.strip()]
    collapsed = " ".join(part for part in parts if part).strip()
    return collapsed or None


def _join_abstract_sections(sections: list[ET.Element]) -> str:
    parts: list[str] = []
    for section in sections:
        text = _collapse_xml_text(section)
        if not text:
            continue
        label = section.attrib.get("Label") or section.attrib.get("NlmCategory")
        if label and label.lower() not in {"unassigned", "abstract"}:
            parts.append(f"{label}: {text}")
        else:
            parts.append(text)
    return " ".join(parts).strip()


def _extract_pubdate(article: ET.Element) -> str | None:
    pub_date = article.find("./Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None

    year = _collapse_xml_text(pub_date.find("./Year"))
    month = _collapse_xml_text(pub_date.find("./Month"))
    day = _collapse_xml_text(pub_date.find("./Day"))
    medline_date = _collapse_xml_text(pub_date.find("./MedlineDate"))
    if medline_date:
        return medline_date
    pieces = [piece for piece in (year, month, day) if piece]
    return " ".join(pieces) if pieces else None


def _materialize_evidence_card(
    base_path: Path,
    *,
    pmid: str,
    article: dict[str, Any],
    prior_versions: list[ArtifactReference],
    retrieval_context: RetrievalContextSnapshot,
) -> RetrievedEvidenceCard:
    claims = _extract_claims(article["abstract"], pmid=pmid, title=article["title"])
    limitations = _extract_limitations(article["abstract"])
    study_type = _infer_study_type(
        article["publication_types"],
        title=article["title"],
        abstract=article["abstract"],
    )
    entity_tags = _extract_entity_tags(article["mesh_terms"])
    confidence = _overall_confidence(claims, abstract_present=bool(article["abstract"]))

    layout = prepare_run_directory(base_path, EVIDENCE_RETRIEVAL_WORKFLOW_NAME)
    raw_cache_path = layout.generated_output_path(f"pmid-{pmid}.xml", step="source-cache")
    raw_cache_path.write_text(article["raw_xml"], encoding="utf-8")
    raw_cache_relpath = layout.generated_output_relpath(f"pmid-{pmid}.xml", step="source-cache").as_posix()
    context_refs, persisted_context_paths = _persist_retrieval_context(
        layout,
        retrieval_context,
        selected_pmid=pmid,
    )
    grounding_artifact = None
    grounding_ref: list[ArtifactReference] = []
    grounded_entities: list[dict[str, Any]] = []
    grounding_results: list[dict[str, Any]] = []
    grounding_requires_clarification = False
    grounding_species = _infer_grounding_species(entity_tags)
    grounding_requests = _extract_grounding_requests(entity_tags)
    if grounding_requests:
        grounding_artifact = materialize_entity_grounding_requests(
            layout,
            mention_requests=grounding_requests,
            species=grounding_species,
        )
        grounding_ref = [
            ArtifactReference(
                artifact_type="entity_grounding",
                path=grounding_artifact.artifact_relpath,
                id=grounding_artifact.artifact.id,
                run_id=grounding_artifact.artifact.run_id,
            )
        ]
        grounded_entities = [
            entity.model_dump(mode="json")
            for entity in grounding_artifact.resolved_entities
        ]
        grounding_results = [
            result.model_dump(mode="json")
            for result in grounding_artifact.artifact.results
        ]
        grounding_requires_clarification = grounding_artifact.artifact.requires_clarification

    card = EvidenceCard.model_validate(
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "evidence_card",
            "id": normalize_identifier(f"evidence-pmid-{pmid}-{layout.run_id}"),
            "run_id": layout.run_id,
            "created_at": layout.created_at,
            "source_workflow": EVIDENCE_RETRIEVAL_WORKFLOW_NAME,
            "related_artifacts": [
                ref.model_dump(mode="json")
                for ref in [*prior_versions, *context_refs, *grounding_ref]
            ],
            "source_database": PUBMED_SOURCE_DATABASE,
            "stable_identifier": f"pmid:{pmid}",
            "title": article["title"],
            "study_type": study_type,
            "claims": claims,
            "confidence": confidence,
            "limitations": limitations,
            "entity_tags": entity_tags,
            "grounded_entities": grounded_entities,
            "grounding_results": grounding_results,
            "grounding_requires_clarification": grounding_requires_clarification,
            "cached_raw_payload_path": raw_cache_relpath,
        }
    )
    card_payload = yaml.safe_dump(card.model_dump(mode="json"), sort_keys=False, allow_unicode=False)
    artifact_path = layout.stable_artifact_path("evidence_card")
    artifact_path.write_text(card_payload, encoding="utf-8")
    _refresh_content_hash_manifest(layout)

    return RetrievedEvidenceCard(
        pmid=pmid,
        card=card,
        artifact_path=artifact_path,
        artifact_relpath=layout.stable_artifact_relpath("evidence_card").as_posix(),
        cached_raw_payload_path=raw_cache_path,
        cached_raw_payload_relpath=raw_cache_relpath,
        retrieval_context_path=persisted_context_paths["retrieval_context_path"],
        retrieval_context_relpath=persisted_context_paths["retrieval_context_relpath"],
        esearch_payload_path=persisted_context_paths["esearch_payload_path"],
        esearch_payload_relpath=persisted_context_paths["esearch_payload_relpath"],
        esummary_payload_path=persisted_context_paths["esummary_payload_path"],
        esummary_payload_relpath=persisted_context_paths["esummary_payload_relpath"],
        entity_grounding_path=(
            grounding_artifact.artifact_path if grounding_artifact is not None else None
        ),
        entity_grounding_relpath=(
            grounding_artifact.artifact_relpath if grounding_artifact is not None else None
        ),
    )


def _materialize_retrieval_context_run(
    base_path: Path,
    retrieval_context: RetrievalContextSnapshot,
    *,
    selected_pmid: str | None,
) -> PersistedRetrievalContext:
    layout = prepare_run_directory(base_path, EVIDENCE_RETRIEVAL_WORKFLOW_NAME)
    _, persisted_paths = _persist_retrieval_context(layout, retrieval_context, selected_pmid=selected_pmid)
    _refresh_content_hash_manifest(layout)

    retrieval_context_path = persisted_paths["retrieval_context_path"]
    retrieval_context_relpath = persisted_paths["retrieval_context_relpath"]
    esearch_payload_path = persisted_paths["esearch_payload_path"]
    esearch_payload_relpath = persisted_paths["esearch_payload_relpath"]
    esummary_payload_path = persisted_paths["esummary_payload_path"]
    esummary_payload_relpath = persisted_paths["esummary_payload_relpath"]

    assert isinstance(retrieval_context_path, Path)
    assert isinstance(retrieval_context_relpath, str)
    assert esearch_payload_path is None or isinstance(esearch_payload_path, Path)
    assert esearch_payload_relpath is None or isinstance(esearch_payload_relpath, str)
    assert esummary_payload_path is None or isinstance(esummary_payload_path, Path)
    assert esummary_payload_relpath is None or isinstance(esummary_payload_relpath, str)

    return PersistedRetrievalContext(
        run_id=layout.run_id,
        retrieval_context_path=retrieval_context_path,
        retrieval_context_relpath=retrieval_context_relpath,
        esearch_payload_path=esearch_payload_path,
        esearch_payload_relpath=esearch_payload_relpath,
        esummary_payload_path=esummary_payload_path,
        esummary_payload_relpath=esummary_payload_relpath,
    )


def _find_prior_evidence_versions(base_path: Path, stable_identifier: str) -> list[ArtifactReference]:
    refs: list[ArtifactReference] = []
    for path in sorted((base_path / "artifacts").glob("*/*/*/evidence_card.yaml")):
        try:
            artifact = load_artifact_document(path)
        except Exception:
            continue
        if not isinstance(artifact, EvidenceCard):
            continue
        if artifact.stable_identifier != stable_identifier:
            continue
        refs.append(
            ArtifactReference(
                artifact_type="evidence_card",
                path=path.relative_to(base_path).as_posix(),
                id=artifact.id,
                run_id=artifact.run_id,
            )
        )
    return refs


def _extract_claims(abstract: str, *, pmid: str, title: str) -> list[dict[str, str]]:
    candidate_sentences = _split_sentences(abstract)
    prioritized = [
        sentence
        for sentence in candidate_sentences
        if any(keyword in sentence.lower() for keyword in _CLAIM_KEYWORDS)
    ]
    ordered = prioritized or candidate_sentences
    if not ordered:
        ordered = [title]

    claims: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, sentence in enumerate(ordered[:3], start=1):
        statement = " ".join(sentence.split()).strip()
        if not statement or statement.lower() in seen:
            continue
        seen.add(statement.lower())
        claims.append(
            {
                "id": normalize_identifier(f"pmid-{pmid}-claim-{index}"),
                "statement": statement,
                "confidence": _claim_confidence(statement),
            }
        )
    return claims


def _extract_limitations(abstract: str) -> list[str]:
    limitations = [
        sentence
        for sentence in _split_sentences(abstract)
        if any(keyword in sentence.lower() for keyword in _LIMITATION_KEYWORDS)
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for sentence in limitations[:3]:
        normalized = " ".join(sentence.split()).strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        deduped.append(normalized)

    if deduped:
        return deduped

    return [
        "Evidence card was generated from PubMed title and abstract metadata only; full-text limitations were not reviewed."
    ]


def _extract_entity_tags(mesh_terms: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    entity_tags: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for mesh_term in mesh_terms[:10]:
        label = (mesh_term.get("label") or "").strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        entity_tags.append(
            {
                "label": label,
                "entity_type": "mesh_term",
                "identifier": mesh_term.get("identifier"),
            }
        )
    return entity_tags


def _extract_grounding_requests(
    entity_tags: list[dict[str, str | None]],
) -> list[EntityGroundingMentionRequest]:
    requests: list[EntityGroundingMentionRequest] = []
    for tag in entity_tags:
        label = (tag.get("label") or "").strip()
        entity_types = _classify_grounding_entity_types(label)
        if entity_types is None:
            continue
        requests.append(
            EntityGroundingMentionRequest(
                mention=label,
                entity_types=entity_types,
            )
        )
    return requests


def _infer_grounding_species(entity_tags: list[dict[str, str | None]]) -> str | None:
    observed_species: list[str] = []
    for tag in entity_tags:
        normalized = _normalize_grounding_label(tag.get("label"))
        if not normalized:
            continue
        species = _MESH_SPECIES_TO_GROUNDING_SPECIES.get(normalized)
        if species is None or species in observed_species:
            continue
        observed_species.append(species)
    if len(observed_species) == 1:
        return observed_species[0]
    return None


def _classify_grounding_entity_types(label: str) -> list[str] | None:
    normalized = _normalize_grounding_label(label)
    if not normalized:
        return None
    if normalized in _GENERIC_GROUNDING_LABELS:
        return None
    if normalized in _MESH_SPECIES_TO_GROUNDING_SPECIES:
        return None
    if _ENSEMBL_ENTITY_ID_RE.fullmatch(label):
        entity_match = re.search(r"ENS[A-Z0-9]*([GTP])\d", label, re.IGNORECASE)
        entity_code = entity_match.group(1).upper() if entity_match is not None else "G"
        if entity_code == "T":
            return ["transcript"]
        if entity_code == "P":
            return ["protein"]
        return ["gene"]
    if _UNIPROT_ACCESSION_RE.fullmatch(label) or _UNIPROT_ENTRY_NAME_RE.fullmatch(label):
        return ["protein"]
    if _looks_like_gene_symbol_label(label, normalized=normalized):
        return ["gene"]
    if _looks_like_protein_name_label(label, normalized=normalized):
        return ["protein"]
    return None


def _looks_like_gene_symbol_label(label: str, *, normalized: str) -> bool:
    if not _GENE_SYMBOL_TOKEN_RE.fullmatch(label):
        return False
    if not any(character.isalpha() for character in label):
        return False
    if label.islower():
        return False
    if label.isalpha() and label.istitle() and len(label) > 4:
        return False
    if normalized in _GENERIC_GROUNDING_LABELS:
        return False
    return True


def _looks_like_protein_name_label(label: str, *, normalized: str) -> bool:
    if " " not in label:
        return False
    if len(label) > 80:
        return False
    if any(delimiter in label for delimiter in (",", ";", ":")):
        return False
    return any(keyword in normalized for keyword in _PROTEIN_GROUNDING_KEYWORDS)


def _normalize_grounding_label(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _infer_study_type(
    publication_types: list[str],
    *,
    title: str,
    abstract: str,
) -> str | None:
    for publication_type in publication_types:
        normalized = normalize_identifier(publication_type)
        if normalized:
            return normalized

    text = f"{title}\n{abstract}".lower()
    for keyword, identifier in _STUDY_TYPE_KEYWORDS:
        if keyword in text:
            return identifier
    return None


def _claim_confidence(statement: str) -> str:
    lowered = statement.lower()
    if any(keyword in lowered for keyword in ("suggest", "may", "might", "could")):
        return "medium"
    if any(keyword in lowered for keyword in ("show", "shows", "demonstrate", "reveals", "found")):
        return "high"
    return "medium"


def _overall_confidence(claims: list[dict[str, str]], *, abstract_present: bool) -> str:
    if not abstract_present:
        return "low"
    if claims and all(claim["confidence"] == "high" for claim in claims):
        return "high"
    return "medium"


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []
    sentences = [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(normalized)]
    return [sentence for sentence in sentences if len(sentence) >= 20]


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = value.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _persist_retrieval_context(
    layout,
    retrieval_context: RetrievalContextSnapshot,
    *,
    selected_pmid: str | None,
) -> tuple[list[ArtifactReference], dict[str, Path | str | None]]:
    refs: list[ArtifactReference] = []
    persisted_paths: dict[str, Path | str | None] = {
        "retrieval_context_path": None,
        "retrieval_context_relpath": None,
        "esearch_payload_path": None,
        "esearch_payload_relpath": None,
        "esummary_payload_path": None,
        "esummary_payload_relpath": None,
    }

    raw_payload_paths: dict[str, str] = {}
    if retrieval_context.esearch_response_text is not None:
        esearch_path = layout.generated_output_path("esearch.json", step="retrieval-context")
        esearch_path.write_text(retrieval_context.esearch_response_text, encoding="utf-8")
        esearch_relpath = layout.generated_output_relpath("esearch.json", step="retrieval-context").as_posix()
        raw_payload_paths["esearch"] = esearch_relpath
        persisted_paths["esearch_payload_path"] = esearch_path
        persisted_paths["esearch_payload_relpath"] = esearch_relpath
        refs.append(
            ArtifactReference(
                artifact_type="retrieval_search_payload",
                path=esearch_relpath,
                run_id=layout.run_id,
            )
        )

    if retrieval_context.esummary_response_text is not None:
        esummary_path = layout.generated_output_path("esummary.json", step="retrieval-context")
        esummary_path.write_text(retrieval_context.esummary_response_text, encoding="utf-8")
        esummary_relpath = layout.generated_output_relpath("esummary.json", step="retrieval-context").as_posix()
        raw_payload_paths["esummary"] = esummary_relpath
        persisted_paths["esummary_payload_path"] = esummary_path
        persisted_paths["esummary_payload_relpath"] = esummary_relpath
        refs.append(
            ArtifactReference(
                artifact_type="retrieval_summary_payload",
                path=esummary_relpath,
                run_id=layout.run_id,
            )
        )

    retrieval_context_payload = {
        "source_database": PUBMED_SOURCE_DATABASE,
        "query": retrieval_context.query,
        "selected_for_pmid": selected_pmid,
        "selected_pmids": retrieval_context.selected_pmids,
        "candidate_records": retrieval_context.candidate_records,
        "request_urls": {
            "esearch": retrieval_context.esearch_request_url,
            "esummary": retrieval_context.esummary_request_url,
        },
        "raw_payload_paths": raw_payload_paths,
    }
    context_path = layout.generated_output_path("retrieval_context.json", step="retrieval-context")
    context_path.write_text(
        json.dumps(retrieval_context_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    context_relpath = layout.generated_output_relpath("retrieval_context.json", step="retrieval-context").as_posix()
    persisted_paths["retrieval_context_path"] = context_path
    persisted_paths["retrieval_context_relpath"] = context_relpath
    refs.append(
        ArtifactReference(
            artifact_type="retrieval_context",
            path=context_relpath,
            run_id=layout.run_id,
        )
    )
    return refs, persisted_paths


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
