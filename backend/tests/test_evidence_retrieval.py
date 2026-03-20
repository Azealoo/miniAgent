import json
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import EvidenceCard, load_artifact_document, lookup_artifact_registry
from evidence import EvidenceRetrievalInput, run_evidence_retrieval
from tools.evidence_retrieval_tool import EvidenceRetrievalTool


def _mock_http_response(*, text: str, payload: dict | None = None):
    response = MagicMock()
    response.text = text
    response.status_code = 200
    response.raise_for_status = MagicMock()
    if payload is None:
        response.json.side_effect = ValueError("no json payload")
    else:
        response.json.return_value = payload
    return response


def _pubmed_article_xml(pmid: str, *, title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
              <Month>Jan</Month>
              <Day>12</Day>
            </PubDate>
          </JournalIssue>
          <Title>Nature Genetics</Title>
        </Journal>
        <ArticleTitle>{title}</ArticleTitle>
        <Abstract>
          <AbstractText Label="RESULTS">TP53 shows a reproducible stress-response program across matched replicates.</AbstractText>
          <AbstractText Label="CONCLUSION">However, the sample size was small and further study is needed to confirm durability.</AbstractText>
        </Abstract>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
        </PublicationTypeList>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName UI="D000001">TP53</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D000002">Stress Response, Physiological</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _ncbi_get_side_effect():
    titles = {
        "12345678": "TP53 coordinates a reproducible stress-response program",
        "23456789": "Interferon signaling remains robust across donors",
    }

    def _dispatch(url: str, timeout: int = 30):  # noqa: ARG001
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        operation = Path(parsed.path).name.replace(".fcgi", "")

        if operation == "esearch":
            payload = {"esearchresult": {"count": "2", "idlist": ["12345678", "23456789"]}}
            return _mock_http_response(text=json.dumps(payload), payload=payload)

        if operation == "esummary":
            ids = params.get("id", [""])[0].split(",")
            payload = {
                "result": {
                    "uids": ids,
                    **{
                        pmid: {
                            "uid": pmid,
                            "title": titles[pmid],
                            "fulljournalname": "Nature Genetics",
                            "pubdate": "2024 Jan 12",
                            "source": "Nature Genetics",
                        }
                        for pmid in ids
                        if pmid
                    },
                }
            }
            return _mock_http_response(text=json.dumps(payload), payload=payload)

        if operation == "efetch":
            pmid = params.get("id", [""])[0]
            return _mock_http_response(
                text=_pubmed_article_xml(pmid, title=titles[pmid]),
            )

        raise AssertionError(f"Unexpected URL: {url}")

    return _dispatch


def _ncbi_get_no_results_side_effect():
    def _dispatch(url: str, timeout: int = 30):  # noqa: ARG001
        parsed = urllib.parse.urlparse(url)
        operation = Path(parsed.path).name.replace(".fcgi", "")
        if operation == "esearch":
            payload = {"esearchresult": {"count": "0", "idlist": []}}
            return _mock_http_response(text=json.dumps(payload), payload=payload)
        raise AssertionError(f"Unexpected URL: {url}")

    return _dispatch


def _ncbi_get_partial_failure_side_effect():
    titles = {
        "12345678": "TP53 coordinates a reproducible stress-response program",
        "23456789": "Interferon signaling remains robust across donors",
    }

    def _dispatch(url: str, timeout: int = 30):  # noqa: ARG001
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        operation = Path(parsed.path).name.replace(".fcgi", "")

        if operation == "esearch":
            payload = {"esearchresult": {"count": "2", "idlist": ["12345678", "23456789"]}}
            return _mock_http_response(text=json.dumps(payload), payload=payload)

        if operation == "esummary":
            ids = params.get("id", [""])[0].split(",")
            payload = {
                "result": {
                    "uids": ids,
                    **{
                        pmid: {
                            "uid": pmid,
                            "title": titles[pmid],
                            "fulljournalname": "Nature Genetics",
                            "pubdate": "2024 Jan 12",
                            "source": "Nature Genetics",
                        }
                        for pmid in ids
                        if pmid
                    },
                }
            }
            return _mock_http_response(text=json.dumps(payload), payload=payload)

        if operation == "efetch":
            pmid = params.get("id", [""])[0]
            if pmid == "23456789":
                return _mock_http_response(text="<not-xml")
            return _mock_http_response(
                text=_pubmed_article_xml(pmid, title=titles[pmid]),
            )

        raise AssertionError(f"Unexpected URL: {url}")

    return _dispatch


def _ncbi_get_all_failure_side_effect():
    title = "Interferon signaling remains robust across donors"

    def _dispatch(url: str, timeout: int = 30):  # noqa: ARG001
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        operation = Path(parsed.path).name.replace(".fcgi", "")

        if operation == "esearch":
            payload = {"esearchresult": {"count": "1", "idlist": ["23456789"]}}
            return _mock_http_response(text=json.dumps(payload), payload=payload)

        if operation == "esummary":
            ids = params.get("id", [""])[0].split(",")
            payload = {
                "result": {
                    "uids": ids,
                    **{
                        pmid: {
                            "uid": pmid,
                            "title": title,
                            "fulljournalname": "Nature Genetics",
                            "pubdate": "2024 Jan 12",
                            "source": "Nature Genetics",
                        }
                        for pmid in ids
                        if pmid
                    },
                }
            }
            return _mock_http_response(text=json.dumps(payload), payload=payload)

        if operation == "efetch":
            return _mock_http_response(text="<not-xml")

        raise AssertionError(f"Unexpected URL: {url}")

    return _dispatch


def test_run_evidence_retrieval_materializes_evidence_card_and_registry_record(tmp_path):
    with patch("httpx.get", side_effect=_ncbi_get_side_effect()):
        result = run_evidence_retrieval(
            tmp_path,
            EvidenceRetrievalInput(query="TP53 stress response", max_results=5, max_evidence_cards=1),
        )

    assert result.selected_pmids == ["12345678"]
    assert len(result.cards) == 1
    assert result.failures == []
    assert result.candidate_records[0]["pmid"] == "12345678"

    retrieved = result.cards[0]
    assert retrieved.artifact_path.is_file()
    assert retrieved.cached_raw_payload_path.is_file()

    card = load_artifact_document(retrieved.artifact_path)
    assert isinstance(card, EvidenceCard)
    assert card.stable_identifier == "pmid:12345678"
    assert card.id.startswith("evidence-pmid-12345678-run-")
    assert card.cached_raw_payload_path == retrieved.cached_raw_payload_relpath
    assert card.study_type == "journal-article"
    assert len(card.claims) >= 1
    assert len(card.limitations) >= 1
    assert len(card.entity_tags) == 2
    assert retrieved.retrieval_context_path is not None
    assert retrieved.retrieval_context_path.is_file()
    assert retrieved.esearch_payload_path is not None
    assert retrieved.esearch_payload_path.is_file()
    assert retrieved.esummary_payload_path is not None
    assert retrieved.esummary_payload_path.is_file()

    retrieval_context = json.loads(retrieved.retrieval_context_path.read_text(encoding="utf-8"))
    assert retrieval_context["query"] == "TP53 stress response"
    assert retrieval_context["selected_for_pmid"] == "12345678"
    assert retrieval_context["selected_pmids"] == ["12345678"]
    assert retrieval_context["candidate_records"][0]["selected"] is True

    manifest_path = retrieved.artifact_path.parent / "content_hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "evidence_card.yaml" in manifest["hashes"]
    assert "outputs/generated/source-cache/pmid-12345678.xml" in manifest["hashes"]
    assert "outputs/generated/retrieval-context/retrieval_context.json" in manifest["hashes"]
    assert "outputs/generated/retrieval-context/esearch.json" in manifest["hashes"]
    assert "outputs/generated/retrieval-context/esummary.json" in manifest["hashes"]

    registry = lookup_artifact_registry(tmp_path, artifact_type="evidence_card")
    assert registry.matched_count == 1
    assert registry.records[0].path == retrieved.artifact_relpath


def test_run_evidence_retrieval_persists_context_when_no_records_match(tmp_path):
    with patch("httpx.get", side_effect=_ncbi_get_no_results_side_effect()):
        result = run_evidence_retrieval(
            tmp_path,
            EvidenceRetrievalInput(query="no matching papers", max_evidence_cards=1),
        )

    assert result.cards == []
    assert result.failures == []
    assert result.selected_pmids == []
    assert result.persisted_context is not None
    assert result.persisted_context.retrieval_context_path.is_file()
    assert result.persisted_context.esearch_payload_path is not None
    assert result.persisted_context.esearch_payload_path.is_file()
    assert result.persisted_context.esummary_payload_path is None

    retrieval_context = json.loads(result.persisted_context.retrieval_context_path.read_text(encoding="utf-8"))
    assert retrieval_context["query"] == "no matching papers"
    assert retrieval_context["selected_for_pmid"] is None
    assert retrieval_context["selected_pmids"] == []


def test_retrieval_links_prior_versions_without_overwriting_history(tmp_path):
    with patch("httpx.get", side_effect=_ncbi_get_side_effect()):
        first = run_evidence_retrieval(
            tmp_path,
            EvidenceRetrievalInput(pmids=["12345678"], max_evidence_cards=1),
        )
    with patch("httpx.get", side_effect=_ncbi_get_side_effect()):
        second = run_evidence_retrieval(
            tmp_path,
            EvidenceRetrievalInput(pmids=["12345678"], max_evidence_cards=1),
        )

    first_card = load_artifact_document(first.cards[0].artifact_path)
    second_card = load_artifact_document(second.cards[0].artifact_path)

    assert isinstance(first_card, EvidenceCard)
    assert isinstance(second_card, EvidenceCard)
    assert first_card.id != second_card.id
    assert first.cards[0].artifact_relpath != second.cards[0].artifact_relpath
    assert first.cards[0].cached_raw_payload_relpath != second.cards[0].cached_raw_payload_relpath
    assert second_card.related_artifacts[0].path == first.cards[0].artifact_relpath
    assert second_card.related_artifacts[0].run_id == first_card.run_id
    assert first.cards[0].artifact_path.is_file()
    assert second.cards[0].artifact_path.is_file()


def test_run_evidence_retrieval_persists_context_when_all_selected_pmids_fail(tmp_path):
    with patch("httpx.get", side_effect=_ncbi_get_all_failure_side_effect()):
        result = run_evidence_retrieval(
            tmp_path,
            EvidenceRetrievalInput(query="stress response", max_evidence_cards=1),
        )

    assert result.cards == []
    assert len(result.failures) == 1
    assert result.failures[0].pmid == "23456789"
    assert result.persisted_context is not None
    assert result.persisted_context.retrieval_context_path.is_file()
    assert result.persisted_context.esearch_payload_path is not None
    assert result.persisted_context.esearch_payload_path.is_file()
    assert result.persisted_context.esummary_payload_path is not None
    assert result.persisted_context.esummary_payload_path.is_file()

    retrieval_context = json.loads(result.persisted_context.retrieval_context_path.read_text(encoding="utf-8"))
    assert retrieval_context["selected_for_pmid"] is None
    assert retrieval_context["selected_pmids"] == ["23456789"]
    assert retrieval_context["candidate_records"][0]["selected"] is True


def test_evidence_retrieval_tool_returns_structured_artifact_refs(tmp_path):
    tool = EvidenceRetrievalTool(base_dir=str(tmp_path))

    with patch("httpx.get", side_effect=_ncbi_get_side_effect()):
        summary, artifact = tool._run(query="TP53 stress response", max_evidence_cards=1)

    assert "Retrieved 1 evidence card" in summary
    assert artifact["tool_name"] == "evidence_retrieval"
    assert artifact["status"] == "success"
    assert artifact["metadata"]["evidence_card_count"] == 1
    assert artifact["structured_payload"]["cards"][0]["stable_identifier"] == "pmid:12345678"
    assert artifact["structured_payload"]["cards"][0]["retrieval_context_path"].endswith("retrieval_context.json")
    assert len(artifact["artifact_refs"]) == 5


def test_evidence_retrieval_tool_returns_success_empty_when_no_results(tmp_path):
    tool = EvidenceRetrievalTool(base_dir=str(tmp_path))

    with patch("httpx.get", side_effect=_ncbi_get_no_results_side_effect()):
        summary, artifact = tool._run(query="no matching papers", max_evidence_cards=1)

    assert "No PubMed records matched" in summary
    assert artifact["status"] == "success"
    assert artifact["outcome"] == "success_empty"
    assert artifact["structured_payload"]["retrieval_context_path"].endswith("retrieval_context.json")
    assert artifact["structured_payload"]["esearch_payload_path"].endswith("esearch.json")
    assert artifact["structured_payload"]["cards"] == []
    assert artifact["structured_payload"]["selected_pmids"] == []
    assert len(artifact["artifact_refs"]) == 2


def test_evidence_retrieval_tool_returns_context_refs_when_all_selected_pmids_fail(tmp_path):
    tool = EvidenceRetrievalTool(base_dir=str(tmp_path))

    with patch("httpx.get", side_effect=_ncbi_get_all_failure_side_effect()):
        summary, artifact = tool._run(query="stress response", max_evidence_cards=1)

    assert "Evidence retrieval did not materialize any evidence cards" in summary
    assert artifact["status"] == "error"
    assert artifact["outcome"] == "execution_failure"
    assert artifact["structured_payload"]["retrieval_context_path"].endswith("retrieval_context.json")
    assert artifact["structured_payload"]["esearch_payload_path"].endswith("esearch.json")
    assert artifact["structured_payload"]["esummary_payload_path"].endswith("esummary.json")
    assert len(artifact["artifact_refs"]) == 3


def test_evidence_retrieval_tool_reports_partial_retrieval_warnings(tmp_path):
    tool = EvidenceRetrievalTool(base_dir=str(tmp_path))

    with patch("httpx.get", side_effect=_ncbi_get_partial_failure_side_effect()):
        summary, artifact = tool._run(query="stress response", max_evidence_cards=2)

    assert "Retrieved 1 evidence card" in summary
    assert "Failed PMIDs: 23456789" in summary
    assert artifact["status"] == "success"
    assert "partial_retrieval" in artifact["warnings"]
    assert artifact["metadata"]["failure_count"] == 1
    assert artifact["structured_payload"]["failures"][0]["pmid"] == "23456789"
