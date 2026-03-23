export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface JsonObject {
  [key: string]: JsonValue;
}

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
  metadata: JsonObject;
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

export type SourcesInspectorCitationTone =
  | "supported"
  | "mixed"
  | "insufficient"
  | "retrieved"
  | "warning"
  | "neutral";

export interface SourcesInspectorCitation {
  id: string;
  title: string;
  identifier: string | null;
  source_type: string;
  support_percent: number | null;
  tone: SourcesInspectorCitationTone;
  detail: string | null;
  path: string | null;
  last_seen_order: number;
}

export type SourcesInspectorChecklistState =
  | "complete"
  | "warning"
  | "blocked"
  | "pending";

export interface SourcesInspectorChecklistItem {
  id: string;
  label: string;
  state: SourcesInspectorChecklistState;
  detail: string | null;
}

export interface SourcesInspectorComplianceCard {
  summary_label: string | null;
  detail: string | null;
  state: SourcesInspectorChecklistState;
  items: SourcesInspectorChecklistItem[];
  report: ComplianceReportArtifact | null;
  audit_log_path: string | null;
}

export interface SourcesInspectorSummary {
  scoped_message_count: number;
  citations: SourcesInspectorCitation[];
  compliance: SourcesInspectorComplianceCard;
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

export interface SessionHistoryMessage {
  role: string;
  content: string;
  request_id?: string;
  tool_calls?: ToolCall[];
  workflow_events?: WorkflowStreamEvent[];
  retrievals?: RetrievalResult[];
}

export type WorkspaceMode =
  | "sessions"
  | "flows"
  | "docs"
  | "files"
  | "ops"
  | "artifacts";

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

export interface FilesWorkspaceItem {
  path: string;
  name: string;
  artifact_type: string | null;
  workflow: string | null;
  run_id: string | null;
  source_tool: string | null;
  step_label: string | null;
  output_name: string | null;
  size_bytes: number | null;
  materialized_at: number | null;
}

export interface FilesWorkspaceSummaryResponse {
  items: FilesWorkspaceItem[];
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

export interface FileContentsResponse {
  path: string;
  content: string;
}

export interface FileSaveResponse {
  path: string;
  saved: boolean;
}

export interface RawFileTextResponse {
  path: string;
  contentType: string | null;
  content: string;
}

export interface SessionTitleResponse {
  session_id: string;
  title: string;
}

export interface SessionCompressionResponse {
  archived_count: number;
  remaining_count: number;
  summary: string;
}

export interface RagModeResponse {
  rag_mode: boolean;
}

export interface RetentionPolicy {
  rotation_strategy: string;
  retention_expectation_days: number;
  automatic_deletion: boolean;
}

export interface ArtifactRegistryRecord {
  artifact_id: string;
  declared_id?: string | null;
  artifact_type: string;
  path: string;
  hash?: string | null;
  created_at?: string | null;
  run_id: string;
  workflow: string;
  date: string;
  source_workflow?: string | null;
  source_tool?: string | null;
  dataset_id?: string | null;
  status: "valid" | "invalid";
  error?: string | null;
  indexed_at: string;
}

export interface ArtifactRegistrySnapshot {
  schema_version: string;
  generated_at: string;
  artifact_root: string;
  registry_path: string;
  record_count: number;
  valid_count: number;
  invalid_count: number;
  records: ArtifactRegistryRecord[];
}

export interface ArtifactRegistryLookupResult {
  generated_at: string;
  artifact_root: string;
  registry_path: string;
  total_count: number;
  matched_count: number;
  valid_count: number;
  invalid_count: number;
  records: ArtifactRegistryRecord[];
}

export interface ArtifactRegistryQuery {
  run_id?: string;
  artifact_type?: string;
  workflow?: string;
  date?: string;
  dataset_id?: string;
  include_invalid?: boolean;
}

export type AuditEventType =
  | "chat_request_received"
  | "compliance_decision"
  | "workflow_started"
  | "workflow_finished"
  | "tool_invoked"
  | "connector_action"
  | "file_written"
  | "job_submitted"
  | "export_generated";

export interface AuditEventRecord {
  contract_version: string;
  event_id: string;
  event_type: AuditEventType;
  recorded_at: string;
  summary: string;
  outcome?: string | null;
  session_id?: string | null;
  run_id?: string | null;
  step_id?: string | null;
  job_id?: string | null;
  workflow_id?: string | null;
  tool_name?: string | null;
  connector_name?: string | null;
  actor: string;
  artifact_paths: string[];
  external_systems: string[];
  redaction_policy: string;
  details: JsonObject;
}

export interface AuditEventsResponse {
  events: AuditEventRecord[];
  retention_policy: RetentionPolicy;
}

export interface AuditEventsQuery {
  event_type?: AuditEventType;
  session_id?: string;
  run_id?: string;
  step_id?: string;
  job_id?: string;
  workflow_id?: string;
  tool_name?: string;
  connector_name?: string;
  outcome?: string;
  limit?: number;
}

export type ObservabilityMetricKind = "duration" | "rate" | "count" | "gauge";

export type ObservabilityTraceStatus = "ok" | "error" | "blocked";

export interface ObservabilityMetricRecord {
  contract_version: "observability_metric.v1";
  record_id: string;
  recorded_at: string;
  metric_name: string;
  metric_kind: ObservabilityMetricKind;
  value: number;
  unit: string;
  request_id?: string | null;
  session_id?: string | null;
  run_id?: string | null;
  step_id?: string | null;
  job_id?: string | null;
  workflow_id?: string | null;
  trace_id?: string | null;
  span_id?: string | null;
  attributes: JsonObject;
}

export interface ObservabilityTraceRecord {
  contract_version: "observability_trace.v1";
  trace_id: string;
  span_id: string;
  parent_span_id?: string | null;
  span_name: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  status: ObservabilityTraceStatus;
  request_id?: string | null;
  session_id?: string | null;
  run_id?: string | null;
  step_id?: string | null;
  job_id?: string | null;
  workflow_id?: string | null;
  attributes: JsonObject;
}

export interface ObservabilityDashboardPanelDefinition {
  title: string;
  metric_name: string;
  aggregation: string;
  filters?: JsonObject;
}

export interface ObservabilityDashboardDefinition {
  id: string;
  title: string;
  description: string;
  panels: ObservabilityDashboardPanelDefinition[];
}

export interface ObservabilityMetricsResponse {
  metrics: ObservabilityMetricRecord[];
  retention_policy: RetentionPolicy;
}

export interface ObservabilityTracesResponse {
  traces: ObservabilityTraceRecord[];
  retention_policy: RetentionPolicy;
}

export interface ObservabilityDashboardDefinitionsResponse {
  dashboards: ObservabilityDashboardDefinition[];
  retention_policy: RetentionPolicy;
}

export interface ObservabilityDurationSummary {
  count: number;
  average: number | null;
  p50: number | null;
  p95: number | null;
  min: number | null;
  max: number | null;
}

export interface ObservabilityRateSummary {
  count: number;
  average: number | null;
}

export interface ObservabilityOverviewFilters {
  workflow_id: string | null;
  session_id: string | null;
  request_id: string | null;
}

export interface ObservabilityOverviewRecordCounts {
  metric_records: number;
  trace_records: number;
}

export interface ObservabilityOverview {
  generated_at: string;
  window_days: number;
  filters: ObservabilityOverviewFilters;
  record_counts: ObservabilityOverviewRecordCounts;
  chat_responsiveness: {
    user_visible_latency_seconds: ObservabilityDurationSummary;
    backend_execution_latency_seconds: ObservabilityDurationSummary;
  };
  workflow_delivery: {
    workflow_duration_seconds: ObservabilityDurationSummary;
    step_duration_seconds: ObservabilityDurationSummary;
    failure_rate: ObservabilityRateSummary;
    block_rate: ObservabilityRateSummary;
  };
  workflow_quality: {
    qc_pass_rate: ObservabilityRateSummary;
    evidence_coverage_rate: ObservabilityRateSummary;
  };
  dashboards: ObservabilityDashboardDefinition[];
  retention_policy: RetentionPolicy;
}

export interface ObservabilityMetricsQuery {
  metric_name?: string;
  request_id?: string;
  session_id?: string;
  run_id?: string;
  step_id?: string;
  job_id?: string;
  workflow_id?: string;
  trace_id?: string;
  span_id?: string;
  limit?: number;
}

export interface ObservabilityTracesQuery {
  trace_id?: string;
  span_id?: string;
  parent_span_id?: string;
  span_name?: string;
  request_id?: string;
  session_id?: string;
  run_id?: string;
  step_id?: string;
  job_id?: string;
  workflow_id?: string;
  status?: ObservabilityTraceStatus;
  limit?: number;
}

export interface ObservabilityOverviewQuery {
  days?: number;
  request_id?: string;
  session_id?: string;
  workflow_id?: string;
  limit?: number;
}

export type ConnectorAction =
  | "configure"
  | "validate"
  | "import"
  | "export"
  | "sync_status";

export type ConnectorExecutionAction = "import" | "export" | "sync_status";

export type ConnectorActionStatus = "success" | "failed";

export type ConnectorActionOutcome =
  | "success"
  | "invalid_input"
  | "blocked"
  | "unsupported"
  | "execution_failure";

export type ConnectorFailureMode =
  | "invalid_configuration"
  | "unsupported_capability"
  | "blocked_action"
  | "remote_failure"
  | "sync_conflict"
  | "partial_result";

export type ConnectorTransportPattern =
  | "file_drop"
  | "rest_api"
  | "webhook_callback";

export type ConnectorConfigFieldKind =
  | "string"
  | "url"
  | "directory_path"
  | "route_path"
  | "env_var"
  | "string_list"
  | "boolean"
  | "enum";

export type ConnectorSystemKind =
  | "eln"
  | "lims"
  | "instrument"
  | "external_service";

export type ConnectorArtifactDomain =
  | "dataset_manifest"
  | "workflow_run"
  | "protocol_run"
  | "evidence_card"
  | "evidence_review"
  | "entity_grounding"
  | "claim_graph"
  | "compliance_report"
  | "qa_report"
  | "eln_export"
  | "report_bundle"
  | "report_bundle_manifest";

export interface ConnectorGuardrails {
  requires_compliance_gate: boolean;
  requires_provenance_records: boolean;
  requires_artifact_registration: boolean;
  allow_destructive_sync: boolean;
}

export interface ConnectorConfigField {
  key: string;
  kind: ConnectorConfigFieldKind;
  description: string;
  required: boolean;
  allowed_values: string[];
  secret_reference: boolean;
}

export interface ConnectorCapabilities {
  supported_actions: ConnectorAction[];
  transport_patterns: ConnectorTransportPattern[];
  artifact_domains: ConnectorArtifactDomain[];
  guardrails: ConnectorGuardrails;
}

export interface ConnectorConfigSummary {
  configured: boolean;
  configured_fields: string[];
  missing_required_fields: string[];
  uses_secret_references: boolean;
}

export interface ConnectorRegistryEntry {
  name: string;
  display_name: string;
  description: string;
  system_kind: ConnectorSystemKind;
  external_system: string;
  capabilities: ConnectorCapabilities;
  config_fields: ConnectorConfigField[];
  enabled: boolean;
  config_summary: ConnectorConfigSummary;
  notes: string[];
}

export interface ConnectorValidationIssue {
  field?: string | null;
  code: string;
  message: string;
}

export interface ConnectorActionRequest {
  dry_run?: boolean;
  artifact_path?: string | null;
  payload?: JsonObject | null;
  compliance_artifact_path?: string | null;
  provenance_artifact_paths?: string[];
  event_type?: string | null;
  delivery_signature?: string | null;
  session_id?: string | null;
  run_id?: string | null;
  workflow_id?: string | null;
}

export interface ConnectorActionResult {
  contract_version: string;
  connector_name: string;
  action: ConnectorAction;
  status: ConnectorActionStatus;
  outcome: ConnectorActionOutcome;
  summary: string;
  action_supported: boolean;
  non_destructive: boolean;
  failure_mode?: ConnectorFailureMode | null;
  issues: ConnectorValidationIssue[];
  config_summary?: ConnectorConfigSummary | null;
  artifact_paths: string[];
  external_paths: string[];
  metadata: JsonObject;
}

export interface ConnectorRegistryListResponse {
  connectors: ConnectorRegistryEntry[];
}

export interface ConnectorRegistryUpdateRequest {
  enabled: boolean;
  config?: JsonObject | null;
}

export interface ConnectorRegistryUpdateResponse {
  connector: ConnectorRegistryEntry;
  result: ConnectorActionResult;
}

export interface ConnectorValidationRequest {
  config?: JsonObject | null;
}

export interface SkillRegistryUpdateRequest {
  enabled: boolean;
}

export interface SkillRegistryUpdateResponse {
  name: string;
  enabled: boolean;
}
