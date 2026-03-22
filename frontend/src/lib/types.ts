export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface ToolArtifactRef {
  path?: string | null;
  label?: string | null;
  artifact_type?: string | null;
  identifier?: string | null;
}

export interface ToolResultError {
  code:
    | "blocked"
    | "invalid_input"
    | "retriable_failure"
    | "execution_failure";
  message: string;
  retriable: boolean;
}

export interface ToolResultEnvelope {
  contract_version: string;
  tool_name: string;
  summary: string;
  structured_payload?: JsonValue;
  artifact_refs: ToolArtifactRef[];
  warnings: string[];
  status: "success" | "error";
  outcome:
    | "success"
    | "success_empty"
    | "blocked"
    | "invalid_input"
    | "retriable_failure"
    | "execution_failure";
  error?: ToolResultError | null;
  metadata: { [key: string]: JsonValue };
  source_payload?: JsonValue;
}

export type ConfidenceLevel = "low" | "medium" | "high";

export type EvidenceReviewStatus =
  | "supported"
  | "mixed"
  | "insufficient_evidence";

export interface EvidenceArtifactReference {
  artifact_type: string;
  path: string;
  id?: string | null;
  run_id?: string | null;
}

export interface EvidenceRetrievalCardSummary {
  pmid: string;
  title: string;
  stable_identifier: string;
  study_type?: string | null;
  artifact_path: string;
  cached_raw_payload_path?: string | null;
  retrieval_context_path?: string | null;
  esearch_payload_path?: string | null;
  esummary_payload_path?: string | null;
  run_id?: string | null;
  claim_count: number;
  limitation_count: number;
  entity_tags?: JsonValue;
  grounded_entities?: JsonValue;
  grounding_results?: JsonValue;
  grounding_requires_clarification: boolean;
  entity_grounding_path?: string | null;
}

export interface EvidenceRetrievalFailure {
  pmid: string;
  error: string;
}

export interface EvidenceRetrievalPayload {
  query?: string | null;
  candidate_records: JsonValue[];
  selected_pmids: string[];
  retrieval_context_run_id?: string | null;
  retrieval_context_path?: string | null;
  esearch_payload_path?: string | null;
  esummary_payload_path?: string | null;
  cards: EvidenceRetrievalCardSummary[];
  failures: EvidenceRetrievalFailure[];
}

export interface EvidenceReviewExcludedEvidence {
  evidence_id: string;
  artifact?: EvidenceArtifactReference | null;
  reason: string;
}

export interface EvidenceReviewSourceFact {
  statement: string;
  claim_id?: string | null;
  stable_identifier?: string | null;
  evidence?: EvidenceArtifactReference | null;
  confidence?: ConfidenceLevel | null;
}

export interface EvidenceReviewConclusion {
  statement: string;
  support_status?: EvidenceReviewStatus | null;
  confidence?: ConfidenceLevel | null;
  supporting_evidence: EvidenceArtifactReference[];
  limitation_notes: string[];
  conflict_notes: string[];
}

export interface EvidenceReviewPayload {
  question?: string | null;
  review_status?: EvidenceReviewStatus | null;
  confidence?: ConfidenceLevel | null;
  unsupported_claims_present?: boolean;
  artifact_path?: string | null;
  evidence_included: EvidenceArtifactReference[];
  evidence_excluded: EvidenceReviewExcludedEvidence[];
  limitations: string[];
  unresolved_conflicts: string[];
  source_facts: EvidenceReviewSourceFact[];
  synthesized_conclusions: EvidenceReviewConclusion[];
  requires_review?: boolean;
  reasons: string[];
}

export type ComplianceDisposition =
  | "allow"
  | "allow_with_warning"
  | "require_approval"
  | "block";

export type ComplianceRuntimeState =
  | "preflight_pending"
  | "allowed"
  | "warning_issued"
  | "blocked"
  | "approval_required"
  | "approved_override";

export type ComplianceApprovalScope = "message" | "workflow" | "run";

export interface ComplianceRequestContext {
  user_message: string;
  attached_identifiers: string[];
  selected_workflow?: string | null;
  session_id?: string | null;
}

export interface ComplianceApprovalRecord {
  approved_by: string;
  approval_scope: ComplianceApprovalScope;
  approved_at: string;
  override_for_disposition: ComplianceDisposition;
  rationale?: string | null;
}

export interface ComplianceReportArtifact {
  artifact_type: "compliance_report";
  id: string;
  run_id: string;
  created_at: string;
  risk_category: string;
  request_context: ComplianceRequestContext;
  triggered_rules: Array<{
    rule_id: string;
    category: string;
    trigger_text: string;
    severity: string;
    recommended_action: ComplianceDisposition;
  }>;
  runtime_state: ComplianceRuntimeState;
  decision_source: string;
  preflight_disposition: ComplianceDisposition;
  block_status: "blocked" | "not_blocked";
  human_approval_required: boolean;
  approval_scope?: ComplianceApprovalScope | null;
  approval?: ComplianceApprovalRecord | null;
  final_disposition: ComplianceDisposition;
}

export type WorkflowLifecycleStatus =
  | "created"
  | "preflight_checked"
  | "running"
  | "waiting"
  | "failed"
  | "completed"
  | "blocked";

export type WorkflowStepStatus =
  | "created"
  | "waiting"
  | "running"
  | "failed"
  | "completed"
  | "blocked";

