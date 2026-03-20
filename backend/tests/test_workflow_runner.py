"""Tests for the internal DAG workflow runner MVP."""

import importlib.util
import json
import shutil
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import ArtifactReference, load_artifact_document, resolve_artifact_path  # noqa: E402
from artifacts.public_urls import public_raw_file_url  # noqa: E402
from artifacts.registry import rebuild_artifact_registry  # noqa: E402
from artifacts.schema_validation import validate_biocompute_payload_against_reference_schemas  # noqa: E402
from artifacts.schemas import SCHEMA_PACK_VERSION  # noqa: E402
import workflow_runner as workflow_runner_module  # noqa: E402
from workflow_runner import InternalDAGRunner  # noqa: E402
from workflow_specs import WORKFLOW_SPEC_VERSION, validate_workflow_spec_payload  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_runner_module(base_dir: Path, module_name: str, source: str) -> str:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    runners_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for tests."""\n', encoding="utf-8")
    (runners_dir / f"{module_name}.py").write_text(source, encoding="utf-8")
    for loaded in (f"workflows.runners.{module_name}", "workflows.runners", "workflows"):
        sys.modules.pop(loaded, None)
    return f"workflows.runners.{module_name}"


def _runtime_contract(provided_inputs: list[str]) -> dict:
    return {
        "provided_inputs": provided_inputs,
        "allowed_parameter_overrides": [name for name in provided_inputs if name != "sample_id"],
        "generated_state": [
            "run_id",
            "created_at",
            "resolved_input_paths",
            "step_statuses",
            "artifact_paths",
        ],
        "state_artifact": "workflow_run",
        "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
    }


def _qa_report_output(source_step_id: str, source_output_name: str) -> dict:
    return {
        "name": "qa_report",
        "kind": "artifact",
        "artifact_type": "qa_report",
        "schema_ref": "artifact_schema:qa_report@1.0.0",
        "description": "Structured QA report for the workflow run.",
        "source": {
            "step_id": source_step_id,
            "output_name": source_output_name,
        },
    }


def _stage_authored_rna_seq_workflow(base_dir: Path) -> str:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    report_templates_dir = workflows_dir / "report_templates"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    runners_dir.mkdir(parents=True, exist_ok=True)
    report_templates_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for tests."""\n', encoding="utf-8")
    shutil.copy2(REPO_ROOT / "workflows" / "rna-seq-qc.yaml", workflows_dir / "rna-seq-qc.yaml")
    shutil.copy2(REPO_ROOT / "workflows" / "runners" / "rna_seq_qc.py", runners_dir / "rna_seq_qc.py")
    shutil.copy2(
        REPO_ROOT / "workflows" / "report_templates" / "rna_seq_qc_summary.md.j2",
        report_templates_dir / "rna_seq_qc_summary.md.j2",
    )

    manifest_relpath = "manifests/dataset_manifest.yaml"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml", manifest_path)
    for relpath in (
        "data/norman/sample_sheet.tsv",
        "data/norman/counts.h5ad",
        "data/norman/metadata.tsv",
    ):
        target = base_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("placeholder\n", encoding="utf-8")
    return manifest_relpath


def _stage_authored_rnaseq_qc_de_workflow(base_dir: Path) -> Path:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    runners_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for tests."""\n', encoding="utf-8")
    shutil.copy2(REPO_ROOT / "workflows" / "rnaseq_qc_de.yaml", workflows_dir / "rnaseq_qc_de.yaml")
    shutil.copy2(REPO_ROOT / "workflows" / "runners" / "rnaseq_qc_de.py", runners_dir / "rnaseq_qc_de.py")
    return workflows_dir / "rnaseq_qc_de.yaml"


def _write_fake_fastqc_executable(base_dir: Path) -> str:
    tool_relpath = "tools/fake_fastqc.py"
    tool_path = base_dir / tool_relpath
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(
        """#!/usr/bin/env python3
import json
import sys
import zipfile
from pathlib import Path


FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def _prefix(name: str) -> str:
    lower = name.lower()
    for suffix in FASTQ_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def _mode_for_input(path: str) -> str:
    lower = Path(path).name.lower()
    if "execfail" in lower:
        return "execfail"
    if "qualityfail" in lower:
        return "qualityfail"
    if "adapterfail" in lower:
        return "adapterfail"
    if "qualitywarn" in lower:
        return "qualitywarn"
    return "pass"


def _statuses(mode: str):
    if mode == "qualityfail":
        return {"per_base": "fail", "adapter": "pass", "means": (23.0, 24.0)}
    if mode == "qualitywarn":
        return {"per_base": "warn", "adapter": "pass", "means": (26.0, 27.0)}
    if mode == "adapterfail":
        return {"per_base": "pass", "adapter": "fail", "means": (31.0, 31.5)}
    return {"per_base": "pass", "adapter": "pass", "means": (31.5, 32.0)}


def _summary_text(filename: str, per_base: str, adapter: str) -> str:
    return "\\n".join(
        [
            f"PASS\\tBasic Statistics\\t{filename}",
            f"{per_base.upper()}\\tPer base sequence quality\\t{filename}",
            f"{adapter.upper()}\\tAdapter Content\\t{filename}",
        ]
    ) + "\\n"


