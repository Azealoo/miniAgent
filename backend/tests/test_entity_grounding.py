import json
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import EntityGroundingArtifact, load_artifact_document, lookup_artifact_registry
from entity_grounding import EntityGroundingInput, run_entity_grounding
from tools.entity_grounding_tool import EntityGroundingTool


def _mock_http_response(*, text: str, payload: dict | None = None):
    response = MagicMock()
    response.text = text
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.raise_for_status = MagicMock()
    if payload is None:
        response.json.side_effect = ValueError("no json payload")
    else:
        response.json.return_value = payload
    return response


def _mock_http_error(*, url: str, status_code: int):
    request = httpx.Request("GET", url)
    response = MagicMock()
    response.text = ""
    response.status_code = status_code
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {}
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"{status_code} error",
        request=request,
        response=httpx.Response(status_code, request=request),
    )
    return response


def _grounding_http_side_effect():
    def _dispatch(url: str, timeout: int = 25, headers: dict | None = None):  # noqa: ARG001
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.lstrip("/")
        query = urllib.parse.parse_qs(parsed.query).get("query", [""])[0]

        if parsed.netloc == "rest.ensembl.org":
            if path == "lookup/symbol/homo_sapiens/TP53":
                payload = {
                    "id": "ENSG00000141510",
                    "display_name": "TP53",
                    "object_type": "Gene",
                    "species": "homo_sapiens",
                    "version": 15,
                }
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            if path == "lookup/symbol/homo_sapiens/P53":
                return _mock_http_error(url=url, status_code=404)
            if path == "lookup/symbol/mus_musculus/TP53":
                return _mock_http_error(url=url, status_code=404)
            if path == "lookup/symbol/homo_sapiens/ACTB":
                payload = {
                    "id": "ENSG00000075624",
                    "display_name": "ACTB",
                    "object_type": "Gene",
                    "species": "homo_sapiens",
                    "version": 9,
                }
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            if path == "lookup/symbol/mus_musculus/ACTB":
                payload = {
                    "id": "ENSMUSG00000029580",
                    "display_name": "ACTB",
                    "object_type": "Gene",
                    "species": "mus_musculus",
                    "version": 4,
                }
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            raise AssertionError(f"Unexpected Ensembl URL: {url}")

        if parsed.netloc == "rest.uniprot.org":
            if query in {"id:P53_HUMAN", "id:TP53_HUMAN"}:
                payload = {
                    "results": [
                        {
                            "primaryAccession": "P04637",
                            "uniProtkbId": "P53_HUMAN",
                            "genes": [
                                {
                                    "geneName": {"value": "TP53"},
                                    "synonyms": [{"value": "P53"}],
                                }
                            ],
                            "proteinDescription": {
                                "recommendedName": {"fullName": {"value": "Cellular tumor antigen p53"}}
                            },
                            "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
                        }
                    ]
                }
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            if query in {
                'reviewed:true AND gene_exact:Cellular tumor antigen p53 AND organism_name:"Homo sapiens"',
                'reviewed:true AND gene:Cellular tumor antigen p53 AND organism_name:"Homo sapiens"',
            }:
                payload = {"results": []}
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            if query == 'reviewed:true AND protein_name:"Cellular tumor antigen p53" AND organism_name:"Homo sapiens"':
                payload = {
                    "results": [
                        {
                            "primaryAccession": "P04637",
                            "uniProtkbId": "P53_HUMAN",
                            "genes": [
                                {
                                    "geneName": {"value": "TP53"},
                                    "synonyms": [{"value": "P53"}],
                                }
                            ],
                            "proteinDescription": {
                                "recommendedName": {"fullName": {"value": "Cellular tumor antigen p53"}}
                            },
                            "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
                        }
                    ]
                }
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            if 'gene:P53 AND organism_name:"Homo sapiens"' in query:
                payload = {
                    "results": [
                        {
                            "primaryAccession": "P04637",
                            "uniProtkbId": "P53_HUMAN",
                            "genes": [
                                {
                                    "geneName": {"value": "TP53"},
                                    "synonyms": [{"value": "P53"}],
                                }
                            ],
                            "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
                        }
                    ]
                }
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            if 'gene:TP53 AND organism_name:"Mus musculus"' in query:
                payload = {"results": []}
                return _mock_http_response(text=json.dumps(payload), payload=payload)
            raise AssertionError(f"Unexpected UniProt URL: {url}")

        raise AssertionError(f"Unexpected URL: {url}")

    return _dispatch


