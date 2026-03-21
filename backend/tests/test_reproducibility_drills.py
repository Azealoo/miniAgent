"""Tests for file-first workflow reproducibility drills."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import (  # noqa: E402
    SCHEMA_PACK_VERSION,
    ReproducibilityDrillReport,
    load_artifact_document,
    lookup_artifact_registry,
    resolve_artifact_path,
)
from reproducibility_drills import (  # noqa: E402
    DrillComparisonDefinition,
    WorkflowReproducibilityDrillDefinition,
    run_workflow_reproducibility_drill,
    validate_compliance_artifact_presence,
    validate_provenance_completeness,
    validate_report_bundle_completeness,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _stage_authored_rnaseq_qc_de_workflow(base_dir: Path) -> None:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    runners_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for tests."""\n', encoding="utf-8")
    shutil.copy2(REPO_ROOT / "workflows" / "rnaseq_qc_de.yaml", workflows_dir / "rnaseq_qc_de.yaml")
    shutil.copy2(REPO_ROOT / "workflows" / "runners" / "rnaseq_qc_de.py", runners_dir / "rnaseq_qc_de.py")


def _write_fake_fastqc_executable(base_dir: Path) -> str:
    script_path = base_dir / "tools" / "fake_fastqc.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        """#!/usr/bin/env python3
import sys
import zipfile
from pathlib import Path

FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def prefix(name: str) -> str:
    lower = name.lower()
    for suffix in FASTQ_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def summary_text(filename: str) -> str:
    return "\\n".join(
        [
            f"PASS\\tBasic Statistics\\t{filename}",
            f"PASS\\tPer base sequence quality\\t{filename}",
            f"PASS\\tAdapter Content\\t{filename}",
        ]
    ) + "\\n"


