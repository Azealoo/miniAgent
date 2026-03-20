"""Tests for the deterministic dataset intake gate."""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from artifacts.schemas import SCHEMA_PACK_VERSION  # noqa: E402
from dataset_intake import (  # noqa: E402
    DatasetIntakeValidationError,
    ensure_valid_dataset_intake_manifest,
    validate_dataset_intake_manifest,
)
from workflows.runners.perturb_seq import validate_inputs as validate_perturb_seq_inputs  # noqa: E402


def _manifest_payload() -> dict:
    return {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "dataset_manifest",
        "id": "ds-test-v1",
        "run_id": "run-20260318T193000Z-deadbeef",
        "created_at": "2026-03-18T19:30:00Z",
        "source_workflow": "dataset-intake",
        "related_artifacts": [],
        "assay_type": "scrna_seq",
        "organism": "homo_sapiens",
        "reference_build": "grch38",
        "sample_sheet_path": "data/sample_sheet.tsv",
        "privacy_classification": "controlled",
        "design": {
            "study_name": "test-study",
            "experiment_type": "scrna_seq",
            "condition_summary": "case control single-cell study",
            "analysis_kind": "comparative",
            "condition_fields": ["condition"],
            "batch_fields": ["donor"],
            "timepoints": ["baseline"],
            "factors": ["condition", "donor"],
        },
        "source_files": [
            "data/counts.h5ad",
            "data/metadata.tsv",
        ],
    }


def _write_manifest(base_dir: Path, payload: dict) -> str:
    manifest_relpath = "manifests/dataset_manifest.yaml"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return manifest_relpath


class TestDatasetIntakeValidation:
    def test_validate_dataset_intake_reports_missing_referenced_files(self, tmp_path):
        manifest_relpath = _write_manifest(tmp_path, _manifest_payload())

        result = validate_dataset_intake_manifest(tmp_path, manifest_relpath)

        assert not result.ok
        assert [issue.field_path for issue in result.issues] == [
            "sample_sheet_path",
            "source_files[0]",
            "source_files[1]",
        ]
        assert all(issue.code == "missing_file" for issue in result.issues)
        assert result.checked_paths == [
            manifest_relpath,
            "data/sample_sheet.tsv",
            "data/counts.h5ad",
            "data/metadata.tsv",
        ]

    def test_validate_dataset_intake_normalizes_schema_and_design_issues(self, tmp_path):
        payload = _manifest_payload()
        payload.pop("sample_sheet_path")
        payload.pop("reference_build")
        payload["design"] = {
            "study_name": "test-study",
            "experiment_type": "scrna_seq",
            "condition_summary": "case control single-cell study",
            "analysis_kind": "comparative",
        }
        manifest_relpath = _write_manifest(tmp_path, payload)

        result = validate_dataset_intake_manifest(tmp_path, manifest_relpath)

        assert not result.ok
        assert any(issue.field_path == "sample_sheet_path" and issue.code == "missing_field" for issue in result.issues)
        assert any(
            issue.field_path == "design.condition_fields" and issue.code == "missing_field"
            for issue in result.issues
        )
        assert any(
            issue.field_path == "manifest" and "reference_build or reference_resource" in issue.message
            for issue in result.issues
        )

    def test_validate_dataset_intake_reports_missing_sample_sheet_alongside_schema_errors(self, tmp_path):
        payload = _manifest_payload()
        payload.pop("sample_sheet_path")
        payload["assay_type"] = "not_real"
        manifest_relpath = _write_manifest(tmp_path, payload)

        result = validate_dataset_intake_manifest(tmp_path, manifest_relpath)

        assert not result.ok
        assert any(issue.field_path == "assay_type" and issue.code == "invalid_value" for issue in result.issues)
        assert any(issue.field_path == "sample_sheet_path" and issue.code == "missing_field" for issue in result.issues)

    def test_ensure_valid_dataset_intake_returns_manifest_when_paths_exist(self, tmp_path):
        manifest_relpath = _write_manifest(tmp_path, _manifest_payload())
        for relpath in ("data/sample_sheet.tsv", "data/counts.h5ad", "data/metadata.tsv"):
            target = tmp_path / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("placeholder\n", encoding="utf-8")

        result = ensure_valid_dataset_intake_manifest(tmp_path, manifest_relpath)

        assert result.ok
        assert result.manifest is not None
        assert result.manifest.sample_sheet_path == "data/sample_sheet.tsv"
        assert result.manifest.design.condition_fields == ["condition"]

    def test_ensure_valid_dataset_intake_raises_with_machine_readable_result(self, tmp_path):
        manifest_relpath = _write_manifest(tmp_path, _manifest_payload())

        with pytest.raises(DatasetIntakeValidationError) as exc_info:
            ensure_valid_dataset_intake_manifest(tmp_path, manifest_relpath)

        assert not exc_info.value.result.ok
        assert exc_info.value.result.issues[0].field_path == "sample_sheet_path"
        assert "Dataset intake validation failed:" in str(exc_info.value)

    def test_ensure_valid_dataset_intake_accepts_reference_resource_without_reference_build(self, tmp_path):
        payload = _manifest_payload()
        payload.pop("reference_build")
        payload["reference_resource"] = "ensembl-release-112"
        manifest_relpath = _write_manifest(tmp_path, payload)
        for relpath in ("data/sample_sheet.tsv", "data/counts.h5ad", "data/metadata.tsv"):
            target = tmp_path / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("placeholder\n", encoding="utf-8")

        result = ensure_valid_dataset_intake_manifest(tmp_path, manifest_relpath)

        assert result.ok
        assert result.manifest is not None
        assert result.manifest.reference_build is None
        assert result.manifest.reference_resource == "ensembl-release-112"

    def test_ensure_valid_dataset_intake_rejects_reference_build_mismatch(self, tmp_path):
        manifest_relpath = _write_manifest(tmp_path, _manifest_payload())
        for relpath in ("data/sample_sheet.tsv", "data/counts.h5ad", "data/metadata.tsv"):
            target = tmp_path / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("placeholder\n", encoding="utf-8")

        with pytest.raises(DatasetIntakeValidationError) as exc_info:
            ensure_valid_dataset_intake_manifest(
                tmp_path,
                manifest_relpath,
                expected_reference_build="hg38",
            )

        issues = exc_info.value.result.issues
        assert any(issue.field_path == "reference_build" and issue.code == "invalid_value" for issue in issues)
        assert "workflow input reference_build 'hg38'" in str(exc_info.value)

    def test_perturb_seq_preflight_checks_workflow_reference_build(self, tmp_path):
        manifest_relpath = _write_manifest(tmp_path, _manifest_payload())
        for relpath in ("data/sample_sheet.tsv", "data/counts.h5ad", "data/metadata.tsv"):
            target = tmp_path / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("placeholder\n", encoding="utf-8")

        context = type("Context", (), {"base_dir": tmp_path})()

        with pytest.raises(DatasetIntakeValidationError) as exc_info:
            validate_perturb_seq_inputs(
                {
                    "dataset_manifest": manifest_relpath,
                    "reference_build": "hg38",
                },
                context,
            )

        assert any(issue.field_path == "reference_build" for issue in exc_info.value.result.issues)