def test_run_entity_grounding_materializes_artifact_and_registry_record(tmp_path):
    with patch("httpx.get", side_effect=_grounding_http_side_effect()):
        result = run_entity_grounding(
            tmp_path,
            EntityGroundingInput(mentions=["TP53"], entity_types=["gene"]),
        )

    assert result.artifact_path.is_file()
    assert len(result.resolved_entities) == 1
    assert result.resolved_entities[0].stable_identifier == "ensembl:ENSG00000141510"
    assert len(result.cached_payloads) >= 1

    artifact = load_artifact_document(result.artifact_path)
    assert isinstance(artifact, EntityGroundingArtifact)
    assert artifact.results[0].status == "resolved"
    assert artifact.results[0].grounded_entity is not None
    assert artifact.results[0].grounded_entity.preferred_label == "TP53"

    registry = lookup_artifact_registry(tmp_path, artifact_type="entity_grounding")
    assert registry.matched_count == 1
    assert registry.records[0].path == result.artifact_relpath


def test_run_entity_grounding_resolves_gene_aliases_via_uniprot_fallback(tmp_path):
    with patch("httpx.get", side_effect=_grounding_http_side_effect()):
        result = run_entity_grounding(
            tmp_path,
            EntityGroundingInput(mentions=["P53"], species="human", entity_types=["gene"]),
        )

    assert len(result.resolved_entities) == 1
    grounded = result.resolved_entities[0]
    assert grounded.stable_identifier == "ensembl:ENSG00000141510"
    assert "P53" in grounded.aliases
    assert "TP53" in grounded.aliases


def test_run_entity_grounding_resolves_uniprot_entry_name_for_proteins(tmp_path):
    with patch("httpx.get", side_effect=_grounding_http_side_effect()):
        result = run_entity_grounding(
            tmp_path,
            EntityGroundingInput(mentions=["P53_HUMAN"], entity_types=["protein"]),
        )

    assert len(result.resolved_entities) == 1
    grounded = result.resolved_entities[0]
    assert grounded.stable_identifier == "uniprot:P04637"
    assert grounded.preferred_label == "Cellular tumor antigen p53"
    assert "P53_HUMAN" in grounded.aliases
    assert grounded.taxon_id == "taxonomy:9606"


def test_run_entity_grounding_resolves_protein_names_via_uniprot_name_search(tmp_path):
    with patch("httpx.get", side_effect=_grounding_http_side_effect()):
        result = run_entity_grounding(
            tmp_path,
            EntityGroundingInput(
                mentions=["Cellular tumor antigen p53"],
                species="human",
                entity_types=["protein"],
            ),
        )

    assert len(result.resolved_entities) == 1
    grounded = result.resolved_entities[0]
    assert grounded.stable_identifier == "uniprot:P04637"
    assert grounded.preferred_label == "Cellular tumor antigen p53"
    assert grounded.species == "Homo sapiens"


def test_entity_grounding_tool_reports_ambiguous_species_matches(tmp_path):
    tool = EntityGroundingTool(base_dir=str(tmp_path))

    with patch("httpx.get", side_effect=_grounding_http_side_effect()):
        summary, artifact = tool._run(mentions=["ACTB"], entity_types=["gene"])

    assert "Grounding requires clarification for 1 of 1 mention(s)." == summary
    assert artifact["tool_name"] == "entity_grounding"
    assert artifact["status"] == "success"
    assert artifact["outcome"] == "success_empty"
    assert "ambiguous_matches" in artifact["warnings"]
    assert artifact["metadata"]["ambiguous_count"] == 1
    assert artifact["metadata"]["requires_clarification"] is True
    assert artifact["structured_payload"]["requires_clarification"] is True
    assert artifact["structured_payload"]["results"][0]["status"] == "ambiguous"
    assert len(artifact["structured_payload"]["results"][0]["candidate_entities"]) == 2
