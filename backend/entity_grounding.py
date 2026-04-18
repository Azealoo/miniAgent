"""Deterministic biological entity grounding with durable artifact persistence."""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artifacts import (
    ArtifactReference,
    EntityGroundingArtifact,
    EntityGroundingResult,
    GroundedEntity,
    RunLayout,
    SCHEMA_PACK_VERSION,
    build_content_hash_manifest,
    normalize_identifier,
    prepare_run_directory,
)
from tools.ensembl_api_tool import fetch_ensembl_response
from tools.uniprot_api_tool import fetch_uniprot_response

EntityType = Literal["gene", "protein", "transcript"]

ENTITY_GROUNDING_WORKFLOW_NAME = "entity-grounding"
_DEFAULT_ENTITY_TYPES: tuple[EntityType, ...] = ("gene",)
_DEFAULT_SPECIES_KEYS = ("human", "mouse")
_UNIPROT_FIELDS = (
    "accession,id,gene_names,protein_name,organism_name,organism_id,reviewed,"
    "annotation_score"
)
_ENSEMBL_ENTITY_ID_RE = re.compile(r"^ENS[A-Z0-9]*[GTP]\d+(?:\.\d+)?$", re.IGNORECASE)
_UNIPROT_ACCESSION_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-\d+)?$",
    re.IGNORECASE,
)
_UNIPROT_ENTRY_NAME_RE = re.compile(r"^[A-Z0-9]{1,10}_[A-Z0-9]{1,10}$", re.IGNORECASE)


@dataclass(frozen=True)
class SpeciesInfo:
    key: str
    ensembl_slug: str
    scientific_name: str
    taxon_id: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class CachedGroundingPayload:
    source_database: str
    stage: str
    path: Path
    relpath: str
    request_url: str


@dataclass(frozen=True)
class PersistedEntityGrounding:
    artifact: EntityGroundingArtifact
    artifact_path: Path
    artifact_relpath: str
    cached_payloads: tuple[CachedGroundingPayload, ...]

    @property
    def resolved_entities(self) -> list[GroundedEntity]:
        return [
            result.grounded_entity
            for result in self.artifact.results
            if result.grounded_entity is not None
        ]


@dataclass
class _GroundingExecutionContext:
    layout: RunLayout
    payloads: dict[tuple[str, str, str, str], CachedGroundingPayload] = field(default_factory=dict)


_SUPPORTED_SPECIES: dict[str, SpeciesInfo] = {
    "human": SpeciesInfo(
        key="human",
        ensembl_slug="homo_sapiens",
        scientific_name="Homo sapiens",
        taxon_id="taxonomy:9606",
        aliases=("human", "homo sapiens", "homo_sapiens"),
    ),
    "mouse": SpeciesInfo(
        key="mouse",
        ensembl_slug="mus_musculus",
        scientific_name="Mus musculus",
        taxon_id="taxonomy:10090",
        aliases=("mouse", "mus musculus", "mus_musculus"),
    ),
    "rat": SpeciesInfo(
        key="rat",
        ensembl_slug="rattus_norvegicus",
        scientific_name="Rattus norvegicus",
        taxon_id="taxonomy:10116",
        aliases=("rat", "rattus norvegicus", "rattus_norvegicus"),
    ),
}

_SPECIES_ALIAS_MAP = {
    re.sub(r"[^a-z0-9]+", " ", alias.casefold()).strip(): info
    for info in _SUPPORTED_SPECIES.values()
    for alias in info.aliases
}


class EntityGroundingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentions: list[str] = Field(min_length=1)
    species: str | None = None
    entity_types: list[EntityType] = Field(default_factory=lambda: list(_DEFAULT_ENTITY_TYPES))

    @field_validator("mentions")
    @classmethod
    def _validate_mentions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            mention = item.strip()
            if not mention:
                continue
            key = mention.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(mention)
        if not cleaned:
            raise ValueError("mentions must include at least one non-empty value.")
        return cleaned

    @field_validator("species")
    @classmethod
    def _validate_species(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("entity_types")
    @classmethod
    def _validate_entity_types(cls, value: list[EntityType]) -> list[EntityType]:
        cleaned = list(dict.fromkeys(value))
        if not cleaned:
            raise ValueError("entity_types must include at least one entity type.")
        return cleaned

    @model_validator(mode="after")
    def _validate_transcript_scope(self) -> "EntityGroundingInput":
        if "transcript" in self.entity_types and len(self.entity_types) > 1:
            return self
        return self


class EntityGroundingMentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mention: str
    entity_types: list[EntityType] = Field(min_length=1)

    @field_validator("mention")
    @classmethod
    def _validate_mention(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("mention must be non-empty.")
        return cleaned

    @field_validator("entity_types")
    @classmethod
    def _validate_entity_types(cls, value: list[EntityType]) -> list[EntityType]:
        cleaned = list(dict.fromkeys(value))
        if not cleaned:
            raise ValueError("entity_types must include at least one entity type.")
        return cleaned


def run_entity_grounding(
    base_dir: Path | str,
    payload: EntityGroundingInput,
) -> PersistedEntityGrounding:
    layout = prepare_run_directory(base_dir, ENTITY_GROUNDING_WORKFLOW_NAME)
    grounded = materialize_entity_grounding(layout, payload)
    _refresh_content_hash_manifest(layout)
    return grounded


def materialize_entity_grounding(
    layout: RunLayout,
    payload: EntityGroundingInput,
) -> PersistedEntityGrounding:
    mention_requests = [
        EntityGroundingMentionRequest(mention=mention, entity_types=payload.entity_types)
        for mention in payload.mentions
    ]
    return materialize_entity_grounding_requests(
        layout,
        mention_requests=mention_requests,
        species=payload.species,
    )


def materialize_entity_grounding_requests(
    layout: RunLayout,
    *,
    mention_requests: list[EntityGroundingMentionRequest],
    species: str | None = None,
) -> PersistedEntityGrounding:
    merged_requests = _merge_mention_requests(mention_requests)
    if not merged_requests:
        raise ValueError("mention_requests must include at least one mention.")

    context = _GroundingExecutionContext(layout=layout)
    results = [
        _ground_mention(
            mention=request.mention,
            requested_entity_types=request.entity_types,
            species_input=species,
            context=context,
        )
        for request in merged_requests
    ]
    related_artifacts = [
        ArtifactReference(
            artifact_type="grounding_source_payload",
            path=record.relpath,
            run_id=layout.run_id,
        )
        for record in context.payloads.values()
    ]
    artifact = EntityGroundingArtifact.model_validate(
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "entity_grounding",
            "id": _build_grounding_artifact_id(
                [request.mention for request in merged_requests],
                layout.run_id,
            ),
            "run_id": layout.run_id,
            "created_at": layout.created_at,
            "source_workflow": layout.workflow,
            "related_artifacts": [ref.model_dump(mode="json") for ref in related_artifacts],
            "input_mentions": [request.mention for request in merged_requests],
            "requested_species": species,
            "requested_entity_types": _collect_requested_entity_types(merged_requests),
            "requires_clarification": any(result.requires_clarification for result in results),
            "results": [result.model_dump(mode="json") for result in results],
        }
    )
    artifact_path = layout.stable_artifact_path("entity_grounding")
    artifact_path.write_text(
        json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return PersistedEntityGrounding(
        artifact=artifact,
        artifact_path=artifact_path,
        artifact_relpath=layout.stable_artifact_relpath("entity_grounding").as_posix(),
        cached_payloads=tuple(context.payloads.values()),
    )


def _ground_mention(
    *,
    mention: str,
    requested_entity_types: list[EntityType],
    species_input: str | None,
    context: _GroundingExecutionContext,
) -> EntityGroundingResult:
    species_candidates, species_error = _resolve_species_candidates(species_input)
    if species_error is not None:
        return EntityGroundingResult.model_validate(
            {
                "input_mention": mention,
                "requested_entity_types": requested_entity_types,
                "status": "unresolved",
                "note": species_error,
            }
        )

    candidates: list[GroundedEntity] = []
    cached_paths: list[str] = []
    for entity_type in requested_entity_types:
        if entity_type == "gene":
            new_candidates, new_paths = _resolve_gene_candidates(mention, species_candidates, context)
        elif entity_type == "protein":
            new_candidates, new_paths = _resolve_protein_candidates(mention, species_candidates, context)
        else:
            new_candidates, new_paths = _resolve_transcript_candidates(mention, context)
        candidates.extend(new_candidates)
        cached_paths.extend(new_paths)

    deduped_candidates = _dedupe_entities(candidates)
    deduped_paths = _dedupe_strings(cached_paths)

    if not deduped_candidates:
        return EntityGroundingResult.model_validate(
            {
                "input_mention": mention,
                "requested_entity_types": requested_entity_types,
                "status": "unresolved",
                "note": _build_unresolved_note(requested_entity_types, species_input),
                "cached_source_payload_paths": deduped_paths,
            }
        )

    if len(deduped_candidates) == 1:
        return EntityGroundingResult.model_validate(
            {
                "input_mention": mention,
                "requested_entity_types": requested_entity_types,
                "status": "resolved",
                "grounded_entity": deduped_candidates[0].model_dump(mode="json"),
                "cached_source_payload_paths": deduped_paths,
            }
        )

    return EntityGroundingResult.model_validate(
        {
            "input_mention": mention,
            "requested_entity_types": requested_entity_types,
            "status": "ambiguous",
            "requires_clarification": True,
            "candidate_entities": [entity.model_dump(mode="json") for entity in deduped_candidates],
            "note": _build_ambiguity_note(deduped_candidates, species_input),
            "cached_source_payload_paths": deduped_paths,
        }
    )


def _resolve_gene_candidates(
    mention: str,
    species_candidates: list[SpeciesInfo],
    context: _GroundingExecutionContext,
) -> tuple[list[GroundedEntity], list[str]]:
    if _looks_like_ensembl_identifier(mention):
        candidate, cached_paths = _lookup_ensembl_identifier(
            mention=mention,
            entity_type="gene",
            expected_object_types={"gene"},
            context=context,
        )
        return ([candidate] if candidate is not None else []), cached_paths

    candidates: list[GroundedEntity] = []
    cached_paths: list[str] = []
    for species in species_candidates:
        candidate, symbol_paths = _lookup_ensembl_symbol(
            mention=mention,
            species=species,
            context=context,
            aliases=[mention],
        )
        cached_paths.extend(symbol_paths)
        if candidate is not None:
            candidates.append(candidate)
            continue

        alias_candidates, alias_paths = _lookup_gene_via_uniprot_alias(
            mention=mention,
            species=species,
            context=context,
        )
        candidates.extend(alias_candidates)
        cached_paths.extend(alias_paths)
    return _dedupe_entities(candidates), _dedupe_strings(cached_paths)


def _resolve_protein_candidates(
    mention: str,
    species_candidates: list[SpeciesInfo],
    context: _GroundingExecutionContext,
) -> tuple[list[GroundedEntity], list[str]]:
    direct_identifier_mode = _direct_uniprot_identifier_mode(mention)
    if direct_identifier_mode is not None:
        candidates, cached_paths = _search_uniprot_proteins(
            mention=mention,
            species=None,
            context=context,
            direct_identifier_mode=direct_identifier_mode,
        )
        return _dedupe_entities(candidates), _dedupe_strings(cached_paths)

    candidates: list[GroundedEntity] = []
    cached_paths: list[str] = []
    for species in species_candidates:
        species_candidates_found, species_paths = _search_uniprot_proteins(
            mention=mention,
            species=species,
            context=context,
            direct_identifier_mode=None,
        )
        candidates.extend(species_candidates_found)
        cached_paths.extend(species_paths)
    return _dedupe_entities(candidates), _dedupe_strings(cached_paths)


def _resolve_transcript_candidates(
    mention: str,
    context: _GroundingExecutionContext,
) -> tuple[list[GroundedEntity], list[str]]:
    if not _looks_like_ensembl_identifier(mention):
        return [], []
    candidate, cached_paths = _lookup_ensembl_identifier(
        mention=mention,
        entity_type="transcript",
        expected_object_types={"transcript"},
        context=context,
    )
    return ([candidate] if candidate is not None else []), cached_paths


def _lookup_ensembl_symbol(
    *,
    mention: str,
    species: SpeciesInfo,
    context: _GroundingExecutionContext,
    aliases: list[str],
) -> tuple[GroundedEntity | None, list[str]]:
    endpoint = f"lookup/symbol/{species.ensembl_slug}/{urllib.parse.quote(mention)}?expand=1"
    try:
        response = fetch_ensembl_response(endpoint=endpoint)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, []
        raise
    payload = response.json_payload if isinstance(response.json_payload, dict) else {}
    cached = _persist_payload(
        context,
        mention=mention,
        entity_type="gene",
        species_label=species.key,
        source_database="ensembl",
        stage="lookup_symbol",
        request_url=response.url,
        payload=payload,
    )
    object_type = _clean_optional_text(payload.get("object_type"))
    if object_type is None or object_type.casefold() != "gene":
        return None, [cached.relpath]
    candidate = _grounded_entity_from_ensembl_payload(
        payload,
        mention=mention,
        aliases=aliases,
        fallback_species=species,
        entity_type="gene",
    )
    return candidate, [cached.relpath]


def _lookup_ensembl_identifier(
    *,
    mention: str,
    entity_type: EntityType,
    expected_object_types: set[str],
    context: _GroundingExecutionContext,
) -> tuple[GroundedEntity | None, list[str]]:
    endpoint = f"lookup/id/{urllib.parse.quote(mention)}?expand=1"
    try:
        response = fetch_ensembl_response(endpoint=endpoint)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None, []
        raise
    payload = response.json_payload if isinstance(response.json_payload, dict) else {}
    cached = _persist_payload(
        context,
        mention=mention,
        entity_type=entity_type,
        species_label=_clean_optional_text(payload.get("species")) or "direct",
        source_database="ensembl",
        stage="lookup_id",
        request_url=response.url,
        payload=payload,
    )
    object_type = (_clean_optional_text(payload.get("object_type")) or "").casefold()
    if object_type not in expected_object_types:
        return None, [cached.relpath]
    candidate = _grounded_entity_from_ensembl_payload(
        payload,
        mention=mention,
        aliases=[mention],
        fallback_species=None,
        entity_type=entity_type,
    )
    return candidate, [cached.relpath]


def _lookup_gene_via_uniprot_alias(
    *,
    mention: str,
    species: SpeciesInfo,
    context: _GroundingExecutionContext,
) -> tuple[list[GroundedEntity], list[str]]:
    entries, cached_paths = _search_uniprot_entries(
        mention=mention,
        species=species,
        context=context,
        stage="gene_alias_search",
        queries=(
            f'reviewed:true AND gene:{mention} AND organism_name:"{species.scientific_name}"',
        ),
    )
    candidates: list[GroundedEntity] = []
    seen_symbols: set[str] = set()
    for entry in entries:
        canonical_symbol = _first_uniprot_gene_name(entry)
        if canonical_symbol is None:
            continue
        key = canonical_symbol.casefold()
        if key in seen_symbols:
            continue
        seen_symbols.add(key)
        aliases = _dedupe_strings([mention, *_collect_uniprot_gene_aliases(entry)])
        candidate, symbol_paths = _lookup_ensembl_symbol(
            mention=canonical_symbol,
            species=species,
            context=context,
            aliases=aliases,
        )
        cached_paths.extend(symbol_paths)
        if candidate is not None:
            candidates.append(
                candidate.model_copy(
                    update={"aliases": _dedupe_strings([*candidate.aliases, *aliases])}
                )
            )
    return _dedupe_entities(candidates), _dedupe_strings(cached_paths)


def _search_uniprot_proteins(
    *,
    mention: str,
    species: SpeciesInfo | None,
    context: _GroundingExecutionContext,
    direct_identifier_mode: Literal["accession", "entry_name"] | None,
) -> tuple[list[GroundedEntity], list[str]]:
    if direct_identifier_mode == "accession":
        queries = (f"accession:{mention}",)
    elif direct_identifier_mode == "entry_name":
        queries = (f"id:{mention}",)
    else:
        species_clause = f' AND organism_name:"{species.scientific_name}"' if species is not None else ""
        queries = (
            f"reviewed:true AND gene_exact:{mention}{species_clause}",
            f"reviewed:true AND gene:{mention}{species_clause}",
            f'reviewed:true AND protein_name:"{mention}"{species_clause}',
        )
    entries, cached_paths = _search_uniprot_entries(
        mention=mention,
        species=species,
        context=context,
        stage="protein_search",
        queries=queries,
    )
    candidates = [
        _grounded_entity_from_uniprot_entry(entry, mention=mention)
        for entry in entries[:3]
        if _clean_optional_text(entry.get("primaryAccession")) is not None
    ]
    return _dedupe_entities(candidates), _dedupe_strings(cached_paths)


def _search_uniprot_entries(
    *,
    mention: str,
    species: SpeciesInfo | None,
    context: _GroundingExecutionContext,
    stage: str,
    queries: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    cached_paths: list[str] = []
    for index, query in enumerate(queries, start=1):
        response = fetch_uniprot_response(
            query=query,
            fields=_UNIPROT_FIELDS,
            format="json",
            size=3,
        )
        payload = response.json_payload if isinstance(response.json_payload, dict) else {}
        cached = _persist_payload(
            context,
            mention=mention,
            entity_type="protein" if stage == "protein_search" else "gene",
            species_label=species.key if species is not None else "global",
            source_database="uniprot",
            stage=f"{stage}_{index}",
            request_url=response.url,
            payload=payload,
        )
        cached_paths.append(cached.relpath)
        results = payload.get("results") if isinstance(payload, dict) else None
        if isinstance(results, list) and results:
            return [entry for entry in results if isinstance(entry, dict)], cached_paths
    return [], cached_paths


def _grounded_entity_from_ensembl_payload(
    payload: dict[str, Any],
    *,
    mention: str,
    aliases: list[str],
    fallback_species: SpeciesInfo | None,
    entity_type: EntityType,
) -> GroundedEntity:
    stable_id = _clean_optional_text(payload.get("id"))
    assert stable_id is not None
    display_name = _clean_optional_text(payload.get("display_name")) or mention
    species_slug = _clean_optional_text(payload.get("species"))
    species_info = _species_from_slug(species_slug) if species_slug is not None else fallback_species
    version = payload.get("version")
    return GroundedEntity.model_validate(
        {
            "entity_type": entity_type,
            "source_database": "ensembl",
            "stable_identifier": f"ensembl:{stable_id}",
            "identifier_version": str(version) if version is not None else None,
            "preferred_label": display_name,
            "aliases": _dedupe_strings([*aliases, display_name]),
            "species": species_info.scientific_name if species_info is not None else _display_species(species_slug),
            "taxon_id": species_info.taxon_id if species_info is not None else None,
        }
    )


def _grounded_entity_from_uniprot_entry(entry: dict[str, Any], *, mention: str) -> GroundedEntity:
    accession = _clean_optional_text(entry.get("primaryAccession"))
    assert accession is not None
    protein_name = _extract_uniprot_protein_name(entry) or accession
    organism = entry.get("organism") if isinstance(entry.get("organism"), dict) else {}
    scientific_name = _clean_optional_text(organism.get("scientificName"))
    taxon_id = organism.get("taxonId")
    return GroundedEntity.model_validate(
        {
            "entity_type": "protein",
            "source_database": "uniprot",
            "stable_identifier": f"uniprot:{accession}",
            "identifier_version": _extract_uniprot_identifier_version(entry),
            "preferred_label": protein_name,
            "aliases": _dedupe_strings(
                [
                    mention,
                    accession,
                    _clean_optional_text(entry.get("uniProtkbId")),
                    *_collect_uniprot_gene_aliases(entry),
                ]
            ),
            "species": scientific_name,
            "taxon_id": f"taxonomy:{taxon_id}" if taxon_id is not None else None,
        }
    )


def _persist_payload(
    context: _GroundingExecutionContext,
    *,
    mention: str,
    entity_type: EntityType,
    species_label: str,
    source_database: str,
    stage: str,
    request_url: str,
    payload: dict[str, Any],
) -> CachedGroundingPayload:
    key = (source_database, stage, request_url, entity_type)
    if key in context.payloads:
        return context.payloads[key]

    filename = (
        f"{_safe_component(mention)}__{entity_type}__{_safe_component(species_label)}__"
        f"{_safe_component(source_database)}__{_safe_component(stage)}.json"
    )
    path = context.layout.generated_output_path(filename, step="entity-grounding-cache")
    path.write_text(
        json.dumps(
            {
                "source_database": source_database,
                "stage": stage,
                "request_url": request_url,
                "payload": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    relpath = context.layout.generated_output_relpath(filename, step="entity-grounding-cache").as_posix()
    record = CachedGroundingPayload(
        source_database=source_database,
        stage=stage,
        path=path,
        relpath=relpath,
        request_url=request_url,
    )
    context.payloads[key] = record
    return record


def _resolve_species_candidates(species_input: str | None) -> tuple[list[SpeciesInfo], str | None]:
    if species_input is None:
        return [_SUPPORTED_SPECIES[key] for key in _DEFAULT_SPECIES_KEYS], None
    key = re.sub(r"[^a-z0-9]+", " ", species_input.casefold()).strip()
    species = _SPECIES_ALIAS_MAP.get(key)
    if species is None:
        supported = ", ".join(sorted(_SUPPORTED_SPECIES))
        return [], f"Unsupported species {species_input!r}. Supported species: {supported}."
    return [species], None


def _build_grounding_artifact_id(mentions: list[str], run_id: str) -> str:
    first = _safe_component(mentions[0])
    if len(mentions) == 1:
        return normalize_identifier(f"entity-grounding-{first}-{run_id}")
    return normalize_identifier(f"entity-grounding-{first}-plus-{len(mentions) - 1}-{run_id}")


def _build_unresolved_note(requested_entity_types: list[EntityType], species_input: str | None) -> str:
    types_text = ", ".join(requested_entity_types)
    if species_input:
        return f"No {types_text} grounding match found for the provided species context."
    return f"No {types_text} grounding match found across the default species search."


def _build_ambiguity_note(candidates: list[GroundedEntity], species_input: str | None) -> str:
    species = {candidate.species for candidate in candidates if candidate.species}
    entity_types = {candidate.entity_type for candidate in candidates}
    if species_input is None and len(species) > 1:
        return "Multiple species matched this mention. Specify species to ground it confidently."
    if len(entity_types) > 1:
        return "Multiple entity classes matched this mention. Specify gene, protein, or transcript."
    return "Multiple plausible identifiers matched this mention. Clarify the intended target."


def _species_from_slug(species_slug: str | None) -> SpeciesInfo | None:
    if species_slug is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", species_slug.casefold()).strip()
    return _SPECIES_ALIAS_MAP.get(normalized)


def _display_species(species_slug: str | None) -> str | None:
    info = _species_from_slug(species_slug)
    if info is not None:
        return info.scientific_name
    if species_slug is None:
        return None
    cleaned = species_slug.replace("_", " ").strip()
    return cleaned.title() if cleaned else None


def _dedupe_entities(candidates: list[GroundedEntity]) -> list[GroundedEntity]:
    deduped: list[GroundedEntity] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.stable_identifier.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _dedupe_strings(values: list[str | None]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _merge_mention_requests(
    mention_requests: list[EntityGroundingMentionRequest],
) -> list[EntityGroundingMentionRequest]:
    merged: list[EntityGroundingMentionRequest] = []
    positions: dict[str, int] = {}
    for request in mention_requests:
        key = request.mention.casefold()
        if key not in positions:
            positions[key] = len(merged)
            merged.append(request)
            continue
        index = positions[key]
        combined_entity_types = list(
            dict.fromkeys([*merged[index].entity_types, *request.entity_types])
        )
        merged[index] = EntityGroundingMentionRequest(
            mention=merged[index].mention,
            entity_types=combined_entity_types,
        )
    return merged


def _collect_requested_entity_types(
    mention_requests: list[EntityGroundingMentionRequest],
) -> list[EntityType]:
    return list(dict.fromkeys(
        entity_type
        for request in mention_requests
        for entity_type in request.entity_types
    ))


def _safe_component(value: str) -> str:
    try:
        return normalize_identifier(value).replace(":", "-")
    except ValueError:
        return "value"


def _looks_like_ensembl_identifier(value: str) -> bool:
    return _ENSEMBL_ENTITY_ID_RE.fullmatch(value.strip()) is not None


def _looks_like_uniprot_accession(value: str) -> bool:
    return _UNIPROT_ACCESSION_RE.fullmatch(value.strip()) is not None


def _looks_like_uniprot_entry_name(value: str) -> bool:
    return _UNIPROT_ENTRY_NAME_RE.fullmatch(value.strip()) is not None


def _direct_uniprot_identifier_mode(value: str) -> Literal["accession", "entry_name"] | None:
    if _looks_like_uniprot_accession(value):
        return "accession"
    if _looks_like_uniprot_entry_name(value):
        return "entry_name"
    return None


def _clean_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _first_uniprot_gene_name(entry: dict[str, Any]) -> str | None:
    genes = entry.get("genes")
    if not isinstance(genes, list):
        return None
    for gene in genes:
        if not isinstance(gene, dict):
            continue
        name = _nested_optional_text(gene, "geneName", "value")
        if name is not None:
            return name
    return None


def _collect_uniprot_gene_aliases(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    genes = entry.get("genes")
    if not isinstance(genes, list):
        return aliases
    for gene in genes:
        if not isinstance(gene, dict):
            continue
        for field_name in ("geneName",):
            value = _nested_optional_text(gene, field_name, "value")
            if value is not None:
                aliases.append(value)
        for field_name in ("synonyms", "orderedLocusNames", "orfNames"):
            values = gene.get(field_name)
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                value = _clean_optional_text(item.get("value"))
                if value is not None:
                    aliases.append(value)
    return _dedupe_strings(aliases)


def _extract_uniprot_protein_name(entry: dict[str, Any]) -> str | None:
    protein = entry.get("proteinDescription")
    if not isinstance(protein, dict):
        return None
    for path in (
        ("recommendedName", "fullName", "value"),
        ("submissionNames", "0", "fullName", "value"),
    ):
        value = _nested_optional_text(protein, *path)
        if value is not None:
            return value
    return None


def _extract_uniprot_identifier_version(entry: dict[str, Any]) -> str | None:
    entry_audit = entry.get("entryAudit")
    if not isinstance(entry_audit, dict):
        return None
    for key in ("entryVersion", "sequenceVersion"):
        value = entry_audit.get(key)
        if value is None:
            continue
        return str(value)
    return None


def _nested_optional_text(value: Any, *path: str) -> str | None:
    current = value
    for part in path:
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return None
            if index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return _clean_optional_text(current)


def _refresh_content_hash_manifest(layout: RunLayout) -> None:
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


__all__ = [
    "ENTITY_GROUNDING_WORKFLOW_NAME",
    "CachedGroundingPayload",
    "EntityGroundingInput",
    "PersistedEntityGrounding",
    "materialize_entity_grounding",
    "run_entity_grounding",
]
