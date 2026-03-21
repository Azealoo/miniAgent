"""Typed workflow spec models and validators for explicit BioAPEX workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from artifacts.schemas import SlurmResourceRequest, normalize_identifier
from qc_policy import QCPolicyDefinition

WORKFLOW_SPEC_VERSION = "1.0.0"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_PYTHON_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STRUCTURED_EXTERNAL_ENGINES = {"nextflow", "snakemake"}

InputKind = Literal["artifact", "parameter", "template", "metadata"]
OutputKind = Literal["artifact", "value"]
ValueType = Literal["string", "integer", "number", "boolean", "object", "array"]
WorkflowQCGateStage = Literal["before_execution", "before_step", "after_step", "before_publish"]
QCGateFailurePolicy = Literal["warn", "block"]
ComplianceHookStage = Literal["before_execution", "before_step", "after_step", "before_publish"]
StepFailurePolicy = Literal["fail_workflow", "block_workflow", "continue_with_warning"]


def _require_non_empty(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def _require_normalized_identifier(value: str, *, field_name: str) -> str:
    cleaned = _require_non_empty(value, field_name=field_name)
    normalized = normalize_identifier(cleaned)
    if cleaned != normalized:
        raise ValueError(f"{field_name} must already be normalized as {normalized!r}.")
    return normalized


def _normalize_relative_path(value: str | PurePosixPath, *, field_name: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError(f"{field_name} must not be empty.")
    if "\\" in raw:
        raise ValueError(f"{field_name} must use forward slashes.")

    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative, not absolute.")
    if candidate.parts == (".",):
        raise ValueError(f"{field_name} must not resolve to '.'.")
    if any(part == ".." for part in candidate.parts):
        raise ValueError(f"{field_name} must not contain '..'.")
    return str(candidate)


def _validate_semver(value: str, *, field_name: str) -> str:
    cleaned = _require_non_empty(value, field_name=field_name)
    if not _SEMVER_RE.fullmatch(cleaned):
        raise ValueError(f"{field_name} must use semantic version format 'x.y.z'.")
    return cleaned


def _validate_artifact_schema_ref(value: str, *, field_name: str, artifact_type: str) -> str:
    cleaned = _require_non_empty(value, field_name=field_name)
    prefix = f"artifact_schema:{artifact_type}@"
    if not cleaned.startswith(prefix):
        raise ValueError(
            f"{field_name} must use the format {prefix}<version>."
        )
    version = cleaned.removeprefix(prefix)
    _validate_semver(version, field_name=field_name)
    return cleaned


def _uses_slurm_execution_profile(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().casefold() == "slurm"


class WorkflowInputSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["workflow_input"] = "workflow_input"
    input_name: str

    @field_validator("input_name")
    @classmethod
    def _validate_input_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="input_name")


class StepOutputSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["step_output"] = "step_output"
    step_id: str
    output_name: str

    @field_validator("step_id", "output_name")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)


class LiteralBindingSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["literal"] = "literal"
    value: Any


BindingSource = Annotated[
    WorkflowInputSource | StepOutputSource | LiteralBindingSource,
    Field(discriminator="source_type"),
]


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = 1
    backoff_seconds: int = 0

    @field_validator("max_attempts")
    @classmethod
    def _validate_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts must be at least 1.")
        return value

    @field_validator("backoff_seconds")
    @classmethod
    def _validate_backoff(cls, value: int) -> int:
        if value < 0:
            raise ValueError("backoff_seconds must be zero or greater.")
        return value


class ToolExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_type: Literal["tool"] = "tool"
    tool_name: str

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="tool_name")


class PythonExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_type: Literal["python"] = "python"
    module: str
    function: str

    @field_validator("module")
    @classmethod
    def _validate_module(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="module")
        if cleaned.startswith(".") or cleaned.endswith(".") or ".." in cleaned:
            raise ValueError("module must use a valid dotted-path form.")
        parts = cleaned.split(".")
        if any(not part or not _PYTHON_IDENTIFIER_RE.fullmatch(part) for part in parts):
            raise ValueError("module must use valid Python dotted identifiers.")
        return cleaned

    @field_validator("function")
    @classmethod
    def _validate_function(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="function")
        if not _PYTHON_IDENTIFIER_RE.fullmatch(cleaned):
            raise ValueError("function must be a valid Python identifier.")
        return cleaned


class ExternalEngineExecutor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_type: Literal["external_engine"] = "external_engine"
    engine_name: str
    entrypoint: str
    command: str | None = None
    engine_version: str | None = None
    version_command: str | None = None
    execution_profile: str | None = None
    parameter_bindings: dict[str, str] = Field(default_factory=dict)
    environment_references: list[str] = Field(default_factory=list)
    output_locations: list[str] = Field(default_factory=list)
    resource_request: SlurmResourceRequest | None = None
    working_directory: str | None = None

    @field_validator("engine_name")
    @classmethod
    def _validate_engine_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="engine_name")

    @field_validator("entrypoint")
    @classmethod
    def _validate_entrypoint(cls, value: str) -> str:
        return _normalize_relative_path(value, field_name="entrypoint")

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="command")

    @field_validator("engine_version", "version_command", "execution_profile")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name=info.field_name)

    @field_validator("parameter_bindings")
    @classmethod
    def _validate_parameter_bindings(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, template in value.items():
            normalized_key = _require_normalized_identifier(str(key), field_name="parameter_bindings key")
            cleaned[normalized_key] = _require_non_empty(
                str(template),
                field_name=f"parameter_bindings[{normalized_key}]",
            )
        return cleaned

    @field_validator("environment_references")
    @classmethod
    def _validate_environment_references(cls, value: list[str]) -> list[str]:
        return [_require_non_empty(item, field_name="environment_references") for item in value]

    @field_validator("output_locations")
    @classmethod
    def _validate_output_locations(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(item, field_name="output_locations") for item in value]

    @field_validator("working_directory")
    @classmethod
    def _validate_working_directory(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value, field_name="working_directory")

    @model_validator(mode="after")
    def _validate_executor_contract(self) -> "ExternalEngineExecutor":
        structured_slurm_backend = (
            self.engine_name in _STRUCTURED_EXTERNAL_ENGINES
            and _uses_slurm_execution_profile(self.execution_profile)
        )
        if self.engine_name == "slurm":
            if self.resource_request is None:
                raise ValueError("Slurm external engines require resource_request.")
            if self.command is not None:
                raise ValueError(
                    "Slurm external engines must use entrypoint plus resource_request instead of command."
                )
        elif self.resource_request is not None and not structured_slurm_backend:
            raise ValueError(
                "resource_request is only supported for engine_name='slurm' or structured external "
                "engines with execution_profile='slurm'."
            )
        if self.engine_name in _STRUCTURED_EXTERNAL_ENGINES:
            if self.command is not None:
                raise ValueError(
                    f"{self.engine_name} external engines must use execution_profile plus parameter_bindings "
                    "instead of command."
                )
            if self.execution_profile is None:
                raise ValueError(f"{self.engine_name} external engines require execution_profile.")
            if not self.parameter_bindings:
                raise ValueError(f"{self.engine_name} external engines require parameter_bindings.")
            if not self.output_locations:
                raise ValueError(f"{self.engine_name} external engines require output_locations.")
            if self.engine_version is None and self.version_command is None:
                raise ValueError(
                    f"{self.engine_name} external engines require engine_version or version_command."
                )
            if structured_slurm_backend and self.resource_request is None:
                raise ValueError(
                    f"{self.engine_name} external engines with execution_profile='slurm' require resource_request."
                )
        return self


StepExecutor = Annotated[
    ToolExecutor | PythonExecutor | ExternalEngineExecutor,
    Field(discriminator="executor_type"),
]


class WorkflowInputDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: InputKind
    description: str
    artifact_type: str | None = None
    schema_ref: str | None = None
    data_type: ValueType | None = None
    template_path: str | None = None
    default: Any = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="name")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_non_empty(value, field_name="description")

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="artifact_type")

    @field_validator("template_path")
    @classmethod
    def _validate_template_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value, field_name="template_path")

    @model_validator(mode="after")
    def _validate_contract(self) -> "WorkflowInputDefinition":
        if self.kind == "artifact":
            if self.artifact_type is None or self.schema_ref is None:
                raise ValueError("Artifact inputs require artifact_type and schema_ref.")
            _validate_artifact_schema_ref(
                self.schema_ref,
                field_name="schema_ref",
                artifact_type=self.artifact_type,
            )
            if self.data_type is not None or self.template_path is not None:
                raise ValueError("Artifact inputs may not define data_type or template_path.")
        elif self.kind == "template":
            if self.template_path is None:
                raise ValueError("Template inputs require template_path.")
            if any(value is not None for value in (self.artifact_type, self.schema_ref, self.data_type)):
                raise ValueError("Template inputs may only define template_path.")
        else:
            if self.data_type is None:
                raise ValueError(f"{self.kind} inputs require data_type.")
            if any(value is not None for value in (self.artifact_type, self.schema_ref, self.template_path)):
                raise ValueError(f"{self.kind} inputs may not define artifact_type, schema_ref, or template_path.")
        return self


class WorkflowRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provided_inputs: list[str] = Field(min_length=1)
    allowed_parameter_overrides: list[str] = Field(default_factory=list)
    generated_state: list[str] = Field(min_length=1)
    state_artifact: Literal["workflow_run"] = "workflow_run"
    artifact_root_template: str

    @field_validator("provided_inputs", "allowed_parameter_overrides", "generated_state")
    @classmethod
    def _validate_identifier_lists(cls, value: list[str], info) -> list[str]:
        return [
            _require_normalized_identifier(item, field_name=info.field_name.rstrip("s"))
            for item in value
        ]

    @field_validator("artifact_root_template")
    @classmethod
    def _validate_artifact_root_template(cls, value: str) -> str:
        cleaned = _require_non_empty(value, field_name="artifact_root_template")
        required_tokens = {"{workflow_id}", "{date}", "{run_id}"}
        missing = sorted(token for token in required_tokens if token not in cleaned)
        if missing:
            raise ValueError(
                "artifact_root_template must include {workflow_id}, {date}, and {run_id}."
            )
        if not cleaned.startswith("artifacts/"):
            raise ValueError("artifact_root_template must stay under artifacts/.")
        return cleaned


class StepOutputDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: OutputKind
    description: str
    artifact_type: str | None = None
    schema_ref: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="name")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_non_empty(value, field_name="description")

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="artifact_type")

    @model_validator(mode="after")
    def _validate_output_shape(self) -> "StepOutputDefinition":
        if self.kind == "artifact":
            if self.artifact_type is None or self.schema_ref is None:
                raise ValueError("Artifact outputs require artifact_type and schema_ref.")
            _validate_artifact_schema_ref(
                self.schema_ref,
                field_name="schema_ref",
                artifact_type=self.artifact_type,
            )
        elif any(value is not None for value in (self.artifact_type, self.schema_ref)):
            raise ValueError("Value outputs may not define artifact_type or schema_ref.")
        return self


class WorkflowOutputSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    output_name: str

    @field_validator("step_id", "output_name")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)


class WorkflowOutputDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: OutputKind
    description: str
    source: WorkflowOutputSource
    artifact_type: str | None = None
    schema_ref: str | None = None
    report_template_path: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="name")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _require_non_empty(value, field_name="description")

    @field_validator("artifact_type")
    @classmethod
    def _validate_artifact_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name="artifact_type")

    @field_validator("report_template_path")
    @classmethod
    def _validate_report_template_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_relative_path(value, field_name="report_template_path")

    @model_validator(mode="after")
    def _validate_output_contract(self) -> "WorkflowOutputDefinition":
        if self.kind == "artifact":
            if self.artifact_type is None or self.schema_ref is None:
                raise ValueError("Artifact workflow outputs require artifact_type and schema_ref.")
            _validate_artifact_schema_ref(
                self.schema_ref,
                field_name="schema_ref",
                artifact_type=self.artifact_type,
            )
        elif any(value is not None for value in (self.artifact_type, self.schema_ref, self.report_template_path)):
            raise ValueError(
                "Value workflow outputs may not define artifact_type, schema_ref, or report_template_path."
            )
        return self


class StepInputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: BindingSource

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="name")


class WorkflowStepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    executor: StepExecutor
    inputs: list[StepInputBinding] = Field(default_factory=list)
    outputs: list[StepOutputDefinition] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    failure_policy: StepFailurePolicy

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="label")

    @field_validator("prerequisites")
    @classmethod
    def _validate_prerequisites(cls, value: list[str]) -> list[str]:
        return [_require_normalized_identifier(item, field_name="prerequisite") for item in value]

    @model_validator(mode="after")
    def _validate_unique_names(self) -> "WorkflowStepDefinition":
        output_names = [item.name for item in self.outputs]
        if len(output_names) != len(set(output_names)):
            raise ValueError(f"Step {self.id!r} defines duplicate output names.")

        input_names = [item.name for item in self.inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError(f"Step {self.id!r} defines duplicate input binding names.")

        if len(self.prerequisites) != len(set(self.prerequisites)):
            raise ValueError(f"Step {self.id!r} defines duplicate prerequisites.")
        return self


class QCGateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    when: WorkflowQCGateStage
    target: BindingSource
    failure_policy: QCGateFailurePolicy
    policy: QCPolicyDefinition | None = None
    description: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _require_normalized_identifier(value, field_name="id")

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _require_non_empty(value, field_name="label")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="description")

    @model_validator(mode="after")
    def _validate_target_shape(self) -> "QCGateDefinition":
        if isinstance(self.target, LiteralBindingSource):
            raise ValueError("QC gates must target a workflow input or step output, not a literal.")
        if self.when == "before_execution" and not isinstance(self.target, WorkflowInputSource):
            raise ValueError("before_execution QC gates must target workflow inputs.")
        if self.when == "after_step" and not isinstance(self.target, StepOutputSource):
            raise ValueError("after_step QC gates must target step outputs.")
        return self


class ComplianceHookDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    stage: ComplianceHookStage
    tool: str
    required: bool = True
    inputs: list[StepInputBinding] = Field(default_factory=list)
    step_id: str | None = None
    description: str | None = None

    @field_validator("id", "tool", "step_id")
    @classmethod
    def _validate_identifiers(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, field_name="description")

    @model_validator(mode="after")
    def _validate_stage(self) -> "ComplianceHookDefinition":
        if self.stage in {"before_step", "after_step"} and self.step_id is None:
            raise ValueError(f"{self.stage} compliance hooks require step_id.")
        if self.stage in {"before_execution", "before_publish"} and self.step_id is not None:
            raise ValueError(f"{self.stage} compliance hooks may not define step_id.")
        input_names = [item.name for item in self.inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError("Compliance hooks may not define duplicate input binding names.")
        return self


class WorkflowSpecDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=WORKFLOW_SPEC_VERSION)
    kind: Literal["workflow_spec"] = "workflow_spec"
    workflow_id: str
    version: str
    name: str
    purpose: str
    engine: str
    required_inputs: list[WorkflowInputDefinition] = Field(min_length=1)
    optional_inputs: list[WorkflowInputDefinition] = Field(default_factory=list)
    runtime: WorkflowRuntimeContract
    outputs: list[WorkflowOutputDefinition] = Field(min_length=1)
    qc_gates: list[QCGateDefinition] = Field(default_factory=list)
    compliance_hooks: list[ComplianceHookDefinition] = Field(default_factory=list)
    steps: list[WorkflowStepDefinition] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        cleaned = _validate_semver(value, field_name="schema_version")
        if cleaned != WORKFLOW_SPEC_VERSION:
            raise ValueError(
                f"Unsupported workflow spec schema_version {cleaned!r}; expected {WORKFLOW_SPEC_VERSION!r}."
            )
        return cleaned

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return _validate_semver(value, field_name="version")

    @field_validator("workflow_id", "engine")
    @classmethod
    def _validate_identifiers(cls, value: str, info) -> str:
        return _require_normalized_identifier(value, field_name=info.field_name)

    @field_validator("name", "purpose")
    @classmethod
    def _validate_text(cls, value: str, info) -> str:
        return _require_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_graph_and_contracts(self) -> "WorkflowSpecDocument":
        input_defs = self.required_inputs + self.optional_inputs
        input_names = [item.name for item in input_defs]
        if len(input_names) != len(set(input_names)):
            raise ValueError("Workflow specs may not define duplicate input names.")

        output_names = [item.name for item in self.outputs]
        if len(output_names) != len(set(output_names)):
            raise ValueError("Workflow specs may not define duplicate output names.")

        qc_gate_ids = [item.id for item in self.qc_gates]
        if len(qc_gate_ids) != len(set(qc_gate_ids)):
            raise ValueError("Workflow specs may not define duplicate QC gate ids.")

        hook_ids = [item.id for item in self.compliance_hooks]
        if len(hook_ids) != len(set(hook_ids)):
            raise ValueError("Workflow specs may not define duplicate compliance hook ids.")

        inputs_by_name = {item.name: item for item in input_defs}
        required_input_names = {item.name for item in self.required_inputs}
        provided_inputs = set(self.runtime.provided_inputs)
        missing_runtime_inputs = sorted(required_input_names - provided_inputs)
        if missing_runtime_inputs:
            raise ValueError(
                "runtime.provided_inputs must include all required inputs; missing "
                + ", ".join(missing_runtime_inputs)
                + "."
            )

        unknown_runtime_inputs = sorted(provided_inputs - set(inputs_by_name))
        if unknown_runtime_inputs:
            raise ValueError(
                "runtime.provided_inputs references undefined inputs: "
                + ", ".join(unknown_runtime_inputs)
                + "."
            )

        parameter_inputs = {
            item.name
            for item in input_defs
            if item.kind == "parameter"
        }
        invalid_overrides = sorted(
            set(self.runtime.allowed_parameter_overrides) - parameter_inputs
        )
        if invalid_overrides:
            raise ValueError(
                "runtime.allowed_parameter_overrides may only reference parameter inputs: "
                + ", ".join(invalid_overrides)
                + "."
            )

        steps_by_id: dict[str, WorkflowStepDefinition] = {}
        for step in self.steps:
            if step.id in steps_by_id:
                raise ValueError(f"Workflow specs may not define duplicate step ids: {step.id!r}.")
            steps_by_id[step.id] = step

        outputs_by_step = {
            step.id: {output.name: output for output in step.outputs}
            for step in self.steps
        }

        self._validate_acyclic_graph(steps_by_id)

        for step in self.steps:
            for prerequisite in step.prerequisites:
                if prerequisite not in steps_by_id:
                    raise ValueError(
                        f"Step {step.id!r} references undefined prerequisite {prerequisite!r}."
                    )

            for binding in step.inputs:
                self._validate_binding_source(
                    binding.source,
                    inputs_by_name=inputs_by_name,
                    steps_by_id=steps_by_id,
                    outputs_by_step=outputs_by_step,
                    current_step=step,
                )

        for gate in self.qc_gates:
            self._validate_binding_source(
                gate.target,
                inputs_by_name=inputs_by_name,
                steps_by_id=steps_by_id,
                outputs_by_step=outputs_by_step,
                current_step=None,
            )

        for hook in self.compliance_hooks:
            if hook.step_id is not None and hook.step_id not in steps_by_id:
                raise ValueError(
                    f"Compliance hook {hook.id!r} references undefined step {hook.step_id!r}."
                )
            for binding in hook.inputs:
                if hook.stage == "before_execution":
                    if not isinstance(binding.source, WorkflowInputSource):
                        raise ValueError(
                            f"Compliance hook {hook.id!r} at stage 'before_execution' may only consume workflow inputs."
                        )
                    self._validate_binding_source(
                        binding.source,
                        inputs_by_name=inputs_by_name,
                        steps_by_id=steps_by_id,
                        outputs_by_step=outputs_by_step,
                        current_step=None,
                    )
                elif hook.stage == "before_step":
                    self._validate_binding_source(
                        binding.source,
                        inputs_by_name=inputs_by_name,
                        steps_by_id=steps_by_id,
                        outputs_by_step=outputs_by_step,
                        current_step=steps_by_id[hook.step_id],
                    )
                elif hook.stage == "after_step":
                    self._validate_binding_source(
                        binding.source,
                        inputs_by_name=inputs_by_name,
                        steps_by_id=steps_by_id,
                        outputs_by_step=outputs_by_step,
                        current_step=steps_by_id[hook.step_id],
                        allow_current_step_output=True,
                    )
                else:
                    self._validate_binding_source(
                        binding.source,
                        inputs_by_name=inputs_by_name,
                        steps_by_id=steps_by_id,
                        outputs_by_step=outputs_by_step,
                        current_step=None,
                    )

        for output in self.outputs:
            source_step = steps_by_id.get(output.source.step_id)
            if source_step is None:
                raise ValueError(
                    f"Workflow output {output.name!r} references undefined step {output.source.step_id!r}."
                )
            source_output = outputs_by_step[output.source.step_id].get(output.source.output_name)
            if source_output is None:
                raise ValueError(
                    f"Workflow output {output.name!r} references undeclared step output "
                    f"{output.source.step_id!r}.{output.source.output_name!r}."
                )
            if output.kind != source_output.kind:
                raise ValueError(
                    f"Workflow output {output.name!r} must match source output kind "
                    f"from {output.source.step_id!r}.{output.source.output_name!r}."
                )
            if output.kind == "artifact" and output.artifact_type != source_output.artifact_type:
                raise ValueError(
                    f"Workflow output {output.name!r} must use the same artifact_type as its source step output."
                )

        return self

    @staticmethod
    def _validate_acyclic_graph(steps_by_id: dict[str, WorkflowStepDefinition]) -> None:
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visited:
                return
            if step_id in visiting:
                raise ValueError(
                    f"Workflow step prerequisites contain a cycle involving {step_id!r}."
                )
            visiting.add(step_id)
            step = steps_by_id[step_id]
            for prerequisite in step.prerequisites:
                if prerequisite in steps_by_id:
                    visit(prerequisite)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in steps_by_id:
            visit(step_id)

    @staticmethod
    def _validate_binding_source(
        source: BindingSource,
        *,
        inputs_by_name: dict[str, WorkflowInputDefinition],
        steps_by_id: dict[str, WorkflowStepDefinition],
        outputs_by_step: dict[str, dict[str, StepOutputDefinition]],
        current_step: WorkflowStepDefinition | None,
        allow_current_step_output: bool = False,
    ) -> None:
        if isinstance(source, WorkflowInputSource):
            if source.input_name not in inputs_by_name:
                raise ValueError(
                    f"Workflow binding references undefined input {source.input_name!r}."
                )
            return

        if isinstance(source, StepOutputSource):
            if source.step_id not in steps_by_id:
                raise ValueError(
                    f"Workflow binding references undefined step {source.step_id!r}."
                )
            if source.output_name not in outputs_by_step[source.step_id]:
                raise ValueError(
                    f"Workflow binding references undeclared step output "
                    f"{source.step_id!r}.{source.output_name!r}."
                )
            if current_step is not None:
                if source.step_id == current_step.id:
                    if not allow_current_step_output:
                        raise ValueError(
                            f"Step {current_step.id!r} may not consume its own output {source.output_name!r} as an input."
                        )
                elif source.step_id not in current_step.prerequisites:
                    raise ValueError(
                        f"Step {current_step.id!r} consumes output {source.step_id!r}.{source.output_name!r} "
                        "without declaring that step as a prerequisite."
                    )
            return


WorkflowSpec = WorkflowSpecDocument


def validate_workflow_spec_payload(payload: dict[str, Any]) -> WorkflowSpec:
    if payload.get("kind") != "workflow_spec":
        raise ValueError("Workflow spec payload must include kind 'workflow_spec'.")
    return WorkflowSpecDocument.model_validate(payload)


def load_workflow_spec(path: str | Path) -> WorkflowSpec:
    workflow_path = Path(path)
    raw_text = workflow_path.read_text(encoding="utf-8")

    if workflow_path.suffix == ".json":
        payload = json.loads(raw_text)
    elif workflow_path.suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_text)
    else:
        raise ValueError(f"Unsupported workflow spec extension: {workflow_path.suffix!r}")

    if not isinstance(payload, dict):
        raise ValueError("Workflow spec documents must deserialize to a mapping.")

    return validate_workflow_spec_payload(payload)
