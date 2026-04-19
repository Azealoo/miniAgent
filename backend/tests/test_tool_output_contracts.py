import json
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from langchain_core.messages import ToolMessage

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.contracts import (
    MAX_SOURCE_PAYLOAD_JSON_CHARS,
    MAX_STRUCTURED_PAYLOAD_JSON_CHARS,
    needs_approval_result,
    normalize_tool_output,
    streaming_chunk_result,
    success_result,
)


def test_needs_approval_result_marks_envelope_with_typed_error():
    summary, artifact = needs_approval_result(
        "terminal",
        "Tool gated by policy.",
        metadata={"policy_approval_reason": "requires_approval"},
    )

    assert summary.startswith("[NEEDS_APPROVAL]")
    assert artifact["status"] == "error"
    assert artifact["outcome"] == "needs_approval"
    assert artifact["error"]["code"] == "needs_approval"
    assert artifact["error"]["retriable"] is False
    assert artifact["metadata"]["policy_approval_reason"] == "requires_approval"


def test_streaming_chunk_result_is_classified_as_success_with_chunk_metadata():
    summary, artifact = streaming_chunk_result(
        "terminal",
        "stdout chunk",
        chunk_index=2,
        chunk="hello world\n",
    )

    assert summary == "stdout chunk"
    assert artifact["status"] == "success"
    assert artifact["outcome"] == "streaming_chunk"
    assert artifact["error"] is None
    assert artifact["metadata"]["chunk_index"] == 2
    assert artifact["metadata"]["chunk_terminal"] is False
    assert artifact["metadata"]["chunk_text"] == "hello world\n"


