import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import ToolMessage

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.contracts import (
    MAX_SOURCE_PAYLOAD_JSON_CHARS,
    MAX_STRUCTURED_PAYLOAD_JSON_CHARS,
    normalize_tool_output,
    success_result,
)


def test_normalize_tool_output_classifies_legacy_blocked_messages():
    result = normalize_tool_output("legacy_tool", "[BLOCKED] Access denied.")

    assert result.tool_name == "legacy_tool"
    assert result.status == "error"
    assert result.outcome == "blocked"
    assert result.error is not None
    assert result.error.code == "blocked"


def test_normalize_tool_output_prefers_structured_artifact_from_tool_message():
    summary, artifact = success_result(
        "demo_tool",
        "Structured summary",
        structured_payload={"value": 42},
        metadata={"source": "test"},
    )
    message = ToolMessage(
        content=summary,
        artifact=artifact,
        tool_call_id="call-123",
        name="demo_tool",
    )

    result = normalize_tool_output("demo_tool", message)

    assert result.summary == "Structured summary"
    assert result.structured_payload == {"value": 42}
    assert result.metadata["source"] == "test"


def test_success_result_caps_oversized_structured_payload():
    oversized = {"results": [{"text": "x" * 10_000} for _ in range(30)]}

    _summary, artifact = success_result(
        "demo_tool",
        "Large payload",
        structured_payload=oversized,
    )

    rendered = str(artifact["structured_payload"])
    assert artifact["tool_name"] == "demo_tool"
    assert "structured_payload_truncated" in artifact["warnings"]
    assert artifact["metadata"]["structured_payload_json_chars"] > MAX_STRUCTURED_PAYLOAD_JSON_CHARS
    assert artifact["structured_payload"]["truncated"] is True or "truncated_preview" in rendered


def test_success_result_caps_oversized_source_payload():
    oversized = {"raw": "y" * (MAX_SOURCE_PAYLOAD_JSON_CHARS + 5_000)}

    _summary, artifact = success_result(
        "demo_tool",
        "Large source payload",
        source_payload=oversized,
    )

    assert "source_payload_truncated" in artifact["warnings"]
    assert artifact["metadata"]["source_payload_json_chars"] > MAX_SOURCE_PAYLOAD_JSON_CHARS
    assert (
        artifact["source_payload"].get("truncated") is True
        or "[payload truncated]" in artifact["source_payload"]["raw"]
    )


def test_write_file_tool_returns_path_metadata(tmp_path):
    from tools.write_file_tool import WriteFileTool

    tool = WriteFileTool(root_dir=str(tmp_path))
    summary, artifact = tool._run("memory/notes.txt", "hello world")

    assert "Wrote memory/notes.txt" in summary
    assert artifact["tool_name"] == "write_file"
    assert artifact["status"] == "success"
    assert artifact["structured_payload"]["path"] == "memory/notes.txt"
    assert artifact["artifact_refs"][0]["path"].endswith("memory/notes.txt")


def test_slurm_tool_contract_includes_job_id(tmp_path):
    from tools.slurm_tool import SlurmTool

    script = tmp_path / "jobs" / "demo.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")

    completed = MagicMock()
    completed.stdout = "Submitted batch job 12345\n"
    completed.stderr = ""
    completed.returncode = 0

    tool = SlurmTool(base_dir=str(tmp_path))
    with patch("tools.slurm_tool.subprocess.run", return_value=completed):
        summary, artifact = tool._run(f"sbatch {script.relative_to(tmp_path)}")

    assert "Submitted batch job 12345" in summary
    assert artifact["tool_name"] == "slurm_tool"
    assert artifact["structured_payload"]["job_id"] == "12345"
    assert artifact["structured_payload"]["returncode"] == 0


def test_ncbi_eutils_contract_preserves_structured_payload():
    from tools.ncbi_eutils_tool import NcbiEutilsTool

    mock_resp = MagicMock()
    payload = {"esearchresult": {"count": "2", "idlist": ["1", "2"]}}
    mock_resp.json.return_value = payload
    mock_resp.text = '{"esearchresult":{"count":"2","idlist":["1","2"]}}'
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    tool = NcbiEutilsTool()
    with patch("httpx.get", return_value=mock_resp):
        summary, artifact = tool._run(operation="esearch", db="pubmed", term="TP53", retmode="json")

    assert "esearchresult" in summary
    assert artifact["tool_name"] == "ncbi_eutils"
    assert artifact["structured_payload"]["esearchresult"]["idlist"] == ["1", "2"]
    assert artifact["metadata"]["result_count"] == 2


def test_uniprot_api_contract_preserves_structured_payload():
    from tools.uniprot_api_tool import UniprotApiTool

    mock_resp = MagicMock()
    payload = {"results": [{"primaryAccession": "P04637"}]}
    mock_resp.json.return_value = payload
    mock_resp.text = '{"results":[{"primaryAccession":"P04637"}]}'
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    tool = UniprotApiTool()
    with patch("httpx.get", return_value=mock_resp):
        summary, artifact = tool._run(query="gene_exact:TP53", format="json")

    assert "P04637" in summary
    assert artifact["tool_name"] == "uniprot_api"
    assert artifact["structured_payload"]["results"][0]["primaryAccession"] == "P04637"
    assert artifact["metadata"]["result_count"] == 1


def test_ensembl_api_contract_preserves_structured_payload():
    from tools.ensembl_api_tool import EnsemblApiTool

    mock_resp = MagicMock()
    payload = {"id": "ENSG00000141510", "display_name": "TP53"}
    mock_resp.json.return_value = payload
    mock_resp.text = '{"id":"ENSG00000141510","display_name":"TP53"}'
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.raise_for_status = MagicMock()

    tool = EnsemblApiTool()
    with patch("httpx.get", return_value=mock_resp):
        summary, artifact = tool._run(endpoint="lookup/symbol/homo_sapiens/TP53")

    assert "ENSG00000141510" in summary
    assert artifact["tool_name"] == "ensembl_api"
    assert artifact["structured_payload"]["display_name"] == "TP53"


def test_search_knowledge_contract_returns_structured_hits(tmp_path):
    from tools.search_knowledge_tool import SearchKnowledgeBaseTool

    class DummyRetriever:
        def retrieve(self, _query):
            node_ref = MagicMock()
            node_ref.node.node_id = "node-1"
            node_ref.metadata = {"file_name": "tp53.md"}
            node_ref.text = "TP53 regulates the cell cycle."
            return [node_ref]

    class DummyIndex:
        def as_retriever(self, similarity_top_k):
            assert similarity_top_k == 3
            return DummyRetriever()

    tool = SearchKnowledgeBaseTool(
        knowledge_dir=str(tmp_path / "knowledge"),
        storage_dir=str(tmp_path / "storage"),
    )
    tool._index = DummyIndex()
    tool._nodes = []
    tool._built = True
    with patch.object(tool, "_ensure_index", return_value=None):
        summary, artifact = tool._run("TP53")

    assert "TP53 regulates the cell cycle." in summary
    assert artifact["tool_name"] == "search_knowledge_base"
    assert artifact["structured_payload"]["results"][0]["source"] == "tp53.md"
    assert artifact["structured_payload"]["results"][0]["retrieval_mode"] == "vector"
