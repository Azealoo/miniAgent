import { deriveMessageBlocks } from "@/lib/message-blocks";
import type {
  AccessProbeResponse,
  ComplianceReportArtifact,
  FilesWorkspaceItem,
  JsonValue,
  Session,
  SessionContinuitySummary,
  SessionHistoryMessage,
  SkillRegistryEntry,
  TokenStats,
  ToolResultEnvelope,
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

export function makeGenericToolResultEnvelope(
  overrides: Partial<ToolResultEnvelope> = {}
): ToolResultEnvelope {
  return {
    contract_version: "tool_result.v1",
    tool_name: "read_file",
    summary: "Read knowledge/study_protocol.md.",
    structured_payload: {
      path: "knowledge/study_protocol.md",
      content_preview: "Protocol guidance for the active RNA-seq cohort.",
    } as unknown as JsonValue,
    artifact_refs: [
      {
        artifact_type: "file",
        path: "knowledge/study_protocol.md",
        label: "study_protocol.md",
      },
    ],
    warnings: [],
    status: "success",
    outcome: "success",
    error: null,
    metadata: {},
    source_payload: null,
    ...overrides,
  };
}

export function makeHistoryMessage(
  overrides: Partial<SessionHistoryMessage> = {}
): SessionHistoryMessage {
  const message: SessionHistoryMessage = {
    role: "assistant",
    content: "BioAPEX loaded the saved session.",
    request_id: "request-history-1",
    tool_calls: [],
    retrievals: [],
    ...overrides,
  };

  if (!("blocks" in overrides)) {
    message.blocks = deriveMessageBlocks(message);
  }

  return message;
}

export function makeSessionContinuitySummary(
  overrides: Partial<SessionContinuitySummary> = {}
): SessionContinuitySummary {
  return {
    source_format: "structured",
    legacy_summary: null,
    decisions_and_rationale: ["Reviewed earlier RNA-seq QC and evidence synthesis work."],
    results_register: ["Generated qc-summary.md and compliance-report.json."],
    evidence_register: ["PMID:41910001 linked to the archived claim set."],
    compliance_register: ["Approval was required before publication."],
    open_questions_and_next_actions: ["Re-open the archived results before exporting."],
    archive_id: "1712012234",
    archived_message_count: 4,
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
    run_id: "run-rnaseq-1",
    source_tool: "qc_reporter",
    step_label: "Quality control",
    output_name: "qc_summary",
    size_bytes: 1024,
    materialized_at: Date.parse("2026-03-24T18:05:00Z"),
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
