"""Tests for canonical artifact naming helpers."""

import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts.naming import (
    CONTENT_HASH_MANIFEST_FILENAME,
    RUN_RECORD_FILENAME,
    USER_INPUTS_DIR,
    build_artifact_header,
    build_content_hash_manifest,
    build_generated_output_relpath,
    build_run_directory,
    build_user_supplied_relpath,
    generate_run_id,
    prepare_run_directory,
    resolve_artifact_path,
    stable_artifact_name,
    validate_artifact_root,
)


class TestArtifactNaming:
    def test_generate_run_id_uses_canonical_format(self):
        run_id = generate_run_id(
            now=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            unique_suffix="deadbeef",
        )
        assert run_id == "run-20260318T190203Z-deadbeef"

    def test_build_run_directory_matches_canonical_layout(self):
        run_dir = build_run_directory(
            "RNA Seq QC",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id="run-20260318T190203Z-deadbeef",
        )
        assert run_dir == PurePosixPath(
            "artifacts/rna-seq-qc/2026-03-18/run-20260318T190203Z-deadbeef"
        )

    def test_prepare_run_directory_creates_expected_structure(self, tmp_path):
        layout = prepare_run_directory(
            tmp_path,
            "Evidence Review",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id="run-20260318T190203Z-deadbeef",
        )

        assert layout.run_dir.is_dir()
        assert (layout.run_dir / USER_INPUTS_DIR).is_dir()
        assert (layout.run_dir / "outputs" / "generated").is_dir()
        assert layout.run_record_relpath.name == RUN_RECORD_FILENAME
        assert layout.content_hash_manifest_relpath.name == CONTENT_HASH_MANIFEST_FILENAME
        assert layout.run_record_path.is_file()
        assert layout.content_hash_manifest_path.is_file()
        run_record = layout.run_record_path.read_text(encoding="utf-8")
        manifest = layout.content_hash_manifest_path.read_text(encoding="utf-8")
        assert '"artifact_type": "workflow_run"' in run_record
        assert '"run_dir": "artifacts/evidence-review/2026-03-18/run-20260318T190203Z-deadbeef"' in run_record
        assert '"run.json"' in manifest

    def test_prepare_run_directory_blocks_run_collisions(self, tmp_path):
        prepare_run_directory(
            tmp_path,
            "Evidence Review",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id="run-20260318T190203Z-deadbeef",
        )

        with pytest.raises(FileExistsError):
            prepare_run_directory(
                tmp_path,
                "Evidence Review",
                created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
                run_id="run-20260318T190203Z-deadbeef",
            )

    def test_stable_artifact_names_match_reserved_filenames(self):
        assert stable_artifact_name("workflow_run") == "run.json"
        assert stable_artifact_name("dataset_manifest") == "dataset_manifest.yaml"
        assert stable_artifact_name("fastqc_run") == "fastqc_run.json"
        assert stable_artifact_name("fastqc_metrics") == "fastqc_metrics.json"
        assert stable_artifact_name("multiqc_run") == "multiqc_run.json"
        assert stable_artifact_name("multiqc_metrics") == "multiqc_metrics.json"
        assert stable_artifact_name("count_matrix") == "count_matrix.json"
        assert stable_artifact_name("normalized_count_matrix") == "normalized_count_matrix.json"
        assert stable_artifact_name("differential_expression_results") == "differential_expression_results.json"
        assert stable_artifact_name("differential_expression_run") == "differential_expression_run.json"
        assert stable_artifact_name("checklist_results") == "checklist_results.json"
        assert stable_artifact_name("provenance") == "prov.json"
        assert stable_artifact_name("biocompute") == "biocompute.json"
        assert stable_artifact_name("ro_crate") == "ro-crate"

    def test_user_and_generated_paths_are_separated(self):
        assert build_user_supplied_relpath("Patient Sheet.csv", slot="sample_sheet") == PurePosixPath(
            "inputs/user/sample-sheet__patient_sheet.csv"
        )
        assert build_generated_output_relpath("volcano plot.png", step="de_analysis") == PurePosixPath(
            "outputs/generated/de-analysis/volcano_plot.png"
        )

    def test_build_artifact_header_requires_source_context(self):
        with pytest.raises(ValueError):
            build_artifact_header(
                schema_version="1.0.0",
                artifact_type="workflow_run",
                run_id="run-20260318T190203Z-deadbeef",
            )

    def test_build_content_hash_manifest_uses_sha256(self):
        manifest = build_content_hash_manifest(
            run_id="run-20260318T190203Z-deadbeef",
            schema_version="1.0.0",
            source_workflow="evidence-review",
            entries={"outputs/generated/report.txt": "hello world"},
        )

        assert manifest["artifact_type"] == "content_hash_manifest"
        assert manifest["hashes"]["outputs/generated/report.txt"]["algorithm"] == "sha256"
        assert (
            manifest["hashes"]["outputs/generated/report.txt"]["digest"]
            == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        )

    def test_validate_artifact_root_rejects_absolute_paths(self):
        with pytest.raises(ValueError):
            validate_artifact_root("/tmp/artifacts")

    def test_build_run_directory_rejects_mismatched_created_at_and_run_id(self):
        with pytest.raises(ValueError):
            build_run_directory(
                "Evidence Review",
                created_at=datetime(2026, 3, 19, 19, 2, 3, tzinfo=timezone.utc),
                run_id="run-20260318T190203Z-deadbeef",
            )

    def test_resolve_artifact_path_rejects_existing_target_when_requested(self, tmp_path):
        existing = tmp_path / "artifacts" / "demo" / "2026-03-18" / "run-20260318T190203Z-deadbeef"
        existing.mkdir(parents=True)

        with pytest.raises(FileExistsError):
            resolve_artifact_path(
                tmp_path,
                "artifacts/demo/2026-03-18/run-20260318T190203Z-deadbeef",
                must_not_exist=True,
            )

    def test_run_layout_path_helpers_block_overwrites(self, tmp_path):
        layout = prepare_run_directory(
            tmp_path,
            "Evidence Review",
            created_at=datetime(2026, 3, 18, 19, 2, 3, tzinfo=timezone.utc),
            run_id="run-20260318T190203Z-deadbeef",
        )
        first_output = layout.generated_output_path("volcano plot.png", step="de_analysis")
        first_output.write_text("plot", encoding="utf-8")

        with pytest.raises(FileExistsError):
            layout.generated_output_path("volcano plot.png", step="de_analysis")

        user_input = layout.user_input_path("Patient Sheet.csv", slot="sample_sheet")
        user_input.write_text("sample", encoding="utf-8")

        with pytest.raises(FileExistsError):
            layout.user_input_path("Patient Sheet.csv", slot="sample_sheet")

        stable = layout.stable_artifact_path("dataset_manifest")
        stable.write_text("manifest", encoding="utf-8")

        with pytest.raises(FileExistsError):
            layout.stable_artifact_path("dataset_manifest")
