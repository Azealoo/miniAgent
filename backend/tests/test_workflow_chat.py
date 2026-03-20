import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[2]


def _stage_selected_workflow(
    base_dir: Path,
    *,
    include_manifest: bool = True,
    include_array_input: bool = False,
) -> str | None:
    workflows_dir = base_dir / "workflows"
    runners_dir = workflows_dir / "runners"
    report_templates_dir = workflows_dir / "report_templates"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    runners_dir.mkdir(parents=True, exist_ok=True)
    report_templates_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "__init__.py").write_text('"""Temporary workflow package for workflow chat tests."""\n', encoding="utf-8")
    (runners_dir / "__init__.py").write_text('"""Temporary workflow runners for workflow chat tests."""\n', encoding="utf-8")
    shutil.copy2(REPO_ROOT / "workflows" / "rna-seq-qc.yaml", workflows_dir / "rna-seq-qc.yaml")
    shutil.copy2(REPO_ROOT / "workflows" / "runners" / "rna_seq_qc.py", runners_dir / "rna_seq_qc.py")
    shutil.copy2(
        REPO_ROOT / "workflows" / "report_templates" / "rna_seq_qc_summary.md.j2",
        report_templates_dir / "rna_seq_qc_summary.md.j2",
    )
    if include_array_input:
        spec_path = workflows_dir / "rna-seq-qc.yaml"
        spec_payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        assert isinstance(spec_payload, dict)
        optional_inputs = spec_payload.setdefault("optional_inputs", [])
        assert isinstance(optional_inputs, list)
        optional_inputs.append(
            {
                "name": "checklist_ids",
                "kind": "metadata",
                "data_type": "array",
                "default": [],
                "description": "Optional checklist identifiers for selected workflow chat tests.",
            }
        )
        runtime = spec_payload.setdefault("runtime", {})
        assert isinstance(runtime, dict)
        provided_inputs = runtime.setdefault("provided_inputs", [])
        assert isinstance(provided_inputs, list)
        provided_inputs.append("checklist_ids")
        spec_path.write_text(yaml.safe_dump(spec_payload, sort_keys=False), encoding="utf-8")

    if not include_manifest:
        return None

    manifest_relpath = "manifests/dataset_manifest.yaml"
    manifest_path = base_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml",
        manifest_path,
    )
    for relpath in (
        "data/norman/sample_sheet.tsv",
        "data/norman/counts.h5ad",
        "data/norman/metadata.tsv",
    ):
        target = base_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("placeholder\n", encoding="utf-8")
    return manifest_relpath


def test_prepare_selected_workflow_run_supports_named_attachment_binding(tmp_path):
    from workflow_chat import prepare_selected_workflow_run

    manifest_relpath = _stage_selected_workflow(tmp_path)
    assert manifest_relpath is not None

    prepared = prepare_selected_workflow_run(
        tmp_path,
        "rna-seq-qc",
        message="Run the RNA-seq QC workflow with min_genes=250",
        attached_identifiers=[
            "qc_summary_template=workflows/report_templates/rna_seq_qc_summary.md.j2",
            f"dataset_manifest={manifest_relpath}",
        ],
    )

    assert prepared.blocking_reason is None
    assert prepared.inputs["dataset_manifest"] == manifest_relpath
    assert prepared.inputs["qc_summary_template"] == "workflows/report_templates/rna_seq_qc_summary.md.j2"
    assert prepared.inputs["min_genes"] == 250


def test_prepare_selected_workflow_run_parses_array_metadata_inputs(tmp_path):
    from workflow_chat import prepare_selected_workflow_run

    manifest_relpath = _stage_selected_workflow(tmp_path, include_array_input=True)
    assert manifest_relpath is not None

    prepared = prepare_selected_workflow_run(
        tmp_path,
        "rna-seq-qc",
        message=(
            "Run the RNA-seq QC workflow with "
            "checklist_ids=[miqe_qpcr_completeness, arrive_animal_study_reporting]"
        ),
        attached_identifiers=[manifest_relpath],
    )

    assert prepared.blocking_reason is None
    assert prepared.inputs["checklist_ids"] == [
        "miqe_qpcr_completeness",
        "arrive_animal_study_reporting",
    ]


def test_materialize_blocked_workflow_run_persists_run_record(tmp_path):
    from artifacts import load_artifact_document
    from workflow_chat import materialize_blocked_workflow_run, prepare_selected_workflow_run

    _stage_selected_workflow(tmp_path, include_manifest=False)
    prepared = prepare_selected_workflow_run(
        tmp_path,
        "rna-seq-qc",
        message="Run the RNA-seq QC workflow",
        attached_identifiers=[],
    )

    assert prepared.blocking_reason is not None
    blocked = materialize_blocked_workflow_run(
        tmp_path,
        prepared,
        reason=prepared.blocking_reason,
    )

    assert blocked.result.artifact_path.exists()
    assert blocked.workflow_events[0]["run_record_path"] == blocked.result.artifact_relpath
    assert (tmp_path / blocked.result.artifact_relpath).exists()

    run_document = load_artifact_document(blocked.result.artifact_path)
    assert run_document.lifecycle_status == "blocked"
    assert run_document.warnings == [prepared.blocking_reason]
    assert any(ref.artifact_type == "workflow_input_bundle" for ref in run_document.related_artifacts)