def _fastqc_data_text(filename: str, per_base: str, adapter: str, mean1: float, mean2: float) -> str:
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
        f">>Per base sequence quality\\t{per_base}\\n"
        "#Base\\tMean\\tMedian\\tLower Quartile\\tUpper Quartile\\t10th Percentile\\t90th Percentile\\n"
        f"1\\t{mean1}\\t{mean1}\\t{mean1}\\t{mean1}\\t{mean1}\\t{mean1}\\n"
        f"2\\t{mean2}\\t{mean2}\\t{mean2}\\t{mean2}\\t{mean2}\\t{mean2}\\n"
        ">>END_MODULE\\n"
        f">>Adapter Content\\t{adapter}\\n"
        "#Position\\tIllumina Universal Adapter\\n"
        "1\\t0.0\\n"
        ">>END_MODULE\\n"
    )


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("FastQC v0.12.1")
        return 0

    try:
        outdir = Path(argv[argv.index("--outdir") + 1])
    except (ValueError, IndexError):
        print("missing --outdir", file=sys.stderr)
        return 2

    inputs = []
    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if token == "--outdir":
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if index == 0:
            continue
        inputs.append(token)

    outdir.mkdir(parents=True, exist_ok=True)
    log_path = Path("fastqc_invocations.json")
    entries = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    entries.append(sorted(inputs))
    log_path.write_text(json.dumps(entries), encoding="utf-8")
    for input_path in inputs:
        mode = _mode_for_input(input_path)
        if mode == "execfail":
            print(f"FastQC simulated execution failure for {input_path}", file=sys.stderr)
            return 2
        filename = Path(input_path).name
        prefix = _prefix(filename)
        statuses = _statuses(mode)
        html_path = outdir / f"{prefix}_fastqc.html"
        zip_path = outdir / f"{prefix}_fastqc.zip"
        html_path.write_text(f"<html><body>{filename}</body></html>\\n", encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr(f"{prefix}_fastqc/summary.txt", _summary_text(filename, statuses["per_base"], statuses["adapter"]))
            archive.writestr(
                f"{prefix}_fastqc/fastqc_data.txt",
                _fastqc_data_text(
                    filename,
                    statuses["per_base"],
                    statuses["adapter"],
                    statuses["means"][0],
                    statuses["means"][1],
                ),
            )

    print(f"processed={len(inputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
""",
        encoding="utf-8",
    )
    tool_path.chmod(0o755)
    return tool_relpath


def _write_fake_multiqc_executable(base_dir: Path) -> str:
    tool_relpath = "tools/fake_multiqc.py"
    tool_path = base_dir / tool_relpath
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(
        """#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path


SAMPLE_RE = re.compile(r"(?P<sample>.+?)(?:__[a-z0-9_-]+)?(?:_R[12])?_fastqc\\.html$", re.IGNORECASE)


def _discover_samples(input_dirs):
    sample_names = []
    seen = set()
    should_fail = False
    for directory in input_dirs:
        for path in sorted(Path(directory).glob("*_fastqc.html")):
            lowered = path.name.lower()
            if "multiqcfail" in lowered:
                should_fail = True
            match = SAMPLE_RE.match(path.name)
            sample_name = match.group("sample") if match else path.stem.replace("_fastqc", "")
            if sample_name not in seen:
                seen.add(sample_name)
                sample_names.append(sample_name)
    return sample_names, should_fail


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("multiqc, version 1.21")
        return 0

    try:
        outdir = Path(argv[argv.index("--outdir") + 1])
        filename = argv[argv.index("--filename") + 1]
    except (ValueError, IndexError):
        print("missing MultiQC output arguments", file=sys.stderr)
        return 2

    inputs = []
    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if token in {"--outdir", "--filename"}:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if index == 0:
            continue
        inputs.append(token)

    log_path = Path("multiqc_invocations.json")
    entries = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    entries.append(sorted(inputs))
    log_path.write_text(json.dumps(entries), encoding="utf-8")

    sample_names, should_fail = _discover_samples(inputs)
    if should_fail:
        print("MultiQC simulated execution failure from FastQC report names", file=sys.stderr)
        return 2

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / filename).write_text("<html><body>multiqc</body></html>\\n", encoding="utf-8")
    data_dir = outdir / "multiqc_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "bioapex_multiqc_summary.json").write_text(
        json.dumps(
            {
                "sample_names": sample_names,
                "report_modules": [{"name": "FastQC"}],
                "report_general_stats_data": [{"sample_name": sample_name} for sample_name in sample_names],
            }
        ),
        encoding="utf-8",
    )
    print(f"aggregated={len(sample_names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
""",
        encoding="utf-8",
    )
    tool_path.chmod(0o755)
    return tool_relpath


def _write_bulk_rnaseq_manifest(
    base_dir: Path,
    *,
    fastqc_executable: str | None = None,
    multiqc_executable: str | None = None,
    sequencing_layout: str = "paired_end",
    sample_modes: dict[str, str] | None = None,
    omit_batch_column: bool = False,
    design_batch_fields: list[str] | None = None,
) -> str:
    manifest_relpath = "manifests/rnaseq_dataset_manifest.yaml"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    sample_sheet_relpath = "data/rnaseq/sample_sheet.tsv"
    samples = [
        ("control_rep1", "control", "batch_a"),
        ("control_rep2", "control", "batch_a"),
        ("control_rep3", "control", "batch_b"),
        ("treated_rep1", "treated", "batch_a"),
        ("treated_rep2", "treated", "batch_b"),
        ("treated_rep3", "treated", "batch_b"),
    ]
    sample_modes = sample_modes or {}
    resolved_design_batch_fields = ["batch"] if design_batch_fields is None else list(design_batch_fields)
    source_files: list[str] = []
    headers = ["sample_id", "condition"]
    if not omit_batch_column:
        headers.append("batch")
    headers.extend(["fastq_r1", "fastq_r2"])
    sample_sheet_lines = ["\t".join(headers)]
    for sample_id, condition, batch in samples:
        mode = sample_modes.get(sample_id, "pass")
        read1_relpath = f"data/rnaseq/{sample_id}__{mode}_R1.fastq"
        read1_path = base_dir / read1_relpath
        read1_path.parent.mkdir(parents=True, exist_ok=True)
        read1_path.write_text("@read1\nACGT\n+\nIIII\n", encoding="utf-8")
        source_files.append(read1_relpath)

        if sequencing_layout == "paired_end":
            read2_relpath = f"data/rnaseq/{sample_id}__{mode}_R2.fastq"
            read2_path = base_dir / read2_relpath
            read2_path.parent.mkdir(parents=True, exist_ok=True)
            read2_path.write_text("@read2\nTGCA\n+\nIIII\n", encoding="utf-8")
            source_files.append(read2_relpath)
        else:
            read2_relpath = ""

        values = [sample_id, condition]
        if not omit_batch_column:
            values.append(batch)
        values.extend([read1_relpath, read2_relpath])
        sample_sheet_lines.append("\t".join(values))

    assay_extensions: dict[str, object] = {}
    if fastqc_executable is not None:
        assay_extensions["fastqc"] = {"executable": fastqc_executable}
    if multiqc_executable is not None:
        assay_extensions["multiqc"] = {"executable": multiqc_executable}
    payload = {
        "schema_version": SCHEMA_PACK_VERSION,
        "artifact_type": "dataset_manifest",
        "id": "ds-rnaseq-skeleton-v1",
        "run_id": "run-20260319T200000Z-14aa00ff",
        "created_at": "2026-03-19T20:00:00Z",
        "source_workflow": "dataset-intake",
        "related_artifacts": [],
        "assay_type": "bulk_rna_seq",
        "organism": "homo_sapiens",
        "reference_build": "grch38",
        "sample_sheet_path": sample_sheet_relpath,
        "privacy_classification": "public",
        "design": {
            "study_name": "interferon-rnaseq-pilot",
            "experiment_type": "bulk_rna_seq",
            "condition_summary": "Bulk RNA-seq pilot comparing treated and control libraries.",
            "analysis_kind": "comparative",
            "condition_fields": ["condition"],
            "batch_fields": resolved_design_batch_fields,
            "replicate_structure": "3 control and 3 treated libraries",
            "timepoints": ["end_point"],
            "factors": ["condition", *resolved_design_batch_fields],
        },
        "source_files": source_files,
        "assay_extensions": assay_extensions,
    }
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    sample_sheet_path = base_dir / sample_sheet_relpath
    sample_sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sample_sheet_path.write_text("\n".join(sample_sheet_lines) + "\n", encoding="utf-8")
    return manifest_relpath


class TestInternalDAGRunner:
    def test_runner_executes_steps_in_dependency_order_and_persists_outputs(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "order_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "execution_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def prepare(inputs, context):
    _log(context, "prepare")
    return {"prepared_value": {"seed": inputs["seed"], "doubled": inputs["seed"] * 2}}


def summarize(inputs, context):
    _log(context, "summarize")
    doubled = inputs["prepared_value"]["doubled"]
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [f"doubled={doubled}"],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-order-demo",
                "version": "1.0.0",
                "name": "Runner Order Demo",
                "purpose": "Verify deterministic DAG execution and artifact persistence.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("summarize", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "prepare",
                        "label": "Prepare Values",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "prepare",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Prepared numeric payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "summarize",
                        "label": "Summarize Results",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "summarize",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "prepare",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["prepare"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(spec, {"seed": 7})

        assert result.run.lifecycle_status == "completed"
        assert [record.id for record in result.run.steps] == ["prepare", "summarize"]
        assert [record.status for record in result.run.steps] == ["completed", "completed"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == [
            "prepare",
            "summarize",
        ]

        persisted = load_artifact_document(result.artifact_path)
        assert persisted.lifecycle_status == "completed"
        assert persisted.outputs[0].artifact_type == "qa_report"
        assert resolve_artifact_path(tmp_path, persisted.outputs[0].path).exists()
        assert (result.run_dir / "outputs" / "generated" / "prepare" / "prepared_value.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "summarize" / "resolved_outputs.json").exists()
        assert (result.run_dir / "qa_report.json").exists()

    def test_runner_emits_structured_workflow_events_for_successful_run(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "stream_demo",
            """
def prepare(inputs, _context):
    return {"prepared_value": {"seed": inputs["seed"], "doubled": inputs["seed"] * 2}}


def summarize(inputs, _context):
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [f"doubled={inputs['prepared_value']['doubled']}"],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-stream-demo",
                "version": "1.0.0",
                "name": "Runner Stream Demo",
                "purpose": "Verify workflow lifecycle event emission for successful runs.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("summarize", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "prepare",
                        "label": "Prepare Values",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "prepare",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Prepared numeric payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "summarize",
                        "label": "Summarize Results",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "summarize",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "prepare",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["prepare"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 11}, event_callback=events.append)

        assert result.run.lifecycle_status == "completed"
        assert [event["type"] for event in events] == [
            "workflow_start",
            "workflow_artifact",
            "workflow_step_start",
            "workflow_artifact",
            "workflow_step_end",
            "workflow_step_start",
            "workflow_artifact",
            "workflow_step_end",
            "workflow_artifact",
            "workflow_done",
        ]
        assert events[0]["contract_version"] == "workflow_event.v1"
        assert events[1]["scope"] == "run_record"
        assert events[3]["artifact"]["artifact_type"] == "workflow_value"
        assert events[6]["artifact"]["artifact_type"] == "qa_report"
        assert events[8]["scope"] == "workflow_output"
        assert events[-1]["lifecycle_status"] == "completed"
        assert events[-1]["completed_steps"] == 2
        assert events[-1]["total_steps"] == 2

    def test_runner_propagates_failures_to_descendants(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "failure_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "execution_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def explode(_inputs, context):
    _log(context, "explode")
    raise RuntimeError("boom")


def never(_inputs, context):
    _log(context, "never")
    return {"qa_report": {"overall_status": "passed", "failed_checks": [], "warnings": [], "missing_artifacts": [], "recommended_remediation": [], "checklist_artifacts": []}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-failure-demo",
                "version": "1.0.0",
                "name": "Runner Failure Demo",
                "purpose": "Verify failure propagation through explicit prerequisites.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("never", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "explode",
                        "label": "Explode",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "explode",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Unreachable prepared payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "never",
                        "label": "Never Execute",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "never",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "explode",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["explode"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(spec, {"seed": 7})
        expected_provenance_exports = [
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/prov.json",
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/ro-crate/ro-crate-metadata.json",
        ]
        provenance_payload = json.loads((result.run_dir / "prov.json").read_text(encoding="utf-8"))

        assert result.run.lifecycle_status == "failed"
        assert [record.status for record in result.run.steps] == ["failed", "blocked"]
        assert result.run.provenance_exports == expected_provenance_exports
        assert result.run.biocompute_exports == []
        assert (result.run_dir / "prov.json").exists()
        assert (result.run_dir / "ro-crate" / "ro-crate-metadata.json").exists()
        assert not (result.run_dir / "biocompute.json").exists()
        assert provenance_payload["workflow"]["lifecycle_status"] == "failed"
        assert provenance_payload["terminal_state"]["is_partial"] is True
        assert any(
            activity["status"] == "failed"
            for activity in provenance_payload["activity"].values()
        )
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == ["explode"]
        assert "boom" in result.run.steps[0].errors[0]
        assert "Blocked by prerequisite explode" in result.run.steps[1].errors[0]

    def test_runner_resumes_from_persisted_state_without_rerunning_completed_steps(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "resume_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "execution_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def prepare(inputs, context):
    _log(context, "prepare")
    return {"prepared_value": {"seed": inputs["seed"], "doubled": inputs["seed"] * 2}}


def summarize(inputs, context):
    _log(context, "summarize")
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [f"doubled={inputs['prepared_value']['doubled']}"],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "runner-resume-demo",
                "version": "1.0.0",
                "name": "Runner Resume Demo",
                "purpose": "Verify pause and resume behavior from persisted state.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("summarize", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "prepare",
                        "label": "Prepare Values",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "prepare",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "prepared_value",
                                "kind": "value",
                                "description": "Prepared numeric payload.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "summarize",
                        "label": "Summarize Results",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "summarize",
                        },
                        "inputs": [
                            {
                                "name": "prepared_value",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "prepare",
                                    "output_name": "prepared_value",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": ["prepare"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        paused = runner.run(spec, {"seed": 5}, step_limit=1)

        assert paused.run.lifecycle_status == "waiting"
        assert [record.status for record in paused.run.steps] == ["completed", "created"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == ["prepare"]

        resumed = runner.run(spec, run_dir=paused.run_dir)

        assert resumed.resumed is True
        assert resumed.run.lifecycle_status == "completed"
        assert [record.status for record in resumed.run.steps] == ["completed", "completed"]
        assert json.loads((tmp_path / "execution_log.json").read_text(encoding="utf-8")) == [
            "prepare",
            "summarize",
        ]

    def test_runner_executes_external_engine_steps_and_persists_value_outputs(self, tmp_path):
        command = " ".join(
            [
                shlex.quote(sys.executable),
                "-c",
                shlex.quote(
                    "import os, sys; print(sys.argv[1]); print(os.environ['BIOAPEX_INPUT_SAMPLE_ID'])"
                ),
                "{sample_id}",
            ]
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "external-engine-demo",
                "version": "1.0.0",
                "name": "External Engine Demo",
                "purpose": "Verify the external command executor path for the workflow runner.",
                "engine": "external_workflow_adapter_v1",
                "required_inputs": [
                    {
                        "name": "sample_id",
                        "kind": "metadata",
                        "data_type": "string",
                        "description": "Sample identifier forwarded to the launch command.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["sample_id"]),
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Captured external execution bundle.",
                        "source": {
                            "step_id": "launch_job",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch_job",
                        "label": "Launch External Job",
                        "executor": {
                            "executor_type": "external_engine",
                            "engine_name": "command",
                            "entrypoint": "workflows/engines/demo/main.sh",
                            "command": command,
                        },
                        "inputs": [
                            {
                                "name": "sample_id",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "sample_id",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Structured external command result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(spec, {"sample_id": "sample-001"})

        assert result.run.lifecycle_status == "completed"
        assert result.run.steps[0].status == "completed"
        assert result.run.outputs[0].artifact_type == "workflow_value"

        output_path = resolve_artifact_path(tmp_path, result.run.outputs[0].path)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["value"]["returncode"] == 0
        assert payload["value"]["argv"][-1] == "sample-001"
        assert payload["value"]["stdout"].splitlines() == ["sample-001", "sample-001"]
        assert "BIOAPEX_INPUT_SAMPLE_ID" in payload["value"]["environment_keys"]

    def test_runner_blocks_before_execution_when_qc_gate_fails(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "qc_gate_demo",
            """
import json


def launch(_inputs, context):
    path = context.base_dir / "execution_log.json"
    path.write_text(json.dumps(["launch"]), encoding="utf-8")
    return {"submission_bundle": {"status": "submitted"}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "qc-gate-demo",
                "version": "1.0.0",
                "name": "QC Gate Demo",
                "purpose": "Verify that before_execution QC gates block execution when inputs are absent.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest required by a QC preflight gate.",
                    }
                ],
                "runtime": {
                    "provided_inputs": ["seed", "dataset_manifest"],
                    "allowed_parameter_overrides": ["seed"],
                    "generated_state": [
                        "run_id",
                        "created_at",
                        "resolved_input_paths",
                        "step_statuses",
                        "artifact_paths",
                    ],
                    "state_artifact": "workflow_run",
                    "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
                },
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [
                    {
                        "id": "dataset-manifest-required",
                        "label": "Dataset manifest is required before launch",
                        "when": "before_execution",
                        "target": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                        "failure_policy": "block",
                        "description": "Block execution until the manifest is available.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 1})

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "created"
        assert "QC gate dataset-manifest-required failed" in result.run.warnings[0]
        assert not (tmp_path / "execution_log.json").exists()

    def test_runner_evaluates_structured_qc_policy_and_blocks_downstream_steps(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "qc_policy_demo",
            """
def collect_metrics(_inputs, _context):
    return {
        "qc_evidence_bundle": {
            "assay_type": "perturb_seq",
            "qc_evidence": {
                "upstream_tools": ["multiqc"],
                "metrics": [
                    {
                        "metric_name": "median_genes_per_cell",
                        "observed_value": 180,
                        "source_artifact": {
                            "artifact_type": "qa_report",
                            "path": "artifacts/qc-policy-demo/run-1/qa_report.json",
                        },
                    },
                    {
                        "metric_name": "pct_counts_mito",
                        "observed_value": 27.5,
                        "source_artifact": {
                            "artifact_type": "qa_report",
                            "path": "artifacts/qc-policy-demo/run-1/qa_report.json",
                        },
                    },
                    {
                        "metric_name": "donor_balance_ratio",
                        "observed_value": 0.72,
                        "source_artifact": {
                            "artifact_type": "qa_report",
                            "path": "artifacts/qc-policy-demo/run-1/qa_report.json",
                        },
                    },
                ],
            },
        },
    }


def publish(_inputs, context):
    (context.base_dir / "publish_ran.txt").write_text("published\\n", encoding="utf-8")
    return {"submission_bundle": {"status": "published"}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "qc-policy-demo",
                "version": "1.0.0",
                "name": "QC Policy Demo",
                "purpose": "Verify structured QC policy evaluation blocks downstream interpretation steps.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed parameter for the demo workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "publish",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [
                    {
                        "id": "evaluate-scrna-policy",
                        "label": "Evaluate reusable single-cell QC policy",
                        "when": "after_step",
                        "target": {
                            "source_type": "step_output",
                            "step_id": "collect_metrics",
                            "output_name": "qc_evidence_bundle",
                        },
                        "failure_policy": "block",
                        "policy": {
                            "policy_id": "scrna-default-qc",
                            "label": "Single-cell default QC policy",
                            "version": "1.0.0",
                            "assay_type": "scrna_seq",
                            "required_upstream_tools": ["fastqc", "multiqc"],
                            "checks": [
                                {
                                    "id": "median-genes-per-cell",
                                    "label": "Median genes per cell",
                                    "metric_name": "median_genes_per_cell",
                                    "category": "technical",
                                    "comparison": "minimum",
                                    "pass_threshold": 300,
                                    "warn_threshold": 200,
                                },
                                {
                                    "id": "mitochondrial-percentage",
                                    "label": "Mitochondrial fraction",
                                    "metric_name": "pct_counts_mito",
                                    "category": "technical",
                                    "comparison": "maximum",
                                    "pass_threshold": 20,
                                    "warn_threshold": 25,
                                },
                                {
                                    "id": "donor-balance",
                                    "label": "Donor balance ratio",
                                    "metric_name": "donor_balance_ratio",
                                    "category": "batch_effect",
                                    "comparison": "minimum",
                                    "pass_threshold": 0.8,
                                    "warn_threshold": 0.6,
                                },
                            ],
                            "assay_overrides": [
                                {
                                    "assay_type": "perturb_seq",
                                    "check_overrides": [
                                        {
                                            "check_id": "median-genes-per-cell",
                                            "pass_threshold": 350,
                                            "warn_threshold": 250,
                                        }
                                    ],
                                }
                            ],
                        },
                        "description": "Block publication if reusable QC policy detects technical failures.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "collect_metrics",
                        "label": "Collect metrics",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "collect_metrics",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qc_evidence_bundle",
                                "kind": "value",
                                "description": "Structured QC evidence for policy evaluation.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "publish",
                        "label": "Publish",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "publish",
                        },
                        "inputs": [
                            {
                                "name": "qc_evidence_bundle",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect_metrics",
                                    "output_name": "qc_evidence_bundle",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": ["collect_metrics"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 7}, event_callback=events.append)

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "completed"
        assert result.run.steps[1].status == "blocked"
        assert not (tmp_path / "publish_ran.txt").exists()
        assert result.run.qc_status == "failed"
        assert result.run.qc_policies[0].policy_id == "scrna-default-qc"
        assert result.run.qc_policy_results[0].overall_status == "fail"
        assert result.run.qc_policy_results[0].applied_assay_override == "perturb_seq"
        assert "Technical failures" in result.run.qc_summary
        assert "Batch-effect warnings" in result.run.qc_summary
        assert any(detail.field_path == "pct_counts_mito" for detail in result.run.warning_details)
        assert events[-1]["type"] == "workflow_done"
        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["blocking_source"] == "qc_gate"
        assert any(detail["field_path"] == "median_genes_per_cell" for detail in blocked_event["issue_details"])

    def test_authored_rna_seq_workflow_evaluates_manifest_attached_qc_policy(self, tmp_path):
        manifest_relpath = _stage_authored_rna_seq_workflow(tmp_path)

        result = InternalDAGRunner(tmp_path).run(
            tmp_path / "workflows" / "rna-seq-qc.yaml",
            {"dataset_manifest": manifest_relpath},
        )

        assert result.run.lifecycle_status == "completed"
        assert result.run.qc_status == "warning"
        assert result.run.qc_policy_results
        assert result.run.qc_policy_results[0].policy_id == "scrna-default-qc"
        assert result.run.qc_policy_results[0].overall_status == "warn"
        assert "Batch-effect warnings" in (result.run.qc_summary or "")

    def test_runner_rejects_invalid_file_backed_qc_sources_instead_of_parsing_them_as_raw_yaml(self, tmp_path):
        invalid_manifest = tmp_path / "manifests" / "not-a-manifest.yaml"
        invalid_manifest.parent.mkdir(parents=True, exist_ok=True)
        invalid_manifest.write_text(
            json.dumps(
                {
                    "assay_type": "perturb_seq",
                    "qc_evidence": {
                        "upstream_tools": ["fastqc", "multiqc"],
                        "metrics": [
                            {
                                "metric_name": "median_genes_per_cell",
                                "observed_value": 500,
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        module_name = _write_runner_module(
            tmp_path,
            "invalid_qc_source_demo",
            """
def emit_invalid_manifest(_inputs, _context):
    return {"dataset_manifest": "manifests/not-a-manifest.yaml"}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "invalid-qc-source-demo",
                "version": "1.0.0",
                "name": "Invalid QC Source Demo",
                "purpose": "Verify malformed file-backed QC sources fail closed.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed parameter for the demo workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Emitted dataset manifest path.",
                        "source": {
                            "step_id": "emit_invalid_manifest",
                            "output_name": "dataset_manifest",
                        },
                    }
                ],
                "qc_gates": [
                    {
                        "id": "evaluate-invalid-qc-source",
                        "label": "Reject invalid file-backed QC sources",
                        "when": "after_step",
                        "target": {
                            "source_type": "step_output",
                            "step_id": "emit_invalid_manifest",
                            "output_name": "dataset_manifest",
                        },
                        "failure_policy": "block",
                        "policy": {
                            "policy_id": "scrna-default-qc",
                            "label": "Single-cell default QC policy",
                            "version": "1.0.0",
                            "required_upstream_tools": ["fastqc", "multiqc"],
                            "checks": [
                                {
                                    "id": "median-genes-per-cell",
                                    "label": "Median genes per cell",
                                    "metric_name": "median_genes_per_cell",
                                    "category": "technical",
                                    "comparison": "minimum",
                                    "pass_threshold": 300,
                                    "warn_threshold": 200,
                                }
                            ],
                        },
                        "description": "Malformed artifacts should fail closed rather than be parsed as ad hoc QC records.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "emit_invalid_manifest",
                        "label": "Emit invalid manifest",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "emit_invalid_manifest",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "dataset_manifest",
                                "kind": "artifact",
                                "artifact_type": "dataset_manifest",
                                "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                                "description": "Malformed manifest path used to exercise fail-closed policy loading.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 1})

        assert result.run.lifecycle_status == "blocked"
        assert "QC gate evaluate-invalid-qc-source failed" in result.run.warnings[0]
        assert result.run.qc_policy_results == []

    def test_runner_blocks_before_execution_when_required_compliance_hook_stops_run(self, tmp_path, monkeypatch):
        module_name = _write_runner_module(
            tmp_path,
            "compliance_hook_demo",
            """
import json


def launch(_inputs, context):
    path = context.base_dir / "execution_log.json"
    path.write_text(json.dumps(["launch"]), encoding="utf-8")
    return {"submission_bundle": {"status": "submitted"}}
""",
        )
        manifest_path = tmp_path / "manifests" / "dataset_manifest.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("dataset_id: ds-1\n", encoding="utf-8")

        def _blocked_preflight(_base_dir, _payload):
            artifact_relpath = "artifacts/compliance-preflight/2026-03-19/run-20260319T000000Z-abcdef12/compliance_report.json"
            artifact_path = tmp_path / artifact_relpath
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                report=SimpleNamespace(
                    id="compliance-report-demo",
                    run_id="run-20260319T000000Z-abcdef12",
                ),
                artifact_relpath=artifact_relpath,
                tool_summary="Approval required before execution can continue.",
                warning_text=None,
                should_continue=False,
            )

        monkeypatch.setattr("compliance.preflight.run_compliance_preflight", _blocked_preflight)

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "compliance-hook-demo",
                "version": "1.0.0",
                "name": "Compliance Hook Demo",
                "purpose": "Verify that required compliance hooks block execution before any step runs.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest passed into the compliance hook.",
                    }
                ],
                "optional_inputs": [],
                "runtime": {
                    "provided_inputs": ["dataset_manifest"],
                    "allowed_parameter_overrides": [],
                    "generated_state": [
                        "run_id",
                        "created_at",
                        "resolved_input_paths",
                        "step_statuses",
                        "artifact_paths",
                    ],
                    "state_artifact": "workflow_run",
                    "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
                },
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [
                    {
                        "id": "privacy-preflight",
                        "stage": "before_execution",
                        "tool": "compliance_preflight",
                        "required": True,
                        "inputs": [
                            {
                                "name": "dataset_manifest",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "dataset_manifest",
                                },
                            }
                        ],
                        "description": "Run required compliance screening before execution.",
                    }
                ],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
                        },
                        "inputs": [
                            {
                                "name": "dataset_manifest",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "dataset_manifest",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"dataset_manifest": "manifests/dataset_manifest.yaml"})

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "created"
        assert not (tmp_path / "execution_log.json").exists()
        assert any(ref.artifact_type == "compliance_report" for ref in result.run.related_artifacts)
        assert "Compliance hook privacy-preflight blocked execution" in result.run.warnings[0]

    def test_runner_emits_blocked_and_done_events_for_blocked_preflight(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "blocked_stream_demo",
            """
def launch(inputs, _context):
    return {"submission_bundle": {"dataset_manifest": inputs["dataset_manifest"]}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "blocked-stream-demo",
                "version": "1.0.0",
                "name": "Blocked Stream Demo",
                "purpose": "Verify blocked workflow event emission before step execution.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest required by the gate.",
                    }
                ],
                "optional_inputs": [],
                "runtime": {
                    "provided_inputs": ["dataset_manifest"],
                    "allowed_parameter_overrides": [],
                    "generated_state": [
                        "run_id",
                        "created_at",
                        "resolved_input_paths",
                        "step_statuses",
                        "artifact_paths",
                    ],
                    "state_artifact": "workflow_run",
                    "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
                },
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [
                    {
                        "id": "dataset-manifest-required",
                        "label": "Dataset manifest required",
                        "when": "before_execution",
                        "target": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                        "failure_policy": "block",
                        "description": "Block execution while required manifest info is missing.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
                        },
                        "inputs": [
                            {
                                "name": "dataset_manifest",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "dataset_manifest",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec,
            {"dataset_manifest": "manifests/missing-dataset-manifest.yaml"},
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert [event["type"] for event in events] == [
            "workflow_start",
            "workflow_artifact",
            "workflow_blocked",
            "workflow_done",
        ]
        assert events[2]["blocking_source"] == "qc_gate"
        assert events[2]["stage"] == "before_execution"
        assert "dataset-manifest-required" in events[2]["reason"]
        assert events[3]["lifecycle_status"] == "blocked"

    def test_blocked_dataset_intake_failures_preserve_structured_issue_details(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "blocked_step_demo",
            """
from dataset_intake import ensure_valid_dataset_intake_manifest


def validate(inputs, context):
    ensure_valid_dataset_intake_manifest(context.base_dir, inputs["dataset_manifest"])
""",
        )
        manifest_payload = {
            "schema_version": SCHEMA_PACK_VERSION,
            "artifact_type": "dataset_manifest",
            "id": "ds-blocked-step-v1",
            "run_id": "run-20260319T000000Z-deadbeef",
            "created_at": "2026-03-19T00:00:00Z",
            "source_workflow": "dataset-intake",
            "related_artifacts": [],
            "assay_type": "scrna_seq",
            "organism": "homo_sapiens",
            "reference_build": "grch38",
            "privacy_classification": "controlled",
            "design": {
                "study_name": "blocked-step-demo",
                "experiment_type": "scrna_seq",
                "condition_summary": "single-condition pilot",
                "analysis_kind": "descriptive",
                "timepoints": ["baseline"],
                "factors": ["condition"],
            },
            "source_files": ["data/counts.h5ad"],
        }
        manifest_path = tmp_path / "manifests" / "dataset_manifest.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
        source_file = tmp_path / "data" / "counts.h5ad"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("placeholder\n", encoding="utf-8")

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "blocked-step-warning-demo",
                "version": "1.0.0",
                "name": "Blocked Step Warning Demo",
                "purpose": "Verify blocked step failures preserve the blocking reason on the run record.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Manifest passed into the dataset intake gate.",
                    }
                ],
                "optional_inputs": [],
                "runtime": {
                    "provided_inputs": ["dataset_manifest"],
                    "allowed_parameter_overrides": [],
                    "generated_state": [
                        "run_id",
                        "created_at",
                        "resolved_input_paths",
                        "step_statuses",
                        "artifact_paths",
                    ],
                    "state_artifact": "workflow_run",
                    "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
                },
                "outputs": [
                    {
                        "name": "blocked_payload",
                        "kind": "value",
                        "description": "Unreached output reserved for spec validation.",
                        "source": {
                            "step_id": "preflight_check",
                            "output_name": "blocked_payload",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "preflight_check",
                        "label": "Validate Dataset Intake",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "validate",
                        },
                        "inputs": [
                            {
                                "name": "dataset_manifest",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "dataset_manifest",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "blocked_payload",
                                "kind": "value",
                                "description": "Unreached output reserved for spec validation.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "block_workflow",
                    }
                ],
            }
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec,
            {"dataset_manifest": "manifests/dataset_manifest.yaml"},
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "blocked"
        assert len(result.run.warnings) == 1
        assert "sample_sheet_path" in result.run.warnings[0]
        assert result.run.steps[0].errors == result.run.warnings
        assert result.run.warning_details[0].field_path == "sample_sheet_path"
        assert result.run.warning_details[0].code == "missing_field"
        assert result.run.steps[0].error_details[0].field_path == "sample_sheet_path"
        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["issue_details"][0]["field_path"] == "sample_sheet_path"
        assert blocked_event["issue_details"][0]["code"] == "missing_field"
        step_end_event = next(event for event in events if event["type"] == "workflow_step_end")
        assert step_end_event["error_details"][0]["field_path"] == "sample_sheet_path"
        assert step_end_event["error_details"][0]["code"] == "missing_field"
        run_document = load_artifact_document(result.artifact_path)
        assert run_document.warning_details[0].field_path == "sample_sheet_path"
        assert run_document.steps[0].error_details[0].field_path == "sample_sheet_path"

    def test_runner_uses_slugified_workflow_identity_in_workflow_run_artifact(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "slug_demo",
            """
def launch(inputs, _context):
    return {"submission_bundle": {"seed": inputs["seed"]}}
""",
        )
        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "demo_workflow",
                "version": "1.0.0",
                "name": "Slug Demo",
                "purpose": "Verify workflow run documents use the path slug expected by the registry.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "submission_bundle",
                        "kind": "value",
                        "description": "Submission result.",
                        "source": {
                            "step_id": "launch",
                            "output_name": "submission_bundle",
                        },
                    }
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "launch",
                        "label": "Launch",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "launch",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "submission_bundle",
                                "kind": "value",
                                "description": "Submission result.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 2})
        snapshot = rebuild_artifact_registry(tmp_path)

        assert result.run.workflow.slug == "demo-workflow"
        workflow_run_record = next(record for record in snapshot.records if record.artifact_type == "workflow_run")
        assert workflow_run_record.status == "valid"

    def test_authored_rnaseq_workflow_skeleton_runs_and_emits_declared_outputs(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )

        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert result.run.lifecycle_status == "completed"
        assert [step.status for step in result.run.steps] == [
            "completed",
            "completed",
            "completed",
            "completed",
            "completed",
            "completed",
        ]
        raw_qc_step = next(step for step in result.run.steps if step.id == "raw_qc")
        aggregated_qc_step = next(step for step in result.run.steps if step.id == "aggregated_qc")
        quantification_step = next(step for step in result.run.steps if step.id == "quantification")
        differential_expression_step = next(
            step for step in result.run.steps if step.id == "differential_expression"
        )
        assert {ref.artifact_type for ref in raw_qc_step.outputs_produced} == {
            "workflow_value",
            "fastqc_run",
            "fastqc_metrics",
        }
        assert {ref.artifact_type for ref in aggregated_qc_step.outputs_produced} == {
            "workflow_value",
            "multiqc_run",
            "multiqc_metrics",
        }
        assert {ref.artifact_type for ref in quantification_step.outputs_produced} == {
            "workflow_value",
            "count_matrix",
        }
        assert {ref.artifact_type for ref in differential_expression_step.outputs_produced} == {
            "workflow_value",
            "normalized_count_matrix",
            "differential_expression_results",
            "differential_expression_run",
        }
        assert (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_run.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_metrics.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc.stdout.txt").exists()
        assert (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc.stderr.txt").exists()
        assert (result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc_run.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc_metrics.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc.stdout.txt").exists()
        assert (result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc.stderr.txt").exists()
        assert (
            result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc" / "multiqc_report.html"
        ).exists()
        assert (result.run_dir / "outputs" / "generated" / "quantification" / "quantification_bundle.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "quantification" / "count_matrix.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "quantification" / "gene_counts.tsv").exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "differential_expression_bundle.json"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "normalized_count_matrix.json"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "differential_expression_results.json"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "differential_expression_run.json"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "treated-vs-control.normalized_counts.tsv"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "treated-vs-control.tsv"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "treated-vs-control.volcano.svg"
        ).exists()
        assert (
            result.run_dir
            / "outputs"
            / "generated"
            / "differential-expression"
            / "treated-vs-control.mean-difference.svg"
        ).exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md").exists()
        assert (result.run_dir / "fastqc_run.json").exists()
        assert (result.run_dir / "fastqc_metrics.json").exists()
        assert (result.run_dir / "multiqc_run.json").exists()
        assert (result.run_dir / "multiqc_metrics.json").exists()
        assert (result.run_dir / "count_matrix.json").exists()
        assert (result.run_dir / "normalized_count_matrix.json").exists()
        assert (result.run_dir / "differential_expression_results.json").exists()
        assert (result.run_dir / "differential_expression_run.json").exists()
        assert (result.run_dir / "qa_report.json").exists()

        report_bundle_payload = json.loads(
            (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").read_text(
                encoding="utf-8"
            )
        )["value"]
        fastqc_run = load_artifact_document(result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_run.json")
        fastqc_metrics = load_artifact_document(
            result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_metrics.json"
        )
        multiqc_run = load_artifact_document(
            result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc_run.json"
        )
        multiqc_metrics = load_artifact_document(
            result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc_metrics.json"
        )
        count_matrix = load_artifact_document(result.run_dir / "count_matrix.json")
        normalized_count_matrix = load_artifact_document(result.run_dir / "normalized_count_matrix.json")
        differential_expression_results = load_artifact_document(
            result.run_dir / "differential_expression_results.json"
        )
        differential_expression_run = load_artifact_document(
            result.run_dir / "differential_expression_run.json"
        )
        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        expected_provenance_exports = [
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/prov.json",
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/ro-crate/ro-crate-metadata.json",
        ]
        expected_biocompute_exports = [
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/biocompute.json",
        ]
        provenance_payload = json.loads((result.run_dir / "prov.json").read_text(encoding="utf-8"))
        ro_crate_payload = json.loads(
            (result.run_dir / "ro-crate" / "ro-crate-metadata.json").read_text(encoding="utf-8")
        )
        biocompute_artifact = load_artifact_document(result.run_dir / "biocompute.json")
        content_hash_manifest = json.loads((result.run_dir / "content_hashes.json").read_text(encoding="utf-8"))
        report_bundle_markdown = (
            result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")

        assert fastqc_run.tool_name == "fastqc"
        assert fastqc_metrics.aggregate_metrics.sample_count == 6
        assert fastqc_metrics.aggregate_metrics.input_file_count == 12
        assert fastqc_metrics.aggregate_metrics.fastqc_pass_rate == 1.0
        assert multiqc_run.tool_name == "multiqc"
        assert multiqc_metrics.aggregate_metrics.report_sample_count == 6
        assert multiqc_metrics.aggregate_metrics.fastqc_pass_rate == 1.0
        assert count_matrix.engine_name == "bioapex_deterministic_quantification"
        assert len(count_matrix.sample_ids) == 6
        assert len(count_matrix.gene_ids) == 10
        assert normalized_count_matrix.engine_name == "bioapex_mean_centered_t_test"
        assert normalized_count_matrix.gene_count == len(count_matrix.gene_ids)
        assert differential_expression_results.engine_name == "bioapex_mean_centered_t_test"
        assert differential_expression_results.significant_gene_count >= 1
        assert differential_expression_run.summary.significant_gene_count >= 1
        assert differential_expression_run.summary.top_upregulated_gene in {
            "IFIT1",
            "ISG15",
            "OAS1",
            "MX1",
            "CXCL10",
        }
        assert any(
            ref.artifact_type == "fastqc_run" and ref.path.endswith("/fastqc_run.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "fastqc_metrics" and ref.path.endswith("/fastqc_metrics.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "multiqc_run" and ref.path.endswith("/multiqc_run.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "multiqc_metrics" and ref.path.endswith("/multiqc_metrics.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "count_matrix" and ref.path.endswith("/count_matrix.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "normalized_count_matrix"
            and ref.path.endswith("/normalized_count_matrix.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "differential_expression_results"
            and ref.path.endswith("/differential_expression_results.json")
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "differential_expression_run"
            and ref.path.endswith("/differential_expression_run.json")
            for ref in result.run.outputs
        )
        assert any(ref.artifact_type == "fastqc_run" for ref in result.run.related_artifacts)
        assert any(ref.artifact_type == "fastqc_metrics" for ref in result.run.related_artifacts)
        assert any(ref.artifact_type == "multiqc_run" for ref in result.run.related_artifacts)
        assert any(ref.artifact_type == "multiqc_metrics" for ref in result.run.related_artifacts)
        assert any(ref.artifact_type == "count_matrix" for ref in result.run.related_artifacts)
        assert any(ref.artifact_type == "normalized_count_matrix" for ref in result.run.related_artifacts)
        assert any(
            ref.artifact_type == "differential_expression_results" for ref in result.run.related_artifacts
        )
        assert any(ref.artifact_type == "differential_expression_run" for ref in result.run.related_artifacts)
        assert result.run.provenance_exports == expected_provenance_exports
        assert result.run.biocompute_exports == expected_biocompute_exports
        assert (result.run_dir / "prov.json").exists()
        assert (result.run_dir / "ro-crate" / "ro-crate-metadata.json").exists()
        assert (result.run_dir / "biocompute.json").exists()
        assert any(
            artifact["artifact_type"] == "fastqc_run"
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["artifact_type"] == "workflow_run" and artifact["path"].endswith("/run.json")
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["artifact_type"] == "multiqc_run"
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["artifact_type"] == "count_matrix"
            and artifact["path"].endswith("/count_matrix.json")
            and "/outputs/generated/" not in artifact["path"]
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["artifact_type"] == "normalized_count_matrix"
            and artifact["path"].endswith("/normalized_count_matrix.json")
            and "/outputs/generated/" not in artifact["path"]
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["artifact_type"] == "differential_expression_results"
            and artifact["path"].endswith("/differential_expression_results.json")
            and "/outputs/generated/" not in artifact["path"]
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["artifact_type"] == "differential_expression_run"
            and artifact["path"].endswith("/differential_expression_run.json")
            and "/outputs/generated/" not in artifact["path"]
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["path"].endswith("outputs/generated/aggregated-qc/multiqc/multiqc_report.html")
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["path"].endswith("outputs/generated/differential-expression/treated-vs-control.tsv")
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert any(
            artifact["path"].endswith("outputs/generated/report-bundle/rnaseq_report_bundle.md")
            for artifact in report_bundle_payload["expected_artifacts"]
        )
        assert report_bundle_payload["bundle_version"] == "1.0.0"
        assert report_bundle_payload["lifecycle_status"] == "completed"
        assert report_bundle_payload["qc_status"] == "passed"
        assert report_bundle_payload["report_markdown_path"].endswith(
            "outputs/generated/report-bundle/rnaseq_report_bundle.md"
        )
        assert report_bundle_payload["provenance_exports"] == expected_provenance_exports
        assert report_bundle_payload["sections"] == [
            "executive_summary",
            "inputs_used",
            "workflow_version",
            "qc_summary",
            "key_outputs",
            "warnings_and_failures",
            "deviations",
            "provenance_pointers",
            "next_recommended_actions",
        ]
        assert report_bundle_payload["missing_artifacts"] == []
        assert report_bundle_payload["deviations"] == []
        assert report_bundle_payload["deviation_summary"]["count"] == 0
        assert qa_report.overall_status == "passed"
        assert qa_report.missing_artifacts == []
        assert qa_report.warnings == []
        assert any(item.artifact_type == "workflow_run" for item in qa_report.checklist_artifacts)
        assert any(item.artifact_type == "count_matrix" for item in qa_report.checklist_artifacts)
        assert any(
            item.artifact_type == "differential_expression_results"
            for item in qa_report.checklist_artifacts
        )
        assert provenance_payload["artifact_type"] == "provenance"
        assert provenance_payload["workflow"]["version"] == "1.0.0"
        assert provenance_payload["workflow"]["lifecycle_status"] == "completed"
        assert provenance_payload["terminal_state"]["is_partial"] is False
        assert any(
            entity["path"] == manifest_relpath
            and entity["hash"]["algorithm"] == "sha256"
            and entity["hash"]["digest"]
            for entity in provenance_payload["entity"].values()
        )
        assert any(
            entity["path"].endswith("/count_matrix.json")
            and entity["hash"]["algorithm"] == "sha256"
            for entity in provenance_payload["entity"].values()
        )
        assert next(
            entity for entity in provenance_payload["entity"].values() if entity["path"].endswith("/content_hashes.json")
        )["hash"] is None
        assert {item["name"] for item in provenance_payload["tool_versions"]} >= {
            "fastqc",
            "multiqc",
            "bioapex_deterministic_quantification",
            "bioapex_mean_centered_t_test",
        }
        assert "prov.json" in content_hash_manifest["hashes"]
        assert "ro-crate/ro-crate-metadata.json" in content_hash_manifest["hashes"]
        assert any(entry.get("@id") == "../prov.json" for entry in ro_crate_payload["@graph"])
        assert any(
            entry.get("@type") == "CreateAction"
            and entry.get("actionStatus") == "CompletedActionStatus"
            for entry in ro_crate_payload["@graph"]
        )
        assert biocompute_artifact.type == "rna_seq_differential_expression"
        empirical_error = biocompute_artifact.error_domain.empirical_error[
            "urn:bioapex:biocompute:error:observed-run-state:1.0.0"
        ]
        algorithmic_error = biocompute_artifact.error_domain.algorithmic_error[
            "urn:bioapex:biocompute:error:export-completeness:1.0.0"
        ]
        assert empirical_error.observed["warning_count"] == 0
        assert empirical_error.observed["error_count"] == 0
        assert algorithmic_error.observed["export_status"] == "full"
        assert len(biocompute_artifact.extension_domain) == 1
        assert biocompute_artifact.extension_domain[0].extension_schema == public_raw_file_url(
            "artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json"
        )
        assert biocompute_artifact.extension_domain[0].bioapex_extension.export_status == "full"
        assert (
            biocompute_artifact.extension_domain[0].bioapex_extension.provenance_exports
            == expected_provenance_exports
        )
        assert biocompute_artifact.extension_domain[0].bioapex_extension.workflow_run.path.endswith("/run.json")
        assert biocompute_artifact.description_domain.xref
        assert {xref.namespace for xref in biocompute_artifact.description_domain.xref} == {"taxonomy"}
        assert biocompute_artifact.description_domain.xref[0].ids == ["9606"]
        assert all(
            isinstance(step.step_number, int) for step in biocompute_artifact.description_domain.pipeline_steps
        )
        assert biocompute_artifact.io_domain.output_subdomain
        assert biocompute_artifact.execution_domain.script_driver == "internal_dag_runner_v1"
        validate_biocompute_payload_against_reference_schemas(biocompute_artifact.model_dump(mode="json"))
        assert "Differential Expression Summary" in report_bundle_markdown
        assert "## Workflow Version" in report_bundle_markdown
        assert "## QC Summary" in report_bundle_markdown
        assert "Workflow lifecycle status: `completed`" in report_bundle_markdown
        assert "Workflow QC status: `passed`" in report_bundle_markdown
        assert expected_provenance_exports[0] in report_bundle_markdown
        assert expected_provenance_exports[1] in report_bundle_markdown
        assert "No provenance exports were materialized for this run." not in report_bundle_markdown
        assert "No structured workflow deviations were recorded for this run." in report_bundle_markdown
        assert next(ref.path for ref in result.run.outputs if ref.artifact_type == "count_matrix") in report_bundle_markdown
        assert (
            next(ref.path for ref in result.run.outputs if ref.artifact_type == "differential_expression_run")
            in report_bundle_markdown
        )
        assert {
            item.metric_name: item.value
            for item in result.run.summary_metrics
            if item.stage == "aggregated_qc"
        } == {
            "fastqc_pass_rate": 1.0,
            "total_reads_millions": 14.4,
            "min_per_base_quality": 31.5,
            "report_sample_count": 6,
        }
        quantification_metrics = {
            item.metric_name: item.value
            for item in result.run.summary_metrics
            if item.stage == "quantification"
        }
        differential_expression_metrics = {
            item.metric_name: item.value
            for item in result.run.summary_metrics
            if item.stage == "differential_expression"
        }
        assert quantification_metrics == {"sample_count": 6, "gene_count": 10}
        assert differential_expression_metrics["tested_gene_count"] == 10
        assert differential_expression_metrics["minimum_condition_replicates"] == 3
        assert differential_expression_metrics["missing_expected_batch_fields"] == 0
        assert differential_expression_metrics["significant_gene_count"] >= 1

    def test_authored_rnaseq_workflow_uses_configured_public_base_url_for_extension_schema(
        self,
        tmp_path,
        monkeypatch,
    ):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )
        monkeypatch.setenv("BIOAPEX_PUBLIC_BASE_URL", "https://bioapex.example.org/base/")

        runner = InternalDAGRunner(tmp_path)
        result = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert result.run.lifecycle_status == "completed"
        biocompute_artifact = load_artifact_document(result.run_dir / "biocompute.json")
        assert biocompute_artifact.extension_domain[0].extension_schema == public_raw_file_url(
            "artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json"
        )

    def test_authored_rnaseq_workflow_refreshes_stale_report_bundle_when_resuming_legacy_final_run(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )

        runner = InternalDAGRunner(tmp_path)
        first = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert first.run.lifecycle_status == "completed"
        expected_provenance_exports = [
            f"{first.run_dir.relative_to(tmp_path).as_posix()}/prov.json",
            f"{first.run_dir.relative_to(tmp_path).as_posix()}/ro-crate/ro-crate-metadata.json",
        ]
        expected_biocompute_exports = [
            f"{first.run_dir.relative_to(tmp_path).as_posix()}/biocompute.json",
        ]
        run_payload = json.loads((first.run_dir / "run.json").read_text(encoding="utf-8"))
        run_payload["provenance_exports"] = []
        run_payload["biocompute_exports"] = []
        (first.run_dir / "run.json").write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")
        (first.run_dir / "prov.json").unlink()
        shutil.rmtree(first.run_dir / "ro-crate")
        (first.run_dir / "biocompute.json").unlink()

        report_bundle_path = first.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json"
        report_bundle_payload = json.loads(report_bundle_path.read_text(encoding="utf-8"))
        report_bundle_payload["value"]["provenance_exports"] = []
        report_bundle_path.write_text(json.dumps(report_bundle_payload, indent=2) + "\n", encoding="utf-8")
        report_bundle_markdown_path = first.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        report_bundle_markdown_path.write_text(
            "# Legacy report bundle\n\n- No provenance exports were materialized for this run.\n",
            encoding="utf-8",
        )

        resumed = runner.run(spec_path, run_dir=first.run_dir)

        assert resumed.resumed is True
        assert resumed.run.lifecycle_status == "completed"
        refreshed_report_bundle_payload = json.loads(report_bundle_path.read_text(encoding="utf-8"))["value"]
        refreshed_report_bundle_markdown = report_bundle_markdown_path.read_text(encoding="utf-8")
        assert refreshed_report_bundle_payload["provenance_exports"] == expected_provenance_exports
        assert expected_provenance_exports[0] in refreshed_report_bundle_markdown
        assert "No provenance exports were materialized for this run." not in refreshed_report_bundle_markdown
        assert resumed.run.provenance_exports == expected_provenance_exports
        assert resumed.run.biocompute_exports == expected_biocompute_exports
        assert (first.run_dir / "prov.json").exists()
        assert (first.run_dir / "ro-crate" / "ro-crate-metadata.json").exists()
        assert (first.run_dir / "biocompute.json").exists()

    def test_authored_rnaseq_workflow_clears_stale_biocompute_materialization_warnings_after_successful_resume(
        self,
        tmp_path,
        monkeypatch,
    ):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )
        failure_prefix = "Optional BioCompute export could not be materialized deterministically:"

        def _failing_biocompute_bundle(*args, **kwargs):
            raise RuntimeError("simulated bioCompute export failure")

        real_materialize = workflow_runner_module.materialize_biocompute_bundle
        monkeypatch.setattr(workflow_runner_module, "materialize_biocompute_bundle", _failing_biocompute_bundle)
        runner = InternalDAGRunner(tmp_path)
        first = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert first.run.lifecycle_status == "completed"
        assert first.run.biocompute_exports == []
        assert not (first.run_dir / "biocompute.json").exists()
        assert any(warning.startswith(failure_prefix) for warning in first.run.warnings)

        monkeypatch.setattr(workflow_runner_module, "materialize_biocompute_bundle", real_materialize)
        resumed = runner.run(spec_path, run_dir=first.run_dir)

        assert resumed.resumed is True
        assert resumed.run.lifecycle_status == "completed"
        assert resumed.run.biocompute_exports == [
            f"{first.run_dir.relative_to(tmp_path).as_posix()}/biocompute.json",
        ]
        assert (first.run_dir / "biocompute.json").exists()
        assert not any(warning.startswith(failure_prefix) for warning in resumed.run.warnings)

    def test_authored_rnaseq_workflow_skeleton_supports_single_end_fastqc_inputs(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            sequencing_layout="single_end",
        )

        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert result.run.lifecycle_status == "completed"
        fastqc_run = load_artifact_document(result.run_dir / "fastqc_run.json")
        fastqc_metrics = load_artifact_document(result.run_dir / "fastqc_metrics.json")
        multiqc_metrics = load_artifact_document(result.run_dir / "multiqc_metrics.json")

        assert fastqc_run.sequencing_layout == "single_end"
        assert len(fastqc_run.input_files) == 6
        assert len(fastqc_run.reports) == 6
        assert fastqc_metrics.sequencing_layout == "single_end"
        assert fastqc_metrics.aggregate_metrics.sequencing_layout == "single_end"
        assert fastqc_metrics.aggregate_metrics.sample_count == 6
        assert fastqc_metrics.aggregate_metrics.input_file_count == 6
        assert fastqc_metrics.aggregate_metrics.fastqc_pass_rate == 1.0
        assert multiqc_metrics.aggregate_metrics.fastqc_pass_rate == 1.0
        assert multiqc_metrics.aggregate_metrics.report_sample_count == 6

    def test_authored_rnaseq_workflow_warns_when_expected_batch_field_is_missing(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            omit_batch_column=True,
            design_batch_fields=["batch"],
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            event_callback=events.append,
        )

        qa_report = load_artifact_document(result.run_dir / "qa_report.json")

        assert result.run.lifecycle_status == "completed"
        assert result.run.qc_status == "warning"
        assert any("missing_expected_batch_fields" in warning for warning in result.run.warnings)
        assert result.run.deviations
        assert any(item.severity == "major" for item in result.run.deviations)
        assert qa_report.overall_status == "warning"
        assert qa_report.warnings
        assert any("workflow deviation" in warning.lower() for warning in qa_report.warnings)
        assert not any(event["type"] == "workflow_blocked" for event in events)
        assert {
            item.metric_name: item.value
            for item in result.run.summary_metrics
            if item.stage == "differential_expression"
        }["missing_expected_batch_fields"] == 1

    def test_authored_rnaseq_workflow_report_bundle_preserves_upstream_qc_warnings(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            sample_modes={"treated_rep3": "qualitywarn"},
        )

        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        report_bundle_markdown = (
            result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")

        assert result.run.lifecycle_status == "completed"
        assert result.run.qc_status == "warning"
        assert result.run.warnings
        assert result.run.deviations
        assert qa_report.overall_status == "warning"
        for warning in result.run.warnings:
            assert warning in qa_report.warnings
        assert any("workflow deviation" in warning.lower() for warning in qa_report.warnings)
        assert "Workflow QC status: `warning`" in report_bundle_markdown
        for warning in result.run.warnings:
            assert warning in report_bundle_markdown
        assert "## Deviations" in report_bundle_markdown

    def test_authored_rnaseq_workflow_blocks_when_multiple_expected_batch_fields_are_missing(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            omit_batch_column=True,
            design_batch_fields=["batch", "lane"],
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert result.run.qc_status == "failed"
        assert [step.status for step in result.run.steps] == [
            "completed",
            "completed",
            "completed",
            "completed",
            "completed",
            "blocked",
        ]
        assert (result.run_dir / "count_matrix.json").exists()
        assert (result.run_dir / "normalized_count_matrix.json").exists()
        assert (result.run_dir / "differential_expression_results.json").exists()
        assert (result.run_dir / "differential_expression_run.json").exists()
        assert (result.run_dir / "qa_report.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md").exists()

        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        report_bundle_payload = json.loads(
            (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").read_text(
                encoding="utf-8"
            )
        )["value"]
        expected_provenance_exports = [
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/prov.json",
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/ro-crate/ro-crate-metadata.json",
        ]
        expected_biocompute_exports = [
            f"{result.run_dir.relative_to(tmp_path).as_posix()}/biocompute.json",
        ]
        provenance_payload = json.loads((result.run_dir / "prov.json").read_text(encoding="utf-8"))
        biocompute_artifact = load_artifact_document(result.run_dir / "biocompute.json")
        report_bundle_markdown = (
            result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")

        assert qa_report.overall_status == "blocked"
        assert qa_report.missing_artifacts == []
        assert qa_report.failed_checks
        assert result.run.deviations
        assert any(item.severity == "critical" for item in result.run.deviations)
        assert report_bundle_payload["lifecycle_status"] == "blocked"
        assert report_bundle_payload["provenance_exports"] == expected_provenance_exports
        assert report_bundle_payload["missing_artifacts"] == []
        assert report_bundle_payload["deviation_summary"]["count"] >= 1
        assert result.run.provenance_exports == expected_provenance_exports
        assert result.run.biocompute_exports == expected_biocompute_exports
        assert provenance_payload["workflow"]["lifecycle_status"] == "blocked"
        assert provenance_payload["terminal_state"]["is_partial"] is True
        empirical_error = biocompute_artifact.error_domain.empirical_error[
            "urn:bioapex:biocompute:error:observed-run-state:1.0.0"
        ]
        assert empirical_error.observed["warning_count"] >= 1
        assert biocompute_artifact.extension_domain[0].bioapex_extension.export_status == "full"
        validate_biocompute_payload_against_reference_schemas(biocompute_artifact.model_dump(mode="json"))
        assert "Workflow lifecycle status: `blocked`" in report_bundle_markdown
        assert expected_provenance_exports[0] in report_bundle_markdown
        assert "## Deviations" in report_bundle_markdown

        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["blocking_source"] == "qc_gate"
        assert blocked_event["stage"] == "after_step"
        assert "missing_expected_batch_fields" in blocked_event["reason"]

    def test_authored_rnaseq_workflow_skeleton_blocks_on_aggregated_qc_gate(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            sample_modes={
                "control_rep1": "adapterfail",
                "treated_rep1": "adapterfail",
            },
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert result.run.qc_status == "failed"
        assert [step.status for step in result.run.steps] == [
            "completed",
            "completed",
            "completed",
            "blocked",
            "blocked",
            "blocked",
        ]
        assert (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_run.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_metrics.json").exists()
        assert (result.run_dir / "fastqc_run.json").exists()
        assert (result.run_dir / "fastqc_metrics.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc_run.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "aggregated-qc" / "multiqc_metrics.json").exists()
        assert (result.run_dir / "multiqc_run.json").exists()
        assert (result.run_dir / "multiqc_metrics.json").exists()
        assert (result.run_dir / "qa_report.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md").exists()
        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        report_bundle_payload = json.loads(
            (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").read_text(
                encoding="utf-8"
            )
        )["value"]
        report_bundle_markdown = (
            result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")
        missing_artifact_types = {item.artifact_type for item in qa_report.missing_artifacts}
        assert qa_report.overall_status == "blocked"
        assert qa_report.failed_checks
        assert {"count_matrix", "differential_expression_results"}.issubset(missing_artifact_types)
        assert {
            item["artifact_type"] for item in report_bundle_payload["missing_artifacts"]
        } >= {"count_matrix", "differential_expression_results"}
        assert "Workflow lifecycle status: `blocked`" in report_bundle_markdown
        assert "Missing artifact: `count_matrix`" in report_bundle_markdown
        assert any(
            ref.artifact_type == "fastqc_run"
            and ref.path.endswith("/fastqc_run.json")
            and "outputs/generated/raw-qc/" not in ref.path
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "fastqc_metrics"
            and ref.path.endswith("/fastqc_metrics.json")
            and "outputs/generated/raw-qc/" not in ref.path
            for ref in result.run.outputs
        )
        assert any(
            ref.artifact_type == "multiqc_metrics"
            and ref.path.endswith("/multiqc_metrics.json")
            and "outputs/generated/aggregated-qc/" not in ref.path
            for ref in result.run.outputs
        )

        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["blocking_source"] == "qc_gate"
        assert blocked_event["stage"] == "after_step"
        assert "fastqc_pass_rate" in blocked_event["reason"]

    def test_authored_rnaseq_workflow_blocks_when_fastqc_execution_fails(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            sample_modes={"control_rep1": "execfail"},
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "completed"
        assert result.run.steps[1].status == "blocked"
        assert all(step.status == "blocked" for step in result.run.steps[2:])
        assert not (result.run_dir / "outputs" / "generated" / "raw-qc" / "fastqc_run.json").exists()
        assert not (result.run_dir / "fastqc_run.json").exists()
        assert not (result.run_dir / "fastqc_metrics.json").exists()
        assert not (result.run_dir / "multiqc_run.json").exists()
        assert not (result.run_dir / "multiqc_metrics.json").exists()
        assert (result.run_dir / "qa_report.json").exists()
        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        assert qa_report.overall_status == "blocked"
        assert {"fastqc_run", "multiqc_run"}.issubset(
            {item.artifact_type for item in qa_report.missing_artifacts}
        )

        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["blocking_source"] == "step_failure"
        assert blocked_event["stage"] == "after_step"

    def test_authored_rnaseq_workflow_materializes_terminal_report_bundle_when_manifest_cannot_be_loaded(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)

        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": "manifests/missing_dataset_manifest.yaml",
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert result.run.lifecycle_status == "blocked"
        report_step = next(step for step in result.run.steps if step.id == "report_bundle")
        assert report_step.status == "blocked"
        assert any(ref.artifact_type == "workflow_value" for ref in report_step.outputs_produced)
        assert any(ref.artifact_type == "qa_report" for ref in report_step.outputs_produced)
        assert (result.run_dir / "qa_report.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").exists()
        assert (result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md").exists()

        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        report_bundle_payload = json.loads(
            (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").read_text(
                encoding="utf-8"
            )
        )["value"]
        report_bundle_markdown = (
            result.run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")

        assert qa_report.overall_status == "blocked"
        assert any("dataset_manifest could not be loaded" in warning for warning in qa_report.warnings)
        assert report_bundle_payload["study_name"] == "unknown-study"
        assert report_bundle_payload["lifecycle_status"] == "blocked"
        assert "Dataset manifest path: `n/a`" in report_bundle_markdown
        assert "Dataset manifest could not be loaded for terminal bundle rendering" in report_bundle_markdown

    def test_authored_rnaseq_workflow_blocks_when_multiqc_execution_fails(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
            sample_modes={"control_rep1": "multiqcfail"},
        )

        events: list[dict] = []
        result = InternalDAGRunner(tmp_path).run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            event_callback=events.append,
        )

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "completed"
        assert result.run.steps[1].status == "completed"
        assert result.run.steps[2].status == "blocked"
        assert all(step.status == "blocked" for step in result.run.steps[3:])
        assert (result.run_dir / "fastqc_run.json").exists()
        assert (result.run_dir / "fastqc_metrics.json").exists()
        assert not (result.run_dir / "multiqc_run.json").exists()
        assert not (result.run_dir / "multiqc_metrics.json").exists()
        assert (result.run_dir / "qa_report.json").exists()
        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        assert qa_report.overall_status == "blocked"
        assert {"multiqc_run", "count_matrix"}.issubset(
            {item.artifact_type for item in qa_report.missing_artifacts}
        )

        blocked_event = next(event for event in events if event["type"] == "workflow_blocked")
        assert blocked_event["blocking_source"] == "step_failure"
        assert blocked_event["stage"] == "after_step"
        assert "MultiQC execution failed" in blocked_event["reason"]

    def test_authored_rnaseq_workflow_resumes_before_multiqc_without_rerunning_fastqc(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )

        runner = InternalDAGRunner(tmp_path)
        paused = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
            step_limit=2,
        )

        assert paused.run.lifecycle_status == "waiting"
        assert [step.status for step in paused.run.steps] == [
            "completed",
            "completed",
            "created",
            "created",
            "created",
            "created",
        ]
        assert json.loads((tmp_path / "fastqc_invocations.json").read_text(encoding="utf-8")) == [
            sorted(
                str(path.relative_to(tmp_path))
                for path in sorted((tmp_path / "data" / "rnaseq").glob("*.fastq"))
            )
        ]
        assert not (tmp_path / "multiqc_invocations.json").exists()

        resumed = runner.run(spec_path, run_dir=paused.run_dir)

        assert resumed.resumed is True
        assert resumed.run.lifecycle_status == "completed"
        assert json.loads((tmp_path / "fastqc_invocations.json").read_text(encoding="utf-8")) == [
            sorted(
                str(path.relative_to(tmp_path))
                for path in sorted((tmp_path / "data" / "rnaseq").glob("*.fastq"))
            )
        ]
        assert json.loads((tmp_path / "multiqc_invocations.json").read_text(encoding="utf-8")) == [
            [
                f"{paused.run_dir.relative_to(tmp_path).as_posix()}/outputs/generated/raw-qc/fastqc"
            ]
        ]

    def test_authored_rnaseq_workflow_can_rerun_multiqc_from_completed_run(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )

        runner = InternalDAGRunner(tmp_path)
        completed = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert completed.run.lifecycle_status == "completed"
        assert json.loads((tmp_path / "fastqc_invocations.json").read_text(encoding="utf-8")) == [
            sorted(
                str(path.relative_to(tmp_path))
                for path in sorted((tmp_path / "data" / "rnaseq").glob("*.fastq"))
            )
        ]
        assert json.loads((tmp_path / "multiqc_invocations.json").read_text(encoding="utf-8")) == [
            [
                f"{completed.run_dir.relative_to(tmp_path).as_posix()}/outputs/generated/raw-qc/fastqc"
            ]
        ]

        rerun = runner.run(
            spec_path,
            run_dir=completed.run_dir,
            restart_from_step="aggregated_qc",
        )

        assert rerun.resumed is True
        assert rerun.run.lifecycle_status == "completed"
        assert json.loads((tmp_path / "fastqc_invocations.json").read_text(encoding="utf-8")) == [
            sorted(
                str(path.relative_to(tmp_path))
                for path in sorted((tmp_path / "data" / "rnaseq").glob("*.fastq"))
            )
        ]
        assert json.loads((tmp_path / "multiqc_invocations.json").read_text(encoding="utf-8")) == [
            [
                f"{completed.run_dir.relative_to(tmp_path).as_posix()}/outputs/generated/raw-qc/fastqc"
            ],
            [
                f"{completed.run_dir.relative_to(tmp_path).as_posix()}/outputs/generated/raw-qc/fastqc"
            ],
        ]

    def test_authored_rnaseq_workflow_clears_stale_deviations_for_reset_steps_on_restart(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )

        runner = InternalDAGRunner(tmp_path)
        completed = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        run_payload = json.loads((completed.run_dir / "run.json").read_text(encoding="utf-8"))
        run_payload["deviations"] = [
            {
                "run_id": completed.run.run_id,
                "step_id": "aggregated_qc",
                "severity": "major",
                "origin": "automatic",
                "logged_at": "2026-03-20T20:00:00Z",
                "original_expected_behavior": "Legacy restart test expected aggregated QC to complete cleanly.",
                "actual_behavior": "Legacy deviation that should be removed when aggregated_qc is restarted.",
                "reason": "Injected stale deviation for restart coverage.",
                "impact_assessment": "Should not survive the restart once the affected step is rerun.",
                "author_or_agent": "system:test",
            }
        ]
        (completed.run_dir / "run.json").write_text(json.dumps(run_payload, indent=2) + "\n", encoding="utf-8")

        rerun = runner.run(
            spec_path,
            run_dir=completed.run_dir,
            restart_from_step="aggregated_qc",
        )

        assert rerun.resumed is True
        assert rerun.run.lifecycle_status == "completed"
        assert all(item.step_id != "aggregated_qc" for item in rerun.run.deviations)

    def test_authored_rnaseq_workflow_removes_stale_multiqc_root_outputs_when_rerun_fails(self, tmp_path):
        spec_path = _stage_authored_rnaseq_qc_de_workflow(tmp_path)
        fastqc_executable = _write_fake_fastqc_executable(tmp_path)
        multiqc_executable = _write_fake_multiqc_executable(tmp_path)
        manifest_relpath = _write_bulk_rnaseq_manifest(
            tmp_path,
            fastqc_executable=fastqc_executable,
            multiqc_executable=multiqc_executable,
        )

        runner = InternalDAGRunner(tmp_path)
        completed = runner.run(
            spec_path,
            {
                "dataset_manifest": manifest_relpath,
                "condition_field": "condition",
                "baseline_condition": "control",
                "comparison_condition": "treated",
            },
        )

        assert completed.run.lifecycle_status == "completed"
        assert (completed.run_dir / "fastqc_run.json").exists()
        assert (completed.run_dir / "fastqc_metrics.json").exists()
        assert (completed.run_dir / "multiqc_run.json").exists()
        assert (completed.run_dir / "multiqc_metrics.json").exists()

        trigger_path = (
            completed.run_dir
            / "outputs"
            / "generated"
            / "raw-qc"
            / "fastqc"
            / "rerun_multiqcfail_fastqc.html"
        )
        trigger_path.write_text("<html><body>rerun fail</body></html>\n", encoding="utf-8")

        rerun = runner.run(
            spec_path,
            run_dir=completed.run_dir,
            restart_from_step="aggregated_qc",
        )

        assert rerun.resumed is True
        assert rerun.run.lifecycle_status == "blocked"
        assert (completed.run_dir / "fastqc_run.json").exists()
        assert (completed.run_dir / "fastqc_metrics.json").exists()
        assert not (completed.run_dir / "multiqc_run.json").exists()
        assert not (completed.run_dir / "multiqc_metrics.json").exists()
        assert not any(ref.artifact_type == "multiqc_run" for ref in rerun.run.outputs)
        assert not any(ref.artifact_type == "multiqc_metrics" for ref in rerun.run.outputs)
        assert not any(ref.artifact_type == "multiqc_run" for ref in rerun.run.related_artifacts)
        assert not any(ref.artifact_type == "multiqc_metrics" for ref in rerun.run.related_artifacts)
        assert json.loads((tmp_path / "multiqc_invocations.json").read_text(encoding="utf-8")) == [
            [
                f"{completed.run_dir.relative_to(tmp_path).as_posix()}/outputs/generated/raw-qc/fastqc"
            ],
            [
                f"{completed.run_dir.relative_to(tmp_path).as_posix()}/outputs/generated/raw-qc/fastqc"
            ],
        ]

    def test_runner_does_not_materialize_publish_ready_artifacts_when_before_publish_blocks(self, tmp_path, monkeypatch):
        module_name = _write_runner_module(
            tmp_path,
            "before_publish_demo",
            """
def emit(_inputs, _context):
    return {
        "qa_report": {
            "overall_status": "passed",
            "failed_checks": [],
            "warnings": [],
            "missing_artifacts": [],
            "recommended_remediation": [],
            "checklist_artifacts": [],
        }
    }
""",
        )

        def _blocked_preflight(_base_dir, _payload):
            artifact_relpath = "artifacts/compliance-preflight/2026-03-19/run-20260319T000000Z-abcdef12/compliance_report.json"
            artifact_path = tmp_path / artifact_relpath
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                report=SimpleNamespace(
                    id="compliance-report-before-publish",
                    run_id="run-20260319T000000Z-abcdef12",
                ),
                artifact_relpath=artifact_relpath,
                tool_summary="Publish review failed.",
                warning_text=None,
                should_continue=False,
            )

        monkeypatch.setattr("compliance.preflight.run_compliance_preflight", _blocked_preflight)

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "before-publish-demo",
                "version": "1.0.0",
                "name": "Before Publish Demo",
                "purpose": "Verify that required before_publish hooks stop stable output publication.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [_qa_report_output("emit", "qa_report")],
                "qc_gates": [],
                "compliance_hooks": [
                    {
                        "id": "publish-review",
                        "stage": "before_publish",
                        "tool": "compliance_preflight",
                        "required": True,
                        "inputs": [
                            {
                                "name": "qa_report",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "emit",
                                    "output_name": "qa_report",
                                },
                            }
                        ],
                        "description": "Block publication until compliance review passes.",
                    }
                ],
                "steps": [
                    {
                        "id": "emit",
                        "label": "Emit QA Report",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "emit",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "QA artifact emitted by the workflow.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 3})

        assert result.run.lifecycle_status == "blocked"
        assert result.run.steps[0].status == "completed"
        assert result.run.deviations
        assert result.run.deviations[0].step_id == "emit"
        assert result.run.deviations[0].severity == "critical"
        assert (result.run_dir / "outputs" / "generated" / "emit" / "qa_report.json").exists()
        assert not (result.run_dir / "qa_report.json").exists()
        assert result.run.outputs[0].path.endswith("outputs/generated/emit/qa_report.json")

    def test_terminal_report_bundle_materializer_preserves_literal_bindings(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "terminal_report_literal_demo",
            """
def collect(_inputs, _context):
    return {"report_inputs": {"note": "upstream"}}


def fail(_inputs, _context):
    raise RuntimeError("synthetic failure")


def materialize_terminal_report_bundle(inputs, _context):
    return {
        "qa_report": {
            "overall_status": "blocked",
            "failed_checks": [
                {
                    "id": "synthetic-block",
                    "description": inputs["literal_note"],
                    "severity": "error",
                    "artifact_type": "workflow_run",
                    "remediation": "retry",
                }
            ],
            "warnings": [inputs["literal_note"]],
            "missing_artifacts": [],
            "recommended_remediation": [inputs["literal_note"]],
            "checklist_artifacts": [],
        },
        "report_bundle_manifest": {
            "literal_note": inputs["literal_note"],
        },
    }
""",
        )

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "terminal-report-literal-demo",
                "version": "1.0.0",
                "name": "Terminal Report Literal Demo",
                "purpose": "Verify literal bindings are preserved when terminal report bundles are materialized after a blocked run.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "report_bundle_manifest",
                        "kind": "value",
                        "description": "Terminal report manifest.",
                        "source": {
                            "step_id": "report_bundle",
                            "output_name": "report_bundle_manifest",
                        },
                    },
                    _qa_report_output("report_bundle", "qa_report"),
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "collect",
                        "label": "Collect",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "collect",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "report_inputs",
                                "kind": "value",
                                "description": "Upstream report inputs.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "fail",
                        "label": "Fail",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "fail",
                        },
                        "inputs": [
                            {
                                "name": "report_inputs",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect",
                                    "output_name": "report_inputs",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "unused_output",
                                "kind": "value",
                                "description": "Unused output because the step fails.",
                            }
                        ],
                        "prerequisites": ["collect"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "report_bundle",
                        "label": "Report bundle",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "materialize_terminal_report_bundle",
                        },
                        "inputs": [
                            {
                                "name": "report_inputs",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect",
                                    "output_name": "report_inputs",
                                },
                            },
                            {
                                "name": "literal_note",
                                "source": {
                                    "source_type": "literal",
                                    "value": "literal-note-preserved",
                                },
                            },
                        ],
                        "outputs": [
                            {
                                "name": "report_bundle_manifest",
                                "kind": "value",
                                "description": "Terminal report manifest.",
                            },
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "Terminal QA report.",
                            },
                        ],
                        "prerequisites": ["collect", "fail"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 1})

        assert result.run.lifecycle_status == "failed"
        report_step = next(step for step in result.run.steps if step.id == "report_bundle")
        assert report_step.status == "blocked"
        assert any(ref.artifact_type == "qa_report" for ref in report_step.outputs_produced)
        qa_report = load_artifact_document(result.run_dir / "qa_report.json")
        assert qa_report.warnings == ["literal-note-preserved"]
        manifest_payload = json.loads(
            (result.run_dir / "outputs" / "generated" / "report-bundle" / "report_bundle_manifest.json").read_text(
                encoding="utf-8"
            )
        )["value"]
        assert manifest_payload["literal_note"] == "literal-note-preserved"

    def test_rnaseq_report_bundle_links_related_evidence_reviews(self, tmp_path):
        module_spec = importlib.util.spec_from_file_location(
            "bioapex_test_rnaseq_qc_de",
            REPO_ROOT / "workflows" / "runners" / "rnaseq_qc_de.py",
        )
        assert module_spec is not None
        assert module_spec.loader is not None
        rnaseq_runner = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(rnaseq_runner)

        manifest = load_artifact_document(REPO_ROOT / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml")
        workflow_run = load_artifact_document(REPO_ROOT / "backend" / "artifacts" / "examples" / "run.json")
        evidence_review_path = (
            "artifacts/evidence-review/2026-03-20/"
            "run-20260320T210000Z-feedface/evidence_review.json"
        )
        workflow_run.related_artifacts.append(
            ArtifactReference.model_validate(
                {
                    "artifact_type": "evidence_review",
                    "path": evidence_review_path,
                    "id": "evidence-review-run-20260320t210000z-feedface",
                    "run_id": "run-20260320T210000Z-feedface",
                }
            )
        )

        run_relpath = Path("artifacts/rnaseq-qc-de/2026-03-20/run-20260320T220000Z-deadbeef")
        run_dir = tmp_path / run_relpath
        run_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            base_dir=tmp_path,
            run_dir=run_dir,
            relative_run_dir=run_relpath.as_posix(),
            run_id="run-20260320T220000Z-deadbeef",
            workflow_id="rnaseq_qc_de",
            relative_path=lambda path: str(path),
        )

        outputs = rnaseq_runner._build_rnaseq_report_bundle_outputs(
            context=context,
            manifest_path="manifests/demo_dataset_manifest.yaml",
            manifest=manifest,
            workflow_run=workflow_run,
            raw_qc_bundle={},
            aggregated_qc_bundle={},
            quantification_bundle={},
            differential_expression_bundle={},
            condition_field="condition",
            baseline_condition="control",
            comparison_condition="treated",
            report_lifecycle_status="completed",
        )

        manifest_payload = outputs["report_bundle_manifest"]
        assert manifest_payload["evidence_review_artifacts"] == [
            {
                "artifact_type": "evidence_review",
                "path": evidence_review_path,
                "id": "evidence-review-run-20260320t210000z-feedface",
                "run_id": "run-20260320T210000Z-feedface",
            }
        ]
        assert any(
            artifact["artifact_type"] == "evidence_review"
            and artifact["path"] == evidence_review_path
            for artifact in manifest_payload["expected_artifacts"]
        )
        assert manifest_payload["deviation_summary"]["count"] == 1
        assert manifest_payload["deviations"][0]["step_id"] == "qc-summary"
        assert outputs["qa_report"]["related_artifacts"] == manifest_payload["evidence_review_artifacts"]
        assert any(
            artifact["artifact_type"] == "evidence_review"
            and artifact["path"] == evidence_review_path
            for artifact in outputs["qa_report"]["checklist_artifacts"]
        )
        assert any("workflow deviation" in warning.lower() for warning in outputs["qa_report"]["warnings"])

        report_bundle_markdown = (
            run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")
        assert "Evidence review artifacts" in report_bundle_markdown
        assert evidence_review_path in report_bundle_markdown
        assert "## Deviations" in report_bundle_markdown

    def test_rnaseq_report_bundle_keeps_minor_deviations_visible_without_degrading_status(self, tmp_path):
        module_spec = importlib.util.spec_from_file_location(
            "bioapex_test_rnaseq_qc_de_minor",
            REPO_ROOT / "workflows" / "runners" / "rnaseq_qc_de.py",
        )
        assert module_spec is not None
        assert module_spec.loader is not None
        rnaseq_runner = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(rnaseq_runner)

        manifest = load_artifact_document(REPO_ROOT / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml")
        workflow_run = load_artifact_document(REPO_ROOT / "backend" / "artifacts" / "examples" / "run.json")
        workflow_run.qc_status = "passed"
        workflow_run.warnings = []
        workflow_run.deviations = [
            workflow_run.deviations[0].model_copy(update={"severity": "minor"})
        ]

        run_relpath = Path("artifacts/rnaseq-qc-de/2026-03-20/run-20260320T223000Z-deadbeef")
        run_dir = tmp_path / run_relpath
        run_dir.mkdir(parents=True, exist_ok=True)
        context = SimpleNamespace(
            base_dir=tmp_path,
            run_dir=run_dir,
            relative_run_dir=run_relpath.as_posix(),
            run_id="run-20260320T223000Z-deadbeef",
            workflow_id="rnaseq_qc_de",
            relative_path=lambda path: str(path),
        )

        outputs = rnaseq_runner._build_rnaseq_report_bundle_outputs(
            context=context,
            manifest_path="manifests/demo_dataset_manifest.yaml",
            manifest=manifest,
            workflow_run=workflow_run,
            raw_qc_bundle={},
            aggregated_qc_bundle={},
            quantification_bundle={},
            differential_expression_bundle={},
            condition_field="condition",
            baseline_condition="control",
            comparison_condition="treated",
            report_lifecycle_status="completed",
        )

        assert outputs["qa_report"]["overall_status"] == "passed"
        assert outputs["qa_report"]["warnings"] == []
        assert outputs["qa_report"]["failed_checks"] == []
        assert outputs["report_bundle_manifest"]["deviation_summary"]["highest_severity"] == "minor"

        report_bundle_markdown = (
            run_dir / "outputs" / "generated" / "report-bundle" / "rnaseq_report_bundle.md"
        ).read_text(encoding="utf-8")
        assert "## Deviations" in report_bundle_markdown
        assert "[minor/automatic]" in report_bundle_markdown

    def test_terminal_report_bundle_materializer_is_idempotent_when_resuming_final_run(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "terminal_report_resume_demo",
            """
import json


def _log(context, entry):
    path = context.base_dir / "terminal_report_log.json"
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries), encoding="utf-8")


def collect(_inputs, _context):
    return {"report_inputs": {"note": "upstream"}}


def fail(_inputs, _context):
    raise RuntimeError("synthetic failure")


def materialize_terminal_report_bundle(inputs, context):
    _log(context, inputs["literal_note"])
    return {
        "qa_report": {
            "overall_status": "failed",
            "failed_checks": [
                {
                    "id": "synthetic-failure",
                    "description": inputs["literal_note"],
                    "severity": "critical",
                    "artifact_type": "workflow_run",
                    "remediation": "retry",
                }
            ],
            "warnings": [inputs["literal_note"]],
            "missing_artifacts": [],
            "recommended_remediation": [inputs["literal_note"]],
            "checklist_artifacts": [],
        },
        "report_bundle_manifest": {
            "literal_note": inputs["literal_note"],
        },
    }
""",
        )

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "terminal-report-resume-demo",
                "version": "1.0.0",
                "name": "Terminal Report Resume Demo",
                "purpose": "Verify terminal report materialization is not re-run when resuming a final workflow.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "report_bundle_manifest",
                        "kind": "value",
                        "description": "Terminal report manifest.",
                        "source": {
                            "step_id": "report_bundle",
                            "output_name": "report_bundle_manifest",
                        },
                    },
                    _qa_report_output("report_bundle", "qa_report"),
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "collect",
                        "label": "Collect",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "collect",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "report_inputs",
                                "kind": "value",
                                "description": "Upstream report inputs.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "fail",
                        "label": "Fail",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "fail",
                        },
                        "inputs": [
                            {
                                "name": "report_inputs",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect",
                                    "output_name": "report_inputs",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "unused_output",
                                "kind": "value",
                                "description": "Unused output because the step fails.",
                            }
                        ],
                        "prerequisites": ["collect"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "report_bundle",
                        "label": "Report bundle",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "materialize_terminal_report_bundle",
                        },
                        "inputs": [
                            {
                                "name": "report_inputs",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect",
                                    "output_name": "report_inputs",
                                },
                            },
                            {
                                "name": "literal_note",
                                "source": {
                                    "source_type": "literal",
                                    "value": "terminal-report-ran-once",
                                },
                            },
                        ],
                        "outputs": [
                            {
                                "name": "report_bundle_manifest",
                                "kind": "value",
                                "description": "Terminal report manifest.",
                            },
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "Terminal QA report.",
                            },
                        ],
                        "prerequisites": ["collect", "fail"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        runner = InternalDAGRunner(tmp_path)
        first = runner.run(spec, {"seed": 1})
        resumed = runner.run(spec, run_dir=first.run_dir)

        assert first.run.lifecycle_status == "failed"
        assert resumed.resumed is True
        assert resumed.run.lifecycle_status == "failed"
        assert json.loads((tmp_path / "terminal_report_log.json").read_text(encoding="utf-8")) == [
            "terminal-report-ran-once"
        ]
        report_step = next(step for step in resumed.run.steps if step.id == "report_bundle")
        assert report_step.status == "blocked"
        assert any(ref.artifact_type == "qa_report" for ref in report_step.outputs_produced)

    def test_terminal_report_bundle_materializer_persists_warning_when_helper_fails(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "terminal_report_warning_demo",
            """
def collect(_inputs, _context):
    return {"report_inputs": {"note": "upstream"}}


def fail(_inputs, _context):
    raise RuntimeError("synthetic failure")


def materialize_terminal_report_bundle(_inputs, _context):
    raise RuntimeError("synthetic terminal helper failure")
""",
        )

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "terminal-report-warning-demo",
                "version": "1.0.0",
                "name": "Terminal Report Warning Demo",
                "purpose": "Verify terminal report helper failures are persisted into the canonical run record.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [],
                "runtime": _runtime_contract(["seed"]),
                "outputs": [
                    {
                        "name": "report_bundle_manifest",
                        "kind": "value",
                        "description": "Terminal report manifest.",
                        "source": {
                            "step_id": "report_bundle",
                            "output_name": "report_bundle_manifest",
                        },
                    },
                    _qa_report_output("report_bundle", "qa_report"),
                ],
                "qc_gates": [],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "collect",
                        "label": "Collect",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "collect",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "report_inputs",
                                "kind": "value",
                                "description": "Upstream report inputs.",
                            }
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "fail",
                        "label": "Fail",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "fail",
                        },
                        "inputs": [
                            {
                                "name": "report_inputs",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect",
                                    "output_name": "report_inputs",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "unused_output",
                                "kind": "value",
                                "description": "Unused output because the step fails.",
                            }
                        ],
                        "prerequisites": ["collect"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                    {
                        "id": "report_bundle",
                        "label": "Report bundle",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "materialize_terminal_report_bundle",
                        },
                        "inputs": [
                            {
                                "name": "report_inputs",
                                "source": {
                                    "source_type": "step_output",
                                    "step_id": "collect",
                                    "output_name": "report_inputs",
                                },
                            }
                        ],
                        "outputs": [
                            {
                                "name": "report_bundle_manifest",
                                "kind": "value",
                                "description": "Terminal report manifest.",
                            },
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "Terminal QA report.",
                            },
                        ],
                        "prerequisites": ["collect", "fail"],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    },
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 1})

        assert result.run.lifecycle_status == "failed"
        assert any(
            "synthetic terminal helper failure" in warning for warning in result.run.warnings
        )
        persisted_run = load_artifact_document(result.artifact_path)
        assert any(
            "synthetic terminal helper failure" in warning for warning in persisted_run.warnings
        )
        report_step = next(step for step in persisted_run.steps if step.id == "report_bundle")
        assert any(
            "synthetic terminal helper failure" in warning for warning in report_step.warnings
        )

    def test_terminal_report_bundle_materializer_marks_ready_step_blocked_after_preflight_block(self, tmp_path):
        module_name = _write_runner_module(
            tmp_path,
            "terminal_report_preflight_demo",
            """
def materialize_terminal_report_bundle(inputs, _context):
    return {
        "qa_report": {
            "overall_status": "blocked",
            "failed_checks": [
                {
                    "id": "preflight-block",
                    "description": inputs["literal_note"],
                    "severity": "error",
                    "artifact_type": "workflow_run",
                    "remediation": "retry",
                }
            ],
            "warnings": [inputs["literal_note"]],
            "missing_artifacts": [],
            "recommended_remediation": [inputs["literal_note"]],
            "checklist_artifacts": [],
        },
        "report_bundle_manifest": {
            "literal_note": inputs["literal_note"],
        },
    }
""",
        )

        spec = validate_workflow_spec_payload(
            {
                "schema_version": WORKFLOW_SPEC_VERSION,
                "kind": "workflow_spec",
                "workflow_id": "terminal-report-preflight-demo",
                "version": "1.0.0",
                "name": "Terminal Report Preflight Demo",
                "purpose": "Verify terminal report materialization updates a ready report step after a preflight block.",
                "engine": "internal_dag_runner_v1",
                "required_inputs": [
                    {
                        "name": "seed",
                        "kind": "parameter",
                        "data_type": "integer",
                        "description": "Seed integer for the test workflow.",
                    }
                ],
                "optional_inputs": [
                    {
                        "name": "dataset_manifest",
                        "kind": "artifact",
                        "artifact_type": "dataset_manifest",
                        "schema_ref": "artifact_schema:dataset_manifest@1.0.0",
                        "description": "Optional manifest gate target.",
                    }
                ],
                "runtime": {
                    "provided_inputs": ["seed", "dataset_manifest"],
                    "allowed_parameter_overrides": ["seed"],
                    "generated_state": [
                        "run_id",
                        "created_at",
                        "resolved_input_paths",
                        "step_statuses",
                        "artifact_paths",
                    ],
                    "state_artifact": "workflow_run",
                    "artifact_root_template": "artifacts/{workflow_id}/{date}/{run_id}",
                },
                "outputs": [
                    {
                        "name": "report_bundle_manifest",
                        "kind": "value",
                        "description": "Terminal report manifest.",
                        "source": {
                            "step_id": "report_bundle",
                            "output_name": "report_bundle_manifest",
                        },
                    },
                    _qa_report_output("report_bundle", "qa_report"),
                ],
                "qc_gates": [
                    {
                        "id": "dataset-manifest-required",
                        "label": "Dataset manifest required",
                        "when": "before_execution",
                        "target": {
                            "source_type": "workflow_input",
                            "input_name": "dataset_manifest",
                        },
                        "failure_policy": "block",
                        "description": "Block execution while the manifest is missing.",
                    }
                ],
                "compliance_hooks": [],
                "steps": [
                    {
                        "id": "report_bundle",
                        "label": "Report bundle",
                        "executor": {
                            "executor_type": "python",
                            "module": module_name,
                            "function": "materialize_terminal_report_bundle",
                        },
                        "inputs": [
                            {
                                "name": "seed",
                                "source": {
                                    "source_type": "workflow_input",
                                    "input_name": "seed",
                                },
                            },
                            {
                                "name": "literal_note",
                                "source": {
                                    "source_type": "literal",
                                    "value": "preflight-note",
                                },
                            },
                        ],
                        "outputs": [
                            {
                                "name": "report_bundle_manifest",
                                "kind": "value",
                                "description": "Terminal report manifest.",
                            },
                            {
                                "name": "qa_report",
                                "kind": "artifact",
                                "artifact_type": "qa_report",
                                "schema_ref": "artifact_schema:qa_report@1.0.0",
                                "description": "Terminal QA report.",
                            },
                        ],
                        "prerequisites": [],
                        "retry_policy": {"max_attempts": 1, "backoff_seconds": 0},
                        "failure_policy": "fail_workflow",
                    }
                ],
            }
        )

        result = InternalDAGRunner(tmp_path).run(spec, {"seed": 1})

        assert result.run.lifecycle_status == "blocked"
        report_step = next(step for step in result.run.steps if step.id == "report_bundle")
        assert report_step.status == "blocked"
        assert report_step.start_time is not None
        assert report_step.end_time is not None
        assert any(ref.artifact_type == "workflow_value" for ref in report_step.outputs_produced)
        assert any(ref.artifact_type == "qa_report" for ref in report_step.outputs_produced)
