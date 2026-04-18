"""Tests for MultiQC helper functions."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from multiqc import inspect_multiqc_report, run_multiqc  # noqa: E402


def test_inspect_multiqc_report_extracts_summary_metadata(tmp_path):
    data_dir = tmp_path / "artifacts" / "demo" / "run-1" / "outputs" / "generated" / "aggregated-qc" / "multiqc" / "multiqc_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    summary_path = data_dir / "bioapex_multiqc_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "sample_names": ["sample1", "sample2"],
                "report_modules": [{"name": "FastQC"}],
            }
        ),
        encoding="utf-8",
    )

    summary = inspect_multiqc_report(
        tmp_path,
        "artifacts/demo/run-1/outputs/generated/aggregated-qc/multiqc",
    )

    assert summary.sample_names == ("sample1", "sample2")
    assert summary.module_names == ("FastQC",)
    assert summary.summary_data_path.endswith("bioapex_multiqc_summary.json")


def test_run_multiqc_returns_report_and_data_paths(tmp_path):
    tool_path = tmp_path / "tools" / "fake_multiqc.py"
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(
        """#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("multiqc, version 1.21")
        return 0
    outdir = Path(argv[argv.index("--outdir") + 1])
    filename = argv[argv.index("--filename") + 1]
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / filename).write_text("<html>report</html>\\n", encoding="utf-8")
    data_dir = outdir / "multiqc_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "bioapex_multiqc_summary.json").write_text(
        json.dumps({"sample_names": ["sample1"], "report_modules": [{"name": "FastQC"}]}),
        encoding="utf-8",
    )
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
""",
        encoding="utf-8",
    )
    tool_path.chmod(0o755)
    input_dir = tmp_path / "artifacts" / "demo" / "fastqc"
    input_dir.mkdir(parents=True, exist_ok=True)

    result = run_multiqc(
        executable=tool_path.relative_to(tmp_path).as_posix(),
        input_paths=[input_dir.relative_to(tmp_path).as_posix()],
        output_dir="artifacts/demo/multiqc",
        base_dir=tmp_path,
    )

    assert result.report_html_path == "artifacts/demo/multiqc/multiqc_report.html"
    assert result.data_directory_path == "artifacts/demo/multiqc/multiqc_data"