export type WorkflowBlockingSource =
  | "qc_gate"
  | "compliance_hook"
  | "step_failure"
  | "qa_review"
  | "input_validation"
  | "unknown";

export type WorkflowBlockStage =
  | "before_execution"
  | "before_step"
  | "after_step"
  | "before_publish";

export type WorkflowArtifactScope =
  | "run_record"
  | "step_output"
  | "workflow_output"
  | "related_artifact";

export interface WorkflowArtifactRef {
  artifact_type: string;
  path: string;
  id?: string | null;
  run_id?: string | null;
}

export interface WorkflowIssueDetail {
  code: string;
  message: string;
  field_path?: string | null;
  path?: string | null;
}

export interface WorkflowEventBase {
  contract_version: "workflow_event.v1";
  run_id: string;
  workflow_id: string;
  request_id?: string;
}

export interface WorkflowStepDescriptor {
  step_id: string;
  step_label: string;
  prerequisite_step_ids: string[];
  executor_type: string;
  engine_name?: string | null;
  status?: WorkflowStepStatus | null;
  artifact_refs?: WorkflowArtifactRef[];
  warnings?: string[];
  warning_details?: WorkflowIssueDetail[];
  errors?: string[];
  error_details?: WorkflowIssueDetail[];
  started_at?: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
}

export interface WorkflowStartEvent extends WorkflowEventBase {
  type: "workflow_start";
  workflow_name: string;
  lifecycle_status: WorkflowLifecycleStatus;
  resumed: boolean;
  run_record_path: string;
  total_steps?: number | null;
  steps?: WorkflowStepDescriptor[];
  started_at?: string | null;
}

export interface WorkflowStepStartEvent extends WorkflowEventBase {
  type: "workflow_step_start";
  step_id: string;
  step_label: string;
  status: "running";
  executor_type: string;
  prerequisite_step_ids: string[];
  engine_name?: string | null;
  started_at?: string | null;
}

export interface WorkflowStepEndEvent extends WorkflowEventBase {
  type: "workflow_step_end";
  step_id: string;
  step_label: string;
  status: Extract<WorkflowStepStatus, "waiting" | "completed" | "failed" | "blocked">;
  artifact_refs: WorkflowArtifactRef[];
  warnings: string[];
  warning_details: WorkflowIssueDetail[];
  errors: string[];
  error_details: WorkflowIssueDetail[];
  started_at?: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
}

export interface WorkflowBlockedEvent extends WorkflowEventBase {
  type: "workflow_blocked";
  lifecycle_status: "blocked";
  reason: string;
  issue_details: WorkflowIssueDetail[];
  stage: WorkflowBlockStage;
  blocking_source: WorkflowBlockingSource;
  step_id?: string | null;
  step_label?: string | null;
}

export interface WorkflowArtifactEvent extends WorkflowEventBase {
  type: "workflow_artifact";
  artifact: WorkflowArtifactRef;
  scope: WorkflowArtifactScope;
  step_id?: string | null;
  step_label?: string | null;
  output_name?: string | null;
}

export interface WorkflowDoneEvent extends WorkflowEventBase {
  type: "workflow_done";
  lifecycle_status: WorkflowLifecycleStatus;
  run_record_path: string;
  completed_steps: number;
  total_steps: number;
  warning_count: number;
  started_at?: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
  blocked_reason?: string | null;
  blocked_issue_details?: WorkflowIssueDetail[];
}

export type WorkflowStreamEvent =
  | WorkflowStartEvent
  | WorkflowStepStartEvent
  | WorkflowStepEndEvent
  | WorkflowBlockedEvent
  | WorkflowArtifactEvent
  | WorkflowDoneEvent;

export interface ToolCall {
  tool: string;
  input: string;
  output: string;
  run_id?: string;
  result?: ToolResultEnvelope;
}

export interface RetrievalResult {
  text: string;
  score: number;
  source: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  request_id?: string;
  tool_calls?: ToolCall[];
  workflow_events?: WorkflowStreamEvent[];
  retrievals?: RetrievalResult[];
  isStreaming?: boolean;
  /** Tool currently executing (cleared when tool_end arrives) */
  pendingTool?: { tool: string; input: string; runId: string };
}

export type WorkspaceMode = "sessions" | "flows" | "docs" | "files";

export interface Session {
  id: string;
  title: string;
  updated_at: number;
  message_count: number;
}

export type FlowsWorkspaceStatus = "active" | "idle" | "blocked" | "failed";

export interface FlowsWorkspaceSummaryItem {
  id: string;
  run_count: number;
  last_activity_at: number | null;
  status: FlowsWorkspaceStatus;
}

export interface FlowsWorkspaceSummaryResponse {
  items: FlowsWorkspaceSummaryItem[];
}

export interface TokenStats {
  session_id: string;
  system_tokens: number;
  message_tokens: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  tool_tokens: number;
  tracked_total_tokens: number;
  context_window_tokens: number | null;
  context_window_remaining_tokens: number | null;
  model_name: string;
}

export interface Skill {
  name: string;
  path: string;
  category?: string;
  stage?: string;
}

export interface SkillRegistryEntry {
  name: string;
  description: string;
  location: string;
  source_path: string;
  category: string;
  version: string;
  tags: string[];
  aliases: string[];
  requires_tools: string[];
  requires_network: boolean;
  user_invocable: boolean;
  species: string;
  modality: string;
  stage: string;
  stability: string;
  safety_level: string;
  enabled: boolean;
}
