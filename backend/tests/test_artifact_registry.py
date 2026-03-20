"""Tests for the file-first artifact registry."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts.naming import prepare_run_directory  # noqa: E402
from artifacts.public_urls import public_raw_file_url  # noqa: E402
from artifacts.registry import (  # noqa: E402
    ARTIFACT_REGISTRY_PATH,
    lookup_artifact_registry,
    rebuild_artifact_registry,
    refresh_artifact_registry_path,
)
from artifacts.schemas import SCHEMA_PACK_VERSION  # noqa: E402


RUN_ID = "run-20260318T190203Z-deadbeef"
RUN_DATE = "2026-03-18"
WORKFLOW = "demo-workflow"
DATASET_ID = "ds-demo-v1"


def _run_dir(base_dir: Path) -> Path:
    return base_dir / "artifacts" / WORKFLOW / RUN_DATE / RUN_ID


def _run_dir_relpath(filename: str) -> str:
    return f"artifacts/{WORKFLOW}/{RUN_DATE}/{RUN_ID}/{filename}"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_minimal_run_record(base_dir: Path) -> None:
    _write_json(
        _run_dir(base_dir) / "run.json",
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "workflow_run",
            "run_id": RUN_ID,
            "created_at": "2026-03-18T19:02:03Z",
            "source_workflow": "internal-dag-runner",
            "workflow": {
                "name": "Demo Workflow",
                "slug": WORKFLOW,
            },
            "paths": {
                "run_dir": f"artifacts/{WORKFLOW}/{RUN_DATE}/{RUN_ID}",
            },
        },
    )


def _write_dataset_manifest(base_dir: Path) -> None:
    _write_yaml(
        _run_dir(base_dir) / "dataset_manifest.yaml",
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": DATASET_ID,
            "run_id": RUN_ID,
            "created_at": "2026-03-18T19:02:03Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "sample_sheet_path": "data/demo_sample_sheet.tsv",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "demo-study",
                "experiment_type": "scrna_seq",
                "condition_summary": "demo condition summary",
                "timepoints": ["baseline"],
                "factors": ["condition"],
            },
            "source_files": ["data/demo.tsv"],
        },
    )


def _write_qa_report(base_dir: Path) -> None:
    _write_json(
        _run_dir(base_dir) / "qa_report.json",
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "qa_report",
            "id": "qa-demo-v1",
            "run_id": RUN_ID,
            "created_at": "2026-03-18T19:05:00Z",
            "source_workflow": "qa-review",
            "related_artifacts": [
                {
                    "artifact_type": "workflow_run",
                    "path": _run_dir_relpath("run.json"),
                    "run_id": RUN_ID,
                }
            ],
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        },
    )


def _write_evidence_card(base_dir: Path) -> None:
    _write_yaml(
        _run_dir(base_dir) / "evidence_card.yaml",
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "evidence_card",
            "id": "evidence-demo-v1",
            "run_id": RUN_ID,
            "created_at": "2026-03-18T19:10:00Z",
            "source_workflow": "literature-retrieval",
            "related_artifacts": [],
            "source_database": "pubmed",
            "stable_identifier": "pubmed:12345678",
            "title": "Demo evidence card",
            "claims": [
                {
                    "id": "claim-demo-1",
                    "statement": "Demo evidence statement.",
                    "confidence": "high",
                }
            ],
            "confidence": "high",
            "limitations": ["Small demonstration artifact."],
            "cached_raw_payload_path": "knowledge/cache/pubmed/12345678.md",
        },
    )


def _write_entity_grounding(base_dir: Path) -> None:
    _write_json(
        _run_dir(base_dir) / "entity_grounding.json",
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "entity_grounding",
            "id": "entity-grounding-demo-v1",
            "run_id": RUN_ID,
            "created_at": "2026-03-18T19:11:00Z",
            "source_workflow": "entity-grounding",
            "related_artifacts": [],
            "input_mentions": ["TP53"],
            "requested_species": "human",
            "requested_entity_types": ["gene"],
            "results": [
                {
                    "input_mention": "TP53",
                    "requested_entity_types": ["gene"],
                    "status": "resolved",
                    "grounded_entity": {
                        "entity_type": "gene",
                        "source_database": "ensembl",
                        "stable_identifier": "ensembl:ENSG00000141510",
                        "identifier_version": "15",
                        "preferred_label": "TP53",
                        "aliases": ["TP53", "P53"],
                        "species": "Homo sapiens",
                        "taxon_id": "taxonomy:9606",
                    },
                    "candidate_entities": [],
                    "cached_source_payload_paths": [],
                }
            ],
        },
    )


def _write_claim_graph(base_dir: Path) -> None:
    _write_json(
        _run_dir(base_dir) / "claim_graph.json",
        {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "claim_graph",
            "id": "claim-graph-demo-v1",
            "run_id": RUN_ID,
            "created_at": "2026-03-18T19:12:00Z",
            "source_workflow": "claim-graph",
            "related_artifacts": [
                {
                    "artifact_type": "evidence_card",
                    "path": _run_dir_relpath("evidence_card.yaml"),
                    "id": "evidence-demo-v1",
                    "run_id": RUN_ID,
                }
            ],
            "source_artifacts": [
                {
                    "artifact_type": "evidence_card",
                    "path": _run_dir_relpath("evidence_card.yaml"),
                    "id": "evidence-demo-v1",
                    "run_id": RUN_ID,
                }
            ],
            "contradiction_rule_set": "claim_graph_contradiction_v1",
            "claim_nodes": [
                {
                    "node_id": "claim-evidence-demo-v1-claim-demo-1",
                    "node_type": "claim",
                    "statement": "Demo evidence statement.",
                    "confidence": "high",
                    "status": "proposed",
                    "provenance": [
                        {
                            "source_type": "evidence_card_claim",
                            "artifact": {
                                "artifact_type": "evidence_card",
                                "path": _run_dir_relpath("evidence_card.yaml"),
                                "id": "evidence-demo-v1",
                                "run_id": RUN_ID,
                            },
                            "source_identifier": "claim-demo-1",
                        }
                    ],
                }
            ],
            "evidence_card_nodes": [
                {
                    "node_id": "evidence-card-evidence-demo-v1",
                    "node_type": "evidence_card",
                    "artifact": {
                        "artifact_type": "evidence_card",
                        "path": _run_dir_relpath("evidence_card.yaml"),
                        "id": "evidence-demo-v1",
                        "run_id": RUN_ID,
                    },
                    "stable_identifier": "pubmed:12345678",
                    "source_database": "pubmed",
                    "title": "Demo evidence card",
                    "confidence": "high",
                }
            ],
            "entity_nodes": [],
            "workflow_result_nodes": [],
            "edges": [
                {
                    "id": "supports-evidence-card-evidence-demo-v1-claim-evidence-demo-v1-claim-demo-1",
                    "edge_type": "supports",
                    "source_node_id": "evidence-card-evidence-demo-v1",
                    "source_node_type": "evidence_card",
                    "target_node_id": "claim-evidence-demo-v1-claim-demo-1",
                    "target_node_type": "claim",
                    "provenance_artifact": {
                        "artifact_type": "evidence_card",
                        "path": _run_dir_relpath("evidence_card.yaml"),
                        "id": "evidence-demo-v1",
                        "run_id": RUN_ID,
                    },
                    "rationale": "Evidence card contains the extracted claim statement.",
                },
                {
                    "id": "derived-from-claim-evidence-demo-v1-claim-demo-1-evidence-card-evidence-demo-v1",
                    "edge_type": "derived_from",
                    "source_node_id": "claim-evidence-demo-v1-claim-demo-1",
                    "source_node_type": "claim",
                    "target_node_id": "evidence-card-evidence-demo-v1",
                    "target_node_type": "evidence_card",
                    "provenance_artifact": {
                        "artifact_type": "evidence_card",
                        "path": _run_dir_relpath("evidence_card.yaml"),
                        "id": "evidence-demo-v1",
                        "run_id": RUN_ID,
                    },
                    "rationale": "Claim text was extracted from the evidence card artifact.",
                },
            ],
            "summary": {
                "claim_count": 1,
                "evidence_card_count": 1,
                "entity_count": 0,
                "workflow_result_count": 0,
                "edge_count": 2,
                "contradiction_count": 0,
                "source_artifact_count": 1,
            },
        },
    )


def _workflow_plan_payload() -> dict:
    return {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "workflow_plan",
        "run_id": RUN_ID,
        "created_at": "2026-03-18T19:06:00Z",
        "source_workflow": WORKFLOW,
        "steps": [
            {"id": "qc", "name": "QC"},
            {"id": "report", "name": "Report"},
        ],
    }


def _provenance_payload() -> dict:
    return {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "provenance",
        "id": f"provenance-{WORKFLOW}-{RUN_ID.lower()}",
        "run_id": RUN_ID,
        "created_at": "2026-03-18T19:07:00Z",
        "source_workflow": WORKFLOW,
        "related_artifacts": [
            {
                "artifact_type": "workflow_run",
                "path": _run_dir_relpath("run.json"),
                "run_id": RUN_ID,
            }
        ],
        "bundle_format": {
            "primary_package": "ro_crate",
            "ro_crate_version": "1.2",
            "lineage_model": "prov_compatible",
        },
        "workflow": {
            "workflow_id": WORKFLOW,
            "name": "Demo Workflow",
            "slug": WORKFLOW,
            "version": "1.0.0",
            "engine": "internal_dag_runner_v1",
            "run_record_path": _run_dir_relpath("run.json"),
            "lifecycle_status": "completed",
            "qc_status": "passed",
        },
        "terminal_state": {
            "lifecycle_status": "completed",
            "representation": "Completed runs include persisted inputs, outputs, and step lineage.",
            "is_partial": False,
        },
        "environment": {},
        "tool_versions": [],
        "exports": {
            "provenance_path": _run_dir_relpath("prov.json"),
            "ro_crate_metadata_path": _run_dir_relpath("ro-crate/ro-crate-metadata.json"),
            "exported_at": "2026-03-18T19:07:00Z",
        },
        "entity": {},
        "activity": {},
        "agent": {},
        "used": [],
        "wasGeneratedBy": [],
        "wasAssociatedWith": [],
        "conforms_to": {
            "ro_crate": "https://w3id.org/ro/crate/1.2",
            "prov": "https://www.w3.org/TR/prov-overview/",
        },
    }


def _biocompute_payload() -> dict:
    return {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "biocompute",
        "id": f"biocompute-{WORKFLOW}-{RUN_ID.lower()}",
        "run_id": RUN_ID,
        "created_at": "2026-03-18T19:08:00Z",
        "source_workflow": WORKFLOW,
        "related_artifacts": [
            {
                "artifact_type": "workflow_run",
                "path": _run_dir_relpath("run.json"),
                "id": f"workflow_run:{RUN_ID.lower()}",
                "run_id": RUN_ID,
            },
            {
                "artifact_type": "provenance",
                "path": _run_dir_relpath("prov.json"),
                "id": f"provenance-{WORKFLOW}-{RUN_ID.lower()}",
                "run_id": RUN_ID,
            },
        ],
        "spec_version": "https://w3id.org/ieee/ieee-2791-schema/2791object.json",
        "object_id": "urn:uuid:5d1972ec-e66b-528d-9066-c6f63bf1af37",
        "type": "demo_pipeline",
        "etag": "a760bef3b98f9e2df4da72108a42bc7d91a02f1bc4387ab9d282354af9b8c398",
        "provenance_domain": {
            "name": "Demo Workflow BioCompute export",
            "version": "1.0.0",
            "created": "2026-03-18T19:02:03Z",
            "modified": "2026-03-18T19:08:00Z",
            "contributors": [
                {
                    "name": "internal_dag_runner_v1",
                    "contribution": ["createdBy"],
                }
            ],
            "license": "NOASSERTION",
        },
        "usability_domain": [
            "Demonstration BioCompute export for registry coverage.",
            "Terminal workflow status is 'completed' with QC status 'passed'.",
        ],
        "description_domain": {
            "keywords": ["demo", "biocompute", WORKFLOW],
            "xref": [
                {
                    "namespace": "taxonomy",
                    "name": "NCBI Taxonomy",
                    "ids": ["9606"],
                    "access_time": "2026-03-18T19:08:00Z",
                }
            ],
            "platform": ["linux", "internal_dag_runner_v1"],
            "pipeline_steps": [
                {
                    "step_number": 1,
                    "name": "QC",
                    "description": "QC. Recorded status: completed.",
                    "version": "1.0.0",
                    "prerequisite": [],
                    "input_list": [],
                    "output_list": [],
                }
            ],
        },
        "execution_domain": {
            "script": [{"uri": {"uri": "tool://internal_dag_runner_v1", "filename": "internal_dag_runner_v1.tool"}}],
            "script_driver": "internal_dag_runner_v1",
            "software_prerequisites": [
                {
                    "name": "internal_dag_runner_v1",
                    "version": "1.0.0",
                    "uri": {"uri": "tool://internal_dag_runner_v1"},
                }
            ],
            "external_data_endpoints": [],
            "environment_variables": {"PLATFORM": "linux"},
        },
        "parametric_domain": [],
        "io_domain": {
            "input_subdomain": [],
            "output_subdomain": [
                {
                    "mediatype": "application/json",
                    "uri": {
                        "uri": public_raw_file_url(_run_dir_relpath("qa_report.json")),
                        "filename": "qa_report.json",
                        "access_time": "2026-03-18T19:05:00Z",
                    },
                }
            ],
        },
        "error_domain": {
            "empirical_error": {
                "urn:bioapex:biocompute:error:observed-run-state:1.0.0": {
                    "title": "Observed workflow state",
                    "description": "Observed terminal workflow warnings and errors carried into this BioCompute export.",
                    "observed": {
                        "lifecycle_status": "completed",
                        "qc_status": "passed",
                        "warning_count": 0,
                        "error_count": 0,
                    },
                    "severity": "info",
                    "messages": [],
                }
            },
            "algorithmic_error": {
                "urn:bioapex:biocompute:error:export-completeness:1.0.0": {
                    "title": "Export completeness",
                    "description": "Algorithmic limits encountered while deriving the BioCompute export from canonical persisted artifacts.",
                    "observed": {
                        "export_status": "full",
                        "warning_count": 0,
                    },
                    "expected": {
                        "export_status": "full",
                        "warning_count": 0,
                    },
                    "severity": "info",
                    "messages": [],
                }
            },
        },
        "extension_domain": [
            {
                "extension_schema": public_raw_file_url(
                    "artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json"
                ),
                "bioapex_extension": {
                    "export_status": "full",
                    "export_warnings": [],
                    "workflow_run": {
                        "artifact_type": "workflow_run",
                        "path": _run_dir_relpath("run.json"),
                        "id": f"workflow_run:{RUN_ID.lower()}",
                        "run_id": RUN_ID,
                    },
                    "provenance_exports": [
                        _run_dir_relpath("prov.json"),
                        _run_dir_relpath("ro-crate/ro-crate-metadata.json"),
                    ],
                    "provenance_artifact": {
                        "artifact_type": "provenance",
                        "path": _run_dir_relpath("prov.json"),
                        "id": f"provenance-{WORKFLOW}-{RUN_ID.lower()}",
                        "run_id": RUN_ID,
                    },
                    "internal_references": [
                        {
                            "artifact_type": "qa_report",
                            "path": _run_dir_relpath("qa_report.json"),
                            "id": f"qa-report-{RUN_ID.lower()}",
                            "run_id": RUN_ID,
                        }
                    ],
                },
            }
        ],
    }


def _write_registry_fixture(base_dir: Path) -> None:
    _write_minimal_run_record(base_dir)
    _write_dataset_manifest(base_dir)
    _write_qa_report(base_dir)


@pytest.fixture
def isolated_registry_root(tmp_path):
    _write_registry_fixture(tmp_path)
    return tmp_path


class TestArtifactRegistryService:
    def test_rebuild_persists_registry_and_indexes_canonical_artifacts(self, isolated_registry_root):
        snapshot = rebuild_artifact_registry(isolated_registry_root)

        assert snapshot.record_count == 3
        assert snapshot.valid_count == 3
        assert snapshot.invalid_count == 0

        registry_path = isolated_registry_root / ARTIFACT_REGISTRY_PATH
        assert registry_path.is_file()

        records_by_type = {record.artifact_type: record for record in snapshot.records}
        assert records_by_type["workflow_run"].artifact_id == f"workflow_run:{RUN_ID}"
        assert records_by_type["workflow_run"].dataset_id == DATASET_ID
        assert records_by_type["dataset_manifest"].artifact_id == DATASET_ID
        assert records_by_type["qa_report"].dataset_id == DATASET_ID

    def test_rebuild_indexes_reserved_generated_and_ro_crate_artifacts(self, isolated_registry_root):
        _write_json(_run_dir(isolated_registry_root) / "workflow_plan.json", _workflow_plan_payload())
        _write_json(_run_dir(isolated_registry_root) / "prov.json", _provenance_payload())
        _write_json(_run_dir(isolated_registry_root) / "biocompute.json", _biocompute_payload())
        (_run_dir(isolated_registry_root) / "inputs" / "user").mkdir(parents=True, exist_ok=True)
        (_run_dir(isolated_registry_root) / "inputs" / "user" / "sample-sheet__patients.csv").write_text(
            "patient_id\nP1\n",
            encoding="utf-8",
        )
        (_run_dir(isolated_registry_root) / "outputs" / "generated").mkdir(parents=True, exist_ok=True)
        (_run_dir(isolated_registry_root) / "outputs" / "generated" / "volcano_plot.png").write_bytes(b"plot")
        (_run_dir(isolated_registry_root) / "ro-crate").mkdir(exist_ok=True)
        _write_json(
            _run_dir(isolated_registry_root) / "ro-crate" / "ro-crate-metadata.json",
            {"@context": "https://w3id.org/ro/crate/1.1/context"},
        )

        snapshot = rebuild_artifact_registry(isolated_registry_root)

        assert snapshot.record_count == 10
        assert {record.artifact_type for record in snapshot.records} >= {
            "workflow_run",
            "dataset_manifest",
            "qa_report",
            "workflow_plan",
            "provenance",
            "biocompute",
            "user_input",
            "figure",
            "ro_crate",
            "ro_crate_entry",
        }

    def test_lookup_filters_by_run_workflow_type_and_dataset(self, isolated_registry_root):
        rebuild_artifact_registry(isolated_registry_root)

        result = lookup_artifact_registry(
            isolated_registry_root,
            run_id=RUN_ID,
            artifact_type="qa_report",
            workflow=WORKFLOW,
            date=RUN_DATE,
            dataset_id=DATASET_ID,
        )

        assert result.total_count == 3
        assert result.matched_count == 1
        assert result.records[0].path == _run_dir_relpath("qa_report.json")

    def test_refresh_path_adds_new_artifact_without_full_rescan_contract(self, isolated_registry_root):
        rebuild_artifact_registry(isolated_registry_root)
        _write_evidence_card(isolated_registry_root)

        record = refresh_artifact_registry_path(
            isolated_registry_root,
            _run_dir_relpath("evidence_card.yaml"),
        )
        assert record is not None
        assert record.status == "valid"
        assert record.artifact_type == "evidence_card"
        assert record.dataset_id == DATASET_ID

        refreshed = lookup_artifact_registry(
            isolated_registry_root,
            artifact_type="evidence_card",
            dataset_id=DATASET_ID,
        )
        assert refreshed.matched_count == 1
        assert refreshed.records[0].path == _run_dir_relpath("evidence_card.yaml")

    def test_refresh_path_indexes_entity_grounding_artifact(self, isolated_registry_root):
        rebuild_artifact_registry(isolated_registry_root)
        _write_entity_grounding(isolated_registry_root)

        record = refresh_artifact_registry_path(
            isolated_registry_root,
            _run_dir_relpath("entity_grounding.json"),
        )
        assert record is not None
        assert record.status == "valid"
        assert record.artifact_type == "entity_grounding"

        refreshed = lookup_artifact_registry(
            isolated_registry_root,
            artifact_type="entity_grounding",
        )
        assert refreshed.matched_count == 1
        assert refreshed.records[0].path == _run_dir_relpath("entity_grounding.json")

    def test_refresh_path_indexes_claim_graph_artifact(self, isolated_registry_root):
        rebuild_artifact_registry(isolated_registry_root)
        _write_evidence_card(isolated_registry_root)
        _write_claim_graph(isolated_registry_root)

        record = refresh_artifact_registry_path(
            isolated_registry_root,
            _run_dir_relpath("claim_graph.json"),
        )
        assert record is not None
        assert record.status == "valid"
        assert record.artifact_type == "claim_graph"

        refreshed = lookup_artifact_registry(
            isolated_registry_root,
            artifact_type="claim_graph",
        )
        assert refreshed.matched_count == 1
        assert refreshed.records[0].path == _run_dir_relpath("claim_graph.json")

    def test_prepare_run_directory_registers_root_artifacts_immediately(self, tmp_path):
        prepare_run_directory(
            tmp_path,
            "Demo Workflow",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id=RUN_ID,
        )

        result = lookup_artifact_registry(tmp_path, include_invalid=True)

        assert result.matched_count == 2
        assert {record.artifact_type for record in result.records} == {
            "content_hash_manifest",
            "workflow_run",
        }
        assert {record.path for record in result.records} == {
            _run_dir_relpath("content_hashes.json"),
            _run_dir_relpath("run.json"),
        }

    def test_run_layout_writes_refresh_registry_for_stable_and_generated_outputs(self, tmp_path):
        layout = prepare_run_directory(
            tmp_path,
            "Demo Workflow",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id=RUN_ID,
        )

        layout.stable_artifact_path("workflow_plan").write_text(
            json.dumps(_workflow_plan_payload(), indent=2) + "\n",
            encoding="utf-8",
        )
        layout.generated_output_path("volcano plot.png").write_bytes(b"plot")
        layout.stable_artifact_path("provenance").write_text(
            json.dumps(_provenance_payload(), indent=2) + "\n",
            encoding="utf-8",
        )
        layout.stable_artifact_path("biocompute").write_text(
            json.dumps(_biocompute_payload(), indent=2) + "\n",
            encoding="utf-8",
        )

        result = lookup_artifact_registry(tmp_path, include_invalid=True)

        assert {record.artifact_type for record in result.records} >= {
            "content_hash_manifest",
            "biocompute",
            "figure",
            "provenance",
            "workflow_plan",
            "workflow_run",
        }

    def test_ro_crate_child_writes_preserve_tracking_and_refresh_registry(self, tmp_path):
        layout = prepare_run_directory(
            tmp_path,
            "Demo Workflow",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id=RUN_ID,
        )

        ro_crate_dir = layout.stable_artifact_path("ro_crate")
        ro_crate_dir.mkdir()
        (ro_crate_dir / "ro-crate-metadata.json").write_text(
            json.dumps({"@context": "https://w3id.org/ro/crate/1.1/context"}, indent=2) + "\n",
            encoding="utf-8",
        )

        result = lookup_artifact_registry(tmp_path, include_invalid=True)

        assert {record.artifact_type for record in result.records} >= {
            "ro_crate",
            "ro_crate_entry",
        }
        assert {record.path for record in result.records} >= {
            _run_dir_relpath("ro-crate"),
            _run_dir_relpath("ro-crate/ro-crate-metadata.json"),
        }

    def test_rebuild_marks_malformed_artifacts_invalid_instead_of_crashing(self, tmp_path):
        _write_minimal_run_record(tmp_path)
        (_run_dir(tmp_path) / "compliance_report.json").write_text("{bad json\n", encoding="utf-8")

        snapshot = rebuild_artifact_registry(tmp_path)

        assert snapshot.record_count == 2
        assert snapshot.valid_count == 1
        assert snapshot.invalid_count == 1

        invalid = next(record for record in snapshot.records if record.status == "invalid")
        assert invalid.artifact_type == "compliance_report"
        assert invalid.path == _run_dir_relpath("compliance_report.json")
        assert invalid.error is not None

        default_lookup = lookup_artifact_registry(tmp_path)
        assert default_lookup.matched_count == 1

        with_invalid = lookup_artifact_registry(tmp_path, include_invalid=True)
        assert with_invalid.matched_count == 2


class TestArtifactRegistryApi:
    def test_api_routes_expose_lookup_and_rebuild(self, isolated_registry_root):
        from graph.agent import agent_manager
        from api.artifact_registry import list_artifact_registry, rebuild_registry

        original_base_dir = agent_manager.base_dir
        try:
            agent_manager.base_dir = isolated_registry_root

            rebuilt = rebuild_registry()
            assert rebuilt["record_count"] == 3
            assert rebuilt["valid_count"] == 3

            listed = list_artifact_registry(workflow=WORKFLOW, dataset_id=DATASET_ID)
            assert listed["matched_count"] == 3
            assert {record["artifact_type"] for record in listed["records"]} == {
                "dataset_manifest",
                "qa_report",
                "workflow_run",
            }
        finally:
            agent_manager.base_dir = original_base_dir