def test_streaming_chunk_result_rejects_negative_chunk_index():
    import pytest

    with pytest.raises(ValueError):
        streaming_chunk_result(
            "terminal",
            "x",
            chunk_index=-1,
            chunk="x",
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


def test_slurm_tool_structured_submit_persists_job_record(tmp_path):
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
        summary, artifact = tool._run(
            action="submit",
            script_path="jobs/demo.sh",
            run_id="run-20260320T120000Z-deadbeef",
            resource_request={"cpus": 4, "memory": "32G", "wall_time": "02:00:00"},
        )

    relpath = artifact["structured_payload"]["job_record_path"]
    persisted = json.loads((tmp_path / relpath).read_text(encoding="utf-8"))

    assert "Submitted Slurm job 12345" in summary
    assert artifact["tool_name"] == "slurm_tool"
    assert persisted["artifact_type"] == "slurm_job"
    assert persisted["job_id"] == "12345"
    assert persisted["resource_request"]["cpus"] == 4
    assert artifact["artifact_refs"][0]["artifact_type"] == "slurm_job"
    assert relpath == "artifacts/slurm-jobs/2026-03-20/run-20260320T120000Z-deadbeef/slurm_job.json"


def test_slurm_tool_structured_status_updates_job_record(tmp_path):
    from tools.slurm_tool import SlurmTool

    run_dir = (
        tmp_path
        / "artifacts"
        / "slurm-jobs"
        / "2026-03-20"
        / "run-20260320T120000Z-deadbeef"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    job_record_path = run_dir / "slurm_job.json"
    job_record_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "artifact_type": "slurm_job",
                "id": "slurm-job-12345-run-20260320t120000z-deadbeef",
                "run_id": "run-20260320T120000Z-deadbeef",
                "created_at": "2026-03-20T12:00:00Z",
                "source_tool": "slurm_tool",
                "related_artifacts": [],
                "job_id": "12345",
                "job_name": "demo",
                "script_path": "jobs/demo.sh",
                "working_directory": ".",
                "submission_command": ["sbatch", "jobs/demo.sh"],
                "resource_request": {"cpus": 4, "memory": "32G", "wall_time": "02:00:00"},
                "status": "pending",
                "submitted_at": "2026-03-20T12:00:00Z",
                "completed_at": None,
                "latest_status": {
                    "observed_at": "2026-03-20T12:00:00Z",
                    "source": "submission",
                    "normalized_status": "pending",
                    "raw_state": "SUBMITTED",
                    "raw_reason": None,
                    "exit_code": None,
                },
                "status_history": [
                    {
                        "observed_at": "2026-03-20T12:00:00Z",
                        "source": "submission",
                        "normalized_status": "pending",
                        "raw_state": "SUBMITTED",
                        "raw_reason": None,
                        "exit_code": None,
                    }
                ],
                "logs": {
                    "stdout_path": "artifacts/slurm-jobs/2026-03-20/run-20260320T120000Z-deadbeef/outputs/generated/slurm/demo-12345.stdout.log",
                    "stderr_path": "artifacts/slurm-jobs/2026-03-20/run-20260320T120000Z-deadbeef/outputs/generated/slurm/demo-12345.stderr.log",
                    "submission_stdout": "Submitted batch job 12345\n",
                    "submission_stderr": None,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stdout_log_path = (
        tmp_path
        / "artifacts"
        / "slurm-jobs"
        / "2026-03-20"
        / "run-20260320T120000Z-deadbeef"
        / "outputs"
        / "generated"
        / "slurm"
        / "demo-12345.stdout.log"
    )
    stderr_log_path = (
        tmp_path
        / "artifacts"
        / "slurm-jobs"
        / "2026-03-20"
        / "run-20260320T120000Z-deadbeef"
        / "outputs"
        / "generated"
        / "slurm"
        / "demo-12345.stderr.log"
    )
    stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_log_path.write_text("runtime stdout\n", encoding="utf-8")
    stderr_log_path.write_text("runtime stderr\n", encoding="utf-8")

    squeue_result = MagicMock()
    squeue_result.stdout = ""
    squeue_result.stderr = ""
    squeue_result.returncode = 0

    sacct_result = MagicMock()
    sacct_result.stdout = (
        "12345|COMPLETED|0:0|00:40:00|02:00:00|None|"
        f"{tmp_path}|"
        f"{tmp_path}/artifacts/slurm-jobs/2026-03-20/run-20260320T120000Z-deadbeef/outputs/generated/slurm/demo-12345.stdout.log|"
        f"{tmp_path}/artifacts/slurm-jobs/2026-03-20/run-20260320T120000Z-deadbeef/outputs/generated/slurm/demo-12345.stderr.log|"
        "demo\n"
    )
    sacct_result.stderr = ""
    sacct_result.returncode = 0

    tool = SlurmTool(base_dir=str(tmp_path))
    with patch("tools.slurm_tool.subprocess.run", side_effect=[squeue_result, sacct_result]):
        summary, artifact = tool._run(
            action="status",
            job_record_path="artifacts/slurm-jobs/2026-03-20/run-20260320T120000Z-deadbeef/slurm_job.json",
        )

    updated = json.loads(job_record_path.read_text(encoding="utf-8"))

    assert summary == "Job 12345 status: completed."
    assert artifact["structured_payload"]["status"] == "completed"
    assert artifact["structured_payload"]["runtime_stdout"] == "runtime stdout"
    assert artifact["structured_payload"]["runtime_stderr"] == "runtime stderr"
    assert updated["status"] == "completed"
    assert updated["completed_at"] == updated["latest_status"]["observed_at"]
    assert updated["logs"]["runtime_stdout"] == "runtime stdout"
    assert updated["logs"]["runtime_stderr"] == "runtime stderr"


def test_slurm_runtime_log_reader_caps_file_reads(monkeypatch):
    import tools.slurm_monitor as slurm_monitor_module

    read_sizes: list[int] = []

    class _FakeReader:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> str:
            read_sizes.append(size)
            if size < 0:
                raise AssertionError("Runtime log reader should use a bounded read size.")
            return "x" * size

    class _FakePath:
        def exists(self) -> bool:
            return True

        def is_file(self) -> bool:
            return True

        def open(self, mode: str = "r", encoding: str | None = None, errors: str | None = None):
            assert mode == "r"
            assert encoding == "utf-8"
            assert errors == "replace"
            return _FakeReader()

    monkeypatch.setattr(
        slurm_monitor_module,
        "_resolve_under_base",
        lambda *args, **kwargs: (_FakePath(), "logs/demo.stdout.log"),
    )

    rendered = slurm_monitor_module._read_runtime_log(Path("/tmp"), "logs/demo.stdout.log")

    assert read_sizes == [slurm_monitor_module._MAX_OUTPUT + 1]
    assert rendered is not None
    assert rendered.startswith("x" * slurm_monitor_module._MAX_OUTPUT)
    assert rendered.endswith("\n...[truncated]")


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


def test_entity_grounding_tool_contract_reports_structured_results(tmp_path):
    from tools.entity_grounding_tool import EntityGroundingTool

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
                response = MagicMock()
                response.text = '{"id":"ENSG00000141510","display_name":"TP53"}'
                response.status_code = 200
                response.headers = {"content-type": "application/json"}
                response.raise_for_status = MagicMock()
                response.json.return_value = payload
                return response
            request = httpx.Request("GET", url)
            response = MagicMock()
            response.text = ""
            response.status_code = 404
            response.headers = {"content-type": "application/json"}
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 error",
                request=request,
                response=httpx.Response(404, request=request),
            )
            response.json.return_value = {}
            return response

        if parsed.netloc == "rest.uniprot.org" and 'gene:TP53 AND organism_name:"Mus musculus"' in query:
            payload = {"results": []}
            response = MagicMock()
            response.text = '{"results":[]}'
            response.status_code = 200
            response.headers = {"content-type": "application/json"}
            response.raise_for_status = MagicMock()
            response.json.return_value = payload
            return response

        raise AssertionError(f"Unexpected URL: {url}")

    tool = EntityGroundingTool(base_dir=str(tmp_path))
    with patch("httpx.get", side_effect=_dispatch):
        summary, artifact = tool._run(mentions=["TP53"], entity_types=["gene"])

    assert "Grounded 1 of 1 mention(s)" in summary
    assert artifact["tool_name"] == "entity_grounding"
    assert artifact["structured_payload"]["requires_clarification"] is False
    assert artifact["metadata"]["requires_clarification"] is False
    assert artifact["structured_payload"]["resolved_entities"][0]["stable_identifier"] == "ensembl:ENSG00000141510"
    assert artifact["artifact_refs"][0]["artifact_type"] == "entity_grounding"


def test_entity_grounding_tool_contract_reports_clarification_required_state(tmp_path):
    from tools.entity_grounding_tool import EntityGroundingTool

    def _dispatch(url: str, timeout: int = 25, headers: dict | None = None):  # noqa: ARG001
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.lstrip("/")

        if parsed.netloc == "rest.ensembl.org":
            if path == "lookup/symbol/homo_sapiens/ACTB":
                payload = {
                    "id": "ENSG00000075624",
                    "display_name": "ACTB",
                    "object_type": "Gene",
                    "species": "homo_sapiens",
                    "version": 9,
                }
                response = MagicMock()
                response.text = '{"id":"ENSG00000075624","display_name":"ACTB"}'
                response.status_code = 200
                response.headers = {"content-type": "application/json"}
                response.raise_for_status = MagicMock()
                response.json.return_value = payload
                return response
            if path == "lookup/symbol/mus_musculus/ACTB":
                payload = {
                    "id": "ENSMUSG00000029580",
                    "display_name": "ACTB",
                    "object_type": "Gene",
                    "species": "mus_musculus",
                    "version": 4,
                }
                response = MagicMock()
                response.text = '{"id":"ENSMUSG00000029580","display_name":"ACTB"}'
                response.status_code = 200
                response.headers = {"content-type": "application/json"}
                response.raise_for_status = MagicMock()
                response.json.return_value = payload
                return response
            request = httpx.Request("GET", url)
            response = MagicMock()
            response.text = ""
            response.status_code = 404
            response.headers = {"content-type": "application/json"}
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404 error",
                request=request,
                response=httpx.Response(404, request=request),
            )
            response.json.return_value = {}
            return response

        raise AssertionError(f"Unexpected URL: {url}")

    tool = EntityGroundingTool(base_dir=str(tmp_path))
    with patch("httpx.get", side_effect=_dispatch):
        summary, artifact = tool._run(mentions=["ACTB"], entity_types=["gene"])

    assert summary == "Grounding requires clarification for 1 of 1 mention(s)."
    assert artifact["tool_name"] == "entity_grounding"
    assert artifact["status"] == "success"
    assert artifact["outcome"] == "success_empty"
    assert artifact["structured_payload"]["requires_clarification"] is True
    assert artifact["metadata"]["requires_clarification"] is True
    assert artifact["structured_payload"]["results"][0]["status"] == "ambiguous"
    assert len(artifact["structured_payload"]["results"][0]["candidate_entities"]) == 2


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


def test_claim_graph_tool_contract_reports_workflow_backed_claims(tmp_path):
    from artifacts.schemas import SCHEMA_PACK_VERSION
    from tools.claim_graph_tool import ClaimGraphTool

    relpath = "artifacts/rna-seq-qc/2026-03-18/run-20260318T200500Z-abcddcba/run.json"
    payload = {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "workflow_run",
        "id": "workflow-run-rna-seq-qc-demo-v1",
        "run_id": "run-20260318T200500Z-abcddcba",
        "created_at": "2026-03-18T20:05:00Z",
        "source_workflow": "internal-dag-runner",
        "related_artifacts": [],
        "workflow": {
            "name": "RNA Seq QC",
            "slug": "rna-seq-qc",
        },
        "lifecycle_status": "completed",
        "qc_status": "warning",
        "engine": "internal_dag_runner_v1",
        "parameters": {"min_genes": 200},
        "environment": {"conda_env": "miniAgent"},
        "inputs": [],
        "outputs": [],
        "qc_summary": "Batch-effect warning remained after QC evaluation.",
        "warnings": ["one donor replicate fell below the warning threshold"],
    }

    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tool = ClaimGraphTool(base_dir=str(tmp_path))
    summary, artifact = tool._run(
        workflow_run_paths=[relpath],
        include_related_artifacts=False,
    )

    assert "Built claim graph" in summary
    assert artifact["tool_name"] == "claim_graph"
    assert artifact["status"] == "success"
    assert artifact["structured_payload"]["summary"]["claim_count"] == 4
    assert artifact["structured_payload"]["summary"]["workflow_result_count"] == 1
    assert artifact["structured_payload"]["summary"]["evidence_card_count"] == 0
    assert artifact["metadata"]["workflow_result_count"] == 1
    assert any(
        node["statement"] == "Workflow RNA Seq QC reached lifecycle status completed."
        for node in artifact["structured_payload"]["claim_nodes"]
    )
    assert any(
        ref["artifact_type"] == "workflow_run" and ref["path"] == relpath
        for ref in artifact["artifact_refs"]
    )