def fastqc_data_text(filename: str) -> str:
    return (
        "##FastQC\\t0.12.1\\n"
        ">>Basic Statistics\\tpass\\n"
        "#Measure\\tValue\\n"
        f"Filename\\t{filename}\\n"
        "Total Sequences\\t1200000\\n"
        "Sequences flagged as poor quality\\t0\\n"
        "Sequence length\\t75\\n"
        "%GC\\t48\\n"
        ">>END_MODULE\\n"
        ">>Per base sequence quality\\tpass\\n"
        "#Base\\tMean\\tMedian\\tLower Quartile\\tUpper Quartile\\t10th Percentile\\t90th Percentile\\n"
        "1\\t31.5\\t31.5\\t31.5\\t31.5\\t31.5\\t31.5\\n"
        "2\\t32.0\\t32.0\\t32.0\\t32.0\\t32.0\\t32.0\\n"
        ">>END_MODULE\\n"
        ">>Adapter Content\\tpass\\n"
        "#Position\\tIllumina Universal Adapter\\n"
        "1\\t0.0\\n"
        ">>END_MODULE\\n"
    )


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("FastQC v0.12.1")
        return 0

    outdir = Path(argv[argv.index("--outdir") + 1])
    outdir.mkdir(parents=True, exist_ok=True)
    input_paths = [
        arg
        for arg in argv[1:]
        if not arg.startswith("-") and arg != str(outdir)
    ]
    for raw in input_paths:
        name = Path(raw).name
        output_prefix = prefix(name)
        html_path = outdir / f"{output_prefix}_fastqc.html"
        zip_path = outdir / f"{output_prefix}_fastqc.zip"
        html_path.write_text(f"<html><body>{name}</body></html>\\n", encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w") as zipped:
            zipped.writestr(f"{output_prefix}_fastqc/summary.txt", summary_text(name))
            zipped.writestr(f"{output_prefix}_fastqc/fastqc_data.txt", fastqc_data_text(name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path.relative_to(base_dir).as_posix()


def _write_fake_multiqc_executable(base_dir: Path) -> str:
    script_path = base_dir / "tools" / "fake_multiqc.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def sample_name(path: str) -> str:
    stem = Path(path).name.replace("_fastqc.zip", "").replace("_fastqc.html", "")
    return stem.split("__", 1)[0]


def discover_samples(path: str) -> set[str]:
    candidate = Path(path)
    if candidate.is_dir():
        return {
            sample_name(item.name)
            for item in candidate.glob("*_fastqc.zip")
        }
    return {sample_name(path)}


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("multiqc v1.15")
        return 0

    outdir = Path(argv[argv.index("--outdir") + 1])
    filename = argv[argv.index("--filename") + 1]
    outdir.mkdir(parents=True, exist_ok=True)
    data_dir = outdir / "multiqc_data"
    data_dir.mkdir(parents=True, exist_ok=True)

    inputs = [
        arg
        for arg in argv[1:]
        if not arg.startswith("-") and arg not in {str(outdir), filename}
    ]
    sample_names = sorted({name for item in inputs for name in discover_samples(item)})
    payload = {
        "sample_names": sample_names,
        "module_names": ["FastQC"],
        "report_modules": [{"name": "FastQC"}],
        "report_saved_raw_data": {"fastqc": {name: {"pass": True} for name in sample_names}},
    }

    (outdir / filename).write_text("<html><body>multiqc</body></html>\\n", encoding="utf-8")
    (data_dir / "bioapex_multiqc_summary.json").write_text(
        json.dumps(payload, indent=2) + "\\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path.relative_to(base_dir).as_posix()


def _write_bulk_rnaseq_manifest(
    base_dir: Path,
    *,
    fastqc_executable: str,
    multiqc_executable: str,
) -> str:
    manifest_relpath = "manifests/rnaseq_dataset_manifest.yaml"
    sample_sheet_relpath = "data/rnaseq/sample_sheet.tsv"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    samples = [
        ("control_rep1", "control", "batch_a"),
        ("control_rep2", "control", "batch_a"),
        ("control_rep3", "control", "batch_b"),
        ("treated_rep1", "treated", "batch_a"),
        ("treated_rep2", "treated", "batch_b"),
        ("treated_rep3", "treated", "batch_b"),
    ]

    source_files: list[str] = []
    rows = ["sample_id\tcondition\tbatch\tfastq_r1\tfastq_r2"]
    for sample_id, condition, batch in samples:
        read1_relpath = f"data/rnaseq/{sample_id}__pass_R1.fastq"
        read2_relpath = f"data/rnaseq/{sample_id}__pass_R2.fastq"
        (base_dir / read1_relpath).parent.mkdir(parents=True, exist_ok=True)
        (base_dir / read1_relpath).write_text("@read1\nACGT\n+\nIIII\n", encoding="utf-8")
        (base_dir / read2_relpath).write_text("@read2\nTGCA\n+\nIIII\n", encoding="utf-8")
        source_files.extend([read1_relpath, read2_relpath])
        rows.append(f"{sample_id}\t{condition}\t{batch}\t{read1_relpath}\t{read2_relpath}")

    payload = {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "dataset_manifest",
        "id": "ds-rnaseq-reproducibility-v1",
        "run_id": "run-20260320T210000Z-abcd1234",
        "created_at": "2026-03-20T21:00:00Z",
        "source_workflow": "dataset-intake",
        "related_artifacts": [],
        "assay_type": "bulk_rna_seq",
        "organism": "homo_sapiens",
        "reference_build": "grch38",
        "sample_sheet_path": sample_sheet_relpath,
        "privacy_classification": "public",
        "design": {
            "study_name": "interferon-rnaseq-reference-replay",
            "experiment_type": "bulk_rna_seq",
            "condition_summary": "Bulk RNA-seq reference replay drill.",
            "analysis_kind": "comparative",
            "condition_fields": ["condition"],
            "batch_fields": ["batch"],
            "replicate_structure": "3 control and 3 treated libraries",
            "timepoints": ["end_point"],
            "factors": ["condition", "batch"],
        },
        "source_files": source_files,
        "assay_extensions": {
            "fastqc": {"executable": fastqc_executable},
            "multiqc": {"executable": multiqc_executable},
        },
    }

    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    sample_sheet_path = base_dir / sample_sheet_relpath
    sample_sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sample_sheet_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return manifest_relpath


def _stage_reproducibility_workspace(base_dir: Path) -> str:
    _stage_authored_rnaseq_qc_de_workflow(base_dir)
    fastqc_executable = _write_fake_fastqc_executable(base_dir)
    multiqc_executable = _write_fake_multiqc_executable(base_dir)
    return _write_bulk_rnaseq_manifest(
        base_dir,
        fastqc_executable=fastqc_executable,
        multiqc_executable=multiqc_executable,
    )


def _build_reference_drill(manifest_relpath: str) -> WorkflowReproducibilityDrillDefinition:
    return WorkflowReproducibilityDrillDefinition(
        drill_id="rnaseq-reference-replay",
        label="RNA-seq Reference Replay",
        execution_tier="ci",
        workflow_spec_path="workflows/rnaseq_qc_de.yaml",
        inputs={
            "dataset_manifest": manifest_relpath,
            "condition_field": "condition",
            "baseline_condition": "control",
            "comparison_condition": "treated",
        },
        environment_references=(
            f"platform:{platform.system().lower()}",
            f"python_version:{platform.python_version()}",
        ),
        comparisons=(
            DrillComparisonDefinition(
                comparison_id="quantification-gene-count",
                description="Quantification gene count remains deterministic across replay.",
                target_type="summary_metric",
                stage="quantification",
                metric_name="gene_count",
                expected_value=10,
            ),
            DrillComparisonDefinition(
                comparison_id="aggregated-total-reads",
                description="Aggregated total reads remain within the accepted replay tolerance.",
                target_type="summary_metric",
                stage="aggregated_qc",
                metric_name="total_reads_millions",
                expected_value=14.4,
                comparison_mode="absolute_tolerance",
                absolute_tolerance=0.001,
            ),
        ),
        notes=("Reference replay drill for the authored RNA-seq workflow.",),
    )


def _run_reference_drill(tmp_path: Path):
    manifest_relpath = _stage_reproducibility_workspace(tmp_path)
    return run_workflow_reproducibility_drill(
        tmp_path,
        _build_reference_drill(manifest_relpath),
        created_at=datetime(2026, 3, 20, 22, 30, 0, tzinfo=timezone.utc),
    )


@pytest.mark.reproducibility_ci
def test_run_workflow_reproducibility_drill_writes_report_and_updates_run_record(tmp_path):
    result = _run_reference_drill(tmp_path)
    report_relpath = (
        "outputs/generated/reproducibility-drills/rnaseq-reference-replay.json"
    )

    assert result.workflow_result.run.lifecycle_status == "completed"
    document = load_artifact_document(result.report_path)
    assert isinstance(document, ReproducibilityDrillReport)
    assert document.status == "passed"
    assert document.execution_tier == "ci"
    assert all(check.passed for check in document.checks)
    assert any(
        comparison.comparison_mode == "exact" and comparison.passed
        for comparison in document.comparisons
    )
    assert any(
        comparison.comparison_mode == "absolute_tolerance" and comparison.passed
        for comparison in document.comparisons
    )

    run_payload = json.loads(result.workflow_result.artifact_path.read_text(encoding="utf-8"))
    assert any(
        item["artifact_type"] == "reproducibility_drill_report"
        and item["path"].endswith(report_relpath)
        for item in run_payload["related_artifacts"]
    )
    registry_lookup = lookup_artifact_registry(tmp_path, artifact_type="reproducibility_drill_report")
    assert registry_lookup.matched_count == 1
    assert registry_lookup.records[0].status == "valid"
    assert registry_lookup.records[0].path.endswith(report_relpath)

    content_hashes = json.loads((result.workflow_result.run_dir / "content_hashes.json").read_text(encoding="utf-8"))
    assert report_relpath in content_hashes["hashes"]


def test_validate_provenance_completeness_reports_missing_lineage_fields(tmp_path):
    result = _run_reference_drill(tmp_path)
    prov_path = result.workflow_result.run_dir / "prov.json"
    payload = json.loads(prov_path.read_text(encoding="utf-8"))
    del payload["workflow"]["workflow_id"]
    payload["tool_versions"] = []
    prov_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    check, _ = validate_provenance_completeness(tmp_path, result.workflow_result.run)

    assert check.passed is False
    assert any(issue.field_path == "workflow.workflow_id" for issue in check.issues)
    assert any(issue.field_path == "tool_versions" for issue in check.issues)


def test_missing_compliance_artifact_fails_report_bundle_and_compliance_checks(tmp_path):
    result = _run_reference_drill(tmp_path)
    compliance_ref = next(
        ref for ref in result.report.checked_artifacts if ref.artifact_type == "compliance_report"
    )
    resolve_artifact_path(tmp_path, compliance_ref.path).unlink()

    report_bundle_check, _ = validate_report_bundle_completeness(tmp_path, result.workflow_result.run)
    compliance_check, compliance_refs = validate_compliance_artifact_presence(
        tmp_path,
        result.workflow_result.run,
    )

    assert report_bundle_check.passed is False
    assert any(issue.code == "missing_report_bundle_artifact" for issue in report_bundle_check.issues)
    assert compliance_check.passed is False
    assert compliance_refs
    assert any(issue.code == "missing_compliance_artifact" for issue in compliance_check.issues)
