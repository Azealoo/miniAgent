"""Tests for FastQC helper functions."""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastqc import load_fastqc_inputs, parse_fastqc_archive  # noqa: E402


def _write_fastq(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@read\nACGT\n+\nIIII\n", encoding="utf-8")


def test_load_fastqc_inputs_supports_paired_end_and_single_end_layouts(tmp_path):
    paired_sheet = tmp_path / "paired.tsv"
    single_sheet = tmp_path / "single.tsv"
    _write_fastq(tmp_path / "data" / "sample1_R1.fastq")
    _write_fastq(tmp_path / "data" / "sample1_R2.fastq")
    _write_fastq(tmp_path / "data" / "sample2.fastq")

    paired_sheet.write_text(
        "sample_id\tfastq_r1\tfastq_r2\nsample1\tdata/sample1_R1.fastq\tdata/sample1_R2.fastq\n",
        encoding="utf-8",
    )
    single_sheet.write_text(
        "sample_id\tfastq_r1\tfastq_r2\nsample2\tdata/sample2.fastq\t\n",
        encoding="utf-8",
    )

    paired_layout, paired_inputs = load_fastqc_inputs(tmp_path, paired_sheet.relative_to(tmp_path))
    single_layout, single_inputs = load_fastqc_inputs(tmp_path, single_sheet.relative_to(tmp_path))

    assert paired_layout == "paired_end"
    assert [item.read_label for item in paired_inputs] == ["read1", "read2"]
    assert single_layout == "single_end"
    assert [item.read_label for item in single_inputs] == ["single"]


def test_load_fastqc_inputs_rejects_mixed_layouts(tmp_path):
    sheet = tmp_path / "mixed.tsv"
    _write_fastq(tmp_path / "data" / "sample1_R1.fastq")
    _write_fastq(tmp_path / "data" / "sample1_R2.fastq")
    _write_fastq(tmp_path / "data" / "sample2.fastq")
    sheet.write_text(
        "\n".join(
            [
                "sample_id\tfastq_r1\tfastq_r2",
                "sample1\tdata/sample1_R1.fastq\tdata/sample1_R2.fastq",
                "sample2\tdata/sample2.fastq\t",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="consistent layout"):
        load_fastqc_inputs(tmp_path, sheet.relative_to(tmp_path))


def test_load_fastqc_inputs_rejects_duplicate_sample_ids(tmp_path):
    sheet = tmp_path / "duplicate.tsv"
    _write_fastq(tmp_path / "data" / "sample1_lane1_R1.fastq")
    _write_fastq(tmp_path / "data" / "sample1_lane2_R1.fastq")
    sheet.write_text(
        "\n".join(
            [
                "sample_id\tfastq_r1\tfastq_r2",
                "sample1\tdata/sample1_lane1_R1.fastq\t",
                "sample1\tdata/sample1_lane2_R1.fastq\t",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="one row per sample_id"):
        load_fastqc_inputs(tmp_path, sheet.relative_to(tmp_path))


def test_parse_fastqc_archive_extracts_metrics_and_statuses(tmp_path):
    archive_path = tmp_path / "sample1_fastqc.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "sample1_fastqc/summary.txt",
            "\n".join(
                [
                    "PASS\tBasic Statistics\tsample1.fastq",
                    "WARN\tPer base sequence quality\tsample1.fastq",
                    "FAIL\tAdapter Content\tsample1.fastq",
                ]
            )
            + "\n",
        )
        archive.writestr(
            "sample1_fastqc/fastqc_data.txt",
            "\n".join(
                [
                    "##FastQC\t0.12.1",
                    ">>Basic Statistics\tpass",
                    "#Measure\tValue",
                    "Filename\tsample1.fastq",
                    "Total Sequences\t1200",
                    "Sequences flagged as poor quality\t12",
                    "Sequence length\t75",
                    "%GC\t51",
                    ">>END_MODULE",
                    ">>Per base sequence quality\twarn",
                    "#Base\tMean\tMedian\tLower Quartile\tUpper Quartile\t10th Percentile\t90th Percentile",
                    "1\t29.5\t29.5\t29.5\t29.5\t29.5\t29.5",
                    "2\t27.0\t27.0\t27.0\t27.0\t27.0\t27.0",
                    ">>END_MODULE",
                    ">>Adapter Content\tfail",
                    "#Position\tIllumina Universal Adapter",
                    "1\t0.0",
                    ">>END_MODULE",
                ]
            )
            + "\n",
        )

    parsed = parse_fastqc_archive(
        archive_path,
        sample_id="sample1",
        read_label="single",
        input_relpath="data/sample1.fastq",
    )

    assert parsed.total_sequences == 1200
    assert parsed.sequences_flagged_as_poor_quality == 12
    assert parsed.percent_gc == 51.0
    assert parsed.min_per_base_quality == 27.0
    assert parsed.overall_status == "fail"
    assert {item.module_id for item in parsed.module_results} == {
        "basic-statistics",
        "per-base-sequence-quality",
        "adapter-content",
    }
