import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from artifacts import ProtocolRun, load_artifact_document
from compliance.preflight import CompliancePreflightInput, run_compliance_preflight
from protocol_executor import (
    ProtocolExecutorInput,
    classify_protocol_execution_request,
    run_protocol_executor,
)


def _write_skill(base_dir: Path, skill_name: str, body: str) -> Path:
    path = base_dir / "backend" / "skills" / skill_name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_protocol_executor_blocks_without_explicit_source(tmp_path):
    payload = ProtocolExecutorInput(
        user_message="Walk me through this protocol step by step.",
    )
    classification = classify_protocol_execution_request(tmp_path, payload)
    assert classification.is_protocol_request is True

    preflight = run_compliance_preflight(
        tmp_path,
        CompliancePreflightInput(user_message=payload.user_message),
    )
    result = run_protocol_executor(
        tmp_path,
        payload,
        compliance_report=preflight.report,
        compliance_artifact_relpath=preflight.artifact_relpath,
        classification=classification,
    )

    assert result.tool_result["status"] == "error"
    assert result.tool_result["outcome"] == "invalid_input"
    assert result.protocol_run.completion_state == "blocked"
    assert result.protocol_run.operator == "not_provided"
    assert result.protocol_run.steps == []
    assert result.protocol_run.protocol_source.artifact_type == "protocol_source_request"
    persisted = load_artifact_document(result.artifact_path)
    assert isinstance(persisted, ProtocolRun)
    assert persisted.completion_state == "blocked"


def test_protocol_executor_materializes_in_progress_run_from_explicit_skill(tmp_path):
    _write_skill(
        tmp_path,
        "demo_protocol",
        """---
name: demo_protocol
description: Demo protocol
---

# Demo Protocol

## Steps

1. Label the collection tubes for each sample.
2. Add lysis buffer to each labeled tube.
3. Incubate the tubes for the required hold time.
""",
    )
    payload = ProtocolExecutorInput(
        user_message="Walk me through this protocol step by step using demo_protocol for sample-001.",
    )
    classification = classify_protocol_execution_request(tmp_path, payload)
    assert classification.is_protocol_request is True

    preflight = run_compliance_preflight(
        tmp_path,
        CompliancePreflightInput(user_message=payload.user_message),
    )
    result = run_protocol_executor(
        tmp_path,
        payload,
        compliance_report=preflight.report,
        compliance_artifact_relpath=preflight.artifact_relpath,
        classification=classification,
    )

    assert result.tool_result["status"] == "success"
    assert result.protocol_run.completion_state == "in_progress"
    assert result.protocol_run.operator == "not_provided"
    assert result.protocol_run.protocol_source.artifact_type == "skill_definition"
    assert result.protocol_run.sample_ids == ["sample-001"]
    assert len(result.protocol_run.steps) == 3
    assert result.protocol_run.steps[0].status == "in_progress"
    assert result.protocol_run.steps[1].status == "pending"
    persisted = load_artifact_document(result.artifact_path)
    assert isinstance(persisted, ProtocolRun)
    assert persisted.steps[0].instruction.startswith("Label the collection tubes")


def test_protocol_executor_blocks_unstructured_attached_file(tmp_path):
    manifest_path = tmp_path / "backend" / "artifacts" / "examples" / "dataset_manifest.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        """schema_version: "1.0.0"
artifact_type: dataset_manifest
condition_fields:
  - perturbation
  - donor
""",
        encoding="utf-8",
    )
    payload = ProtocolExecutorInput(
        user_message="Walk me through this protocol step by step using backend/artifacts/examples/dataset_manifest.yaml.",
        attached_identifiers=["backend/artifacts/examples/dataset_manifest.yaml"],
    )
    classification = classify_protocol_execution_request(tmp_path, payload)
    assert classification.is_protocol_request is True

    preflight = run_compliance_preflight(
        tmp_path,
        CompliancePreflightInput(
            user_message=payload.user_message,
            attached_identifiers=payload.attached_identifiers,
        ),
    )
    result = run_protocol_executor(
        tmp_path,
        payload,
        compliance_report=preflight.report,
        compliance_artifact_relpath=preflight.artifact_relpath,
        classification=classification,
    )

    assert result.tool_result["status"] == "error"
    assert result.tool_result["outcome"] == "invalid_input"
    assert result.protocol_run.completion_state == "blocked"
    assert result.protocol_run.steps == []


def test_protocol_executor_blocks_unreadable_attached_file(tmp_path):
    binary_path = tmp_path / "backend" / "artifacts" / "examples" / "binary_protocol.bin"
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_bytes(b"\xff\xfe\x00\x01")
    binary_relpath = binary_path.relative_to(tmp_path).as_posix()
    payload = ProtocolExecutorInput(
        user_message=(
            "Walk me through this protocol step by step using "
            f"{binary_relpath}."
        ),
        attached_identifiers=[binary_relpath],
    )
    classification = classify_protocol_execution_request(tmp_path, payload)
    assert classification.is_protocol_request is True

    preflight = run_compliance_preflight(
        tmp_path,
        CompliancePreflightInput(
            user_message=payload.user_message,
            attached_identifiers=payload.attached_identifiers,
        ),
    )
    result = run_protocol_executor(
        tmp_path,
        payload,
        compliance_report=preflight.report,
        compliance_artifact_relpath=preflight.artifact_relpath,
        classification=classification,
    )

    assert result.tool_result["status"] == "error"
    assert result.tool_result["outcome"] == "invalid_input"
    assert "assumptions_recorded" in result.tool_result["warnings"]
    assert "protocol_source_unreadable" in result.tool_result["warnings"]
    assert result.protocol_run.completion_state == "blocked"
    assert result.protocol_run.protocol_source.path == binary_relpath
    assert result.protocol_run.steps == []
    assert (
        "could not be decoded as UTF-8 text" in result.protocol_run.assumptions[0]
    )
    persisted = load_artifact_document(result.artifact_path)
    assert isinstance(persisted, ProtocolRun)
    assert persisted.completion_state == "blocked"


def test_protocol_executor_blocks_sensitive_step_guidance_even_if_compliance_allows(tmp_path):
    _write_skill(
        tmp_path,
        "influenza_culture_protocol",
        """---
name: influenza_culture_protocol
description: Influenza culture protocol
---

# Influenza Protocol

## Steps

1. Culture influenza virus in permissive cells.
2. Amplify viral material and collect the supernatant.
""",
    )
    payload = ProtocolExecutorInput(
        user_message="Walk me through this protocol step by step using influenza_culture_protocol.",
    )
    classification = classify_protocol_execution_request(tmp_path, payload)
    assert classification.is_protocol_request is True

    preflight = run_compliance_preflight(
        tmp_path,
        CompliancePreflightInput(user_message=payload.user_message),
    )
    assert preflight.report.final_disposition == "allow"

    result = run_protocol_executor(
        tmp_path,
        payload,
        compliance_report=preflight.report,
        compliance_artifact_relpath=preflight.artifact_relpath,
        classification=classification,
    )

    assert result.tool_result["status"] == "error"
    assert result.tool_result["outcome"] == "blocked"
    assert result.protocol_run.completion_state == "blocked"
    assert result.protocol_run.steps == []
