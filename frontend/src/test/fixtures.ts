import type {
  AccessProbeResponse,
  ArtifactRegistryRecord,
  ComplianceReportArtifact,
  FilesWorkspaceItem,
  JsonValue,
  Session,
  SessionHistoryMessage,
  SkillRegistryEntry,
  TokenStats,
  ToolResultEnvelope,
  WorkflowArtifactEvent,
  WorkflowDoneEvent,
  WorkflowStartEvent,
  WorkflowStepEndEvent,
  WorkflowStepStartEvent,
} from "@/lib/types";

export function makeAccessProbe(
  scope: AccessProbeResponse["scope"],
  authorizationMode: AccessProbeResponse["authorization_mode"] = "loopback"
): AccessProbeResponse {
  return {
    scope,
    authorization_mode: authorizationMode,
  };
}

export function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: "session-alpha",
    title: "Alpha session",
    updated_at: Date.parse("2026-03-24T18:00:00Z"),
    message_count: 2,
    ...overrides,
  };
}

export function makeComplianceReport(
  overrides: Partial<ComplianceReportArtifact> = {}
): ComplianceReportArtifact {
  return {
    artifact_type: "compliance_report",
    id: "compliance-1",
    run_id: "run-rnaseq-1",
    created_at: "2026-03-24T18:00:00Z",
    risk_category: "biosafety_review",
    request_context: {
      user_message: "Run the RNA-seq QC and DE workflow.",
      attached_identifiers: [],
      selected_workflow: "rnaseq_qc_de",
      session_id: "session-alpha",
    },
    triggered_rules: [
      {
        rule_id: "rna-human-review",
        category: "human_subjects",
        trigger_text: "RNA-seq patient cohort",
        severity: "medium",
        recommended_action: "allow_with_warning",
      },
    ],
    runtime_state: "warning_issued",
    decision_source: "preflight_rule_engine",
    preflight_disposition: "allow_with_warning",
    block_status: "not_blocked",
    human_approval_required: false,
    approval_scope: null,
    approval: null,
    final_disposition: "allow_with_warning",
    ...overrides,
  };
}

export function makeToolResultEnvelope(
  report: ComplianceReportArtifact,
  overrides: Partial<ToolResultEnvelope> = {}
): ToolResultEnvelope {
  return {
    contract_version: "tool_result.v1",
    tool_name: "compliance_preflight",
    summary: "Compliance review completed.",
    structured_payload: {
      audit_log_path: "audit/compliance/latest.jsonl",
      report,
    } as unknown as JsonValue,
    artifact_refs: [
      {
        artifact_type: "compliance_report",
        path: "artifacts/compliance/report.json",
        identifier: report.id,
      },
    ],
    warnings:
      report.final_disposition === "block"
        ? ["blocked_by_compliance"]
        : report.final_disposition === "require_approval"
          ? ["approval_required"]
          : report.final_disposition === "allow_with_warning"
            ? ["compliance_warning"]
            : [],
    status: "success",
    outcome: "success",
    metadata: {},
    source_payload: null,
    ...overrides,
  };
}

export function makeWorkflowStartEvent(
  overrides: Partial<WorkflowStartEvent> = {}
): WorkflowStartEvent {
  return {
    contract_version: "workflow_event.v1",
    type: "workflow_start",
    run_id: "run-rnaseq-1",
    workflow_id: "rnaseq_qc_de",
    workflow_name: "RNA-seq QC + DE",
    lifecycle_status: "running",
    resumed: false,
    run_record_path: "artifacts/workflows/run-rnaseq-1/run.json",
    total_steps: 2,
    steps: [
      {
        step_id: "qc",
        step_label: "Quality control",
        prerequisite_step_ids: [],
        executor_type: "tool",
      },
      {
        step_id: "de",
        step_label: "Differential expression",
        prerequisite_step_ids: ["qc"],
        executor_type: "tool",
      },
    ],
    started_at: "2026-03-24T18:00:00Z",
    ...overrides,
  };
}

export function makeWorkflowStepStartEvent(
  overrides: Partial<WorkflowStepStartEvent> = {}
): WorkflowStepStartEvent {
  return {
    contract_version: "workflow_event.v1",
    type: "workflow_step_start",
    run_id: "run-rnaseq-1",
    workflow_id: "rnaseq_qc_de",
    step_id: "qc",
    step_label: "Quality control",
    status: "running",
    executor_type: "tool",
    prerequisite_step_ids: [],
    started_at: "2026-03-24T18:00:01Z",
    ...overrides,
  };
}

export function makeWorkflowStepEndEvent(
  overrides: Partial<WorkflowStepEndEvent> = {}
): WorkflowStepEndEvent {
  return {
    contract_version: "workflow_event.v1",
    type: "workflow_step_end",
    run_id: "run-rnaseq-1",
    workflow_id: "rnaseq_qc_de",
    step_id: "qc",
    step_label: "Quality control",
    status: "completed",
    artifact_refs: [
      {
        artifact_type: "qa_report",
        path: "artifacts/reports/qc-summary.md",
        run_id: "run-rnaseq-1",
      },
    ],
    warnings: [],
    warning_details: [],
    errors: [],
    error_details: [],
    started_at: "2026-03-24T18:00:01Z",
    ended_at: "2026-03-24T18:00:15Z",
    duration_seconds: 14,
    ...overrides,
  };
}

export function makeWorkflowArtifactEvent(
  overrides: Partial<WorkflowArtifactEvent> = {}
): WorkflowArtifactEvent {
  return {
    contract_version: "workflow_event.v1",
    type: "workflow_artifact",
    run_id: "run-rnaseq-1",
    workflow_id: "rnaseq_qc_de",
    artifact: {
      artifact_type: "qa_report",
      path: "artifacts/reports/qc-summary.md",
      run_id: "run-rnaseq-1",
    },
    scope: "workflow_output",
    step_id: "qc",
    step_label: "Quality control",
    output_name: "qc_summary",
    ...overrides,
  };
}

export function makeWorkflowDoneEvent(
  overrides: Partial<WorkflowDoneEvent> = {}
): WorkflowDoneEvent {
  return {
    contract_version: "workflow_event.v1",
    type: "workflow_done",
    run_id: "run-rnaseq-1",
    workflow_id: "rnaseq_qc_de",
    lifecycle_status: "completed",
    run_record_path: "artifacts/workflows/run-rnaseq-1/run.json",
    completed_steps: 2,
    total_steps: 2,
    warning_count: 1,
    started_at: "2026-03-24T18:00:00Z",
    ended_at: "2026-03-24T18:05:00Z",
    duration_seconds: 300,
    blocked_reason: null,
    blocked_issue_details: [],
    ...overrides,
  };
}

export function makeHistoryMessage(
  overrides: Partial<SessionHistoryMessage> = {}
): SessionHistoryMessage {
  return {
    role: "assistant",
    content: "BioAPEX loaded the saved session.",
    request_id: "request-history-1",
    tool_calls: [],
    workflow_events: [],
    retrievals: [],
    ...overrides,
  };
}

export function makeFilesWorkspaceItem(
  overrides: Partial<FilesWorkspaceItem> = {}
): FilesWorkspaceItem {
  return {
    path: "artifacts/reports/qc-summary.md",
    name: "qc-summary.md",
    artifact_type: "qa_report",
    workflow: "rnaseq_qc_de",
    run_id: "run-rnaseq-1",
    source_tool: "qc_reporter",
    step_label: "Quality control",
    output_name: "qc_summary",
    size_bytes: 1024,
    materialized_at: Date.parse("2026-03-24T18:05:00Z"),
    ...overrides,
  };
}

export function makeArtifactRegistryRecord(
  overrides: Partial<ArtifactRegistryRecord> = {}
): ArtifactRegistryRecord {
  return {
    artifact_id: "artifact-1",
    declared_id: "artifact-1",
    artifact_type: "qa_report",
    path: "artifacts/reports/qc-summary.md",
    hash: "sha256:test",
    created_at: "2026-03-24T18:05:00Z",
    run_id: "run-rnaseq-1",
    workflow: "rnaseq_qc_de",
    date: "2026-03-24",
    source_workflow: "rnaseq_qc_de",
    source_tool: "qc_reporter",
    dataset_id: "dataset-alpha",
    status: "valid",
    error: null,
    indexed_at: "2026-03-24T18:06:00Z",
    ...overrides,
  };
}

export function makeSkillRegistryEntry(
  overrides: Partial<SkillRegistryEntry> = {}
): SkillRegistryEntry {
  return {
    name: "feature",
    description: "Manage the BioAPEX current-feature workflow from scoping through review and completion",
    location: "/gpfs/projects/hrbomics/miniAgent/.codex/skills/feature/SKILL.md",
    source_path: "/gpfs/projects/hrbomics/miniAgent/.codex/skills/feature/SKILL.md",
    category: "workflow",
    version: "1.0.0",
    tags: ["feature", "workflow"],
    aliases: [],
    requires_tools: [],
    requires_network: false,
    user_invocable: true,
    species: "general",
    modality: "text",
    stage: "production",
    stability: "stable",
    safety_level: "standard",
    enabled: true,
    ...overrides,
  };
}

export function makeTokenStats(
  overrides: Partial<TokenStats> = {}
): TokenStats {
  return {
    session_id: "session-alpha",
    system_tokens: 240,
    message_tokens: 880,
    total_tokens: 1120,
    input_tokens: 620,
    output_tokens: 340,
    tool_tokens: 160,
    tracked_total_tokens: 1120,
    context_window_tokens: 8000,
    context_window_remaining_tokens: 6880,
    model_name: "gpt-5.4",
    tokenizer_backend: "tiktoken_cl100k_base",
    tokenizer_accuracy: "model_aligned",
    ...overrides,
  };
}
