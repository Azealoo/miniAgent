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

export type ComplianceApprovalScope = "message" | "run";

export interface ComplianceRequestContext {
  user_message: string;
  attached_identifiers: string[];
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

export interface SourcesInspectorChecklistCard {
  summary_label: string | null;
  detail: string | null;
  state: SourcesInspectorChecklistState;
  items: SourcesInspectorChecklistItem[];
}

export interface SourcesInspectorSummary {
  scoped_message_count: number;
  citations: SourcesInspectorCitation[];
  checklist: SourcesInspectorChecklistCard;
}

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
  memory_type?: string;
  memory_type_label?: string;
  memory_name?: string;
  memory_description?: string;
}

interface ChatStreamEventBase {
  request_id?: string;
  event_index?: number;
}

export interface ChatStreamRetrievalEvent extends ChatStreamEventBase {
  type: "retrieval";
  query: string;
  results: RetrievalResult[];
}

export interface ChatStreamTokenEvent extends ChatStreamEventBase {
  type: "token";
  content: string;
}

export interface ChatStreamToolStartEvent extends ChatStreamEventBase {
  type: "tool_start";
  tool: string;
  input: string;
  run_id?: string;
}

export interface ChatStreamToolEndEvent extends ChatStreamEventBase {
  type: "tool_end";
  tool: string;
  output: string;
  run_id?: string;
  result?: ToolResultEnvelope;
  policy?: JsonObject;
}

interface ChatStreamPlanEventBase extends ChatStreamEventBase {
  summary: string;
  run_id?: string;
  plan: JsonObject;
  tool_trace?: JsonObject[];
}

export interface ChatStreamPlanCreatedEvent extends ChatStreamPlanEventBase {
  type: "plan_created";
}

export interface ChatStreamPlanUpdatedEvent extends ChatStreamPlanEventBase {
  type: "plan_updated";
}

export interface ChatStreamVerificationResultEvent extends ChatStreamEventBase {
  type: "verification_result";
  summary: string;
  verdict: "pass" | "repair_required" | "fail";
  run_id?: string;
  verification: JsonObject;
  tool_trace?: JsonObject[];
}

export interface ChatStreamNewResponseEvent extends ChatStreamEventBase {
  type: "new_response";
}

export interface ChatStreamDoneEvent extends ChatStreamEventBase {
  type: "done";
  content: string;
  session_id?: string;
}

export interface ChatStreamErrorEvent extends ChatStreamEventBase {
  type: "error";
  error: string;
}

export type ChatStreamEvent =
  | ChatStreamRetrievalEvent
  | ChatStreamTokenEvent
  | ChatStreamToolStartEvent
  | ChatStreamToolEndEvent
  | ChatStreamPlanCreatedEvent
  | ChatStreamPlanUpdatedEvent
  | ChatStreamVerificationResultEvent
  | ChatStreamNewResponseEvent
  | ChatStreamDoneEvent
  | ChatStreamErrorEvent;

export type ChatStreamEventType = ChatStreamEvent["type"];

export interface SessionTextBlock {
  type: "text";
  text: string;
}

export interface SessionToolUseBlock {
  type: "tool_use";
  tool: string;
  input: string;
  run_id?: string;
}

export interface SessionToolResultBlock {
  type: "tool_result";
  tool: string;
  output: string;
  run_id?: string;
  result?: ToolResultEnvelope;
}

export interface SessionRetrievalBlock {
  type: "retrieval";
  query?: string;
  results: RetrievalResult[];
}

export interface SessionUsageBlock {
  type: "usage";
  metadata: JsonObject;
}

export interface SessionPlanBlock {
  type: "plan";
  event: "created" | "updated";
  summary: string;
  run_id?: string;
  plan: JsonObject;
  tool_trace?: JsonObject[];
}

export interface SessionVerificationBlock {
  type: "verification";
  summary: string;
  verdict: "pass" | "repair_required" | "fail";
  run_id?: string;
  verification: JsonObject;
  tool_trace?: JsonObject[];
}

export type SessionContentBlock =
  | SessionTextBlock
  | SessionToolUseBlock
  | SessionToolResultBlock
  | SessionRetrievalBlock
  | SessionUsageBlock
  | SessionPlanBlock
  | SessionVerificationBlock;

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  request_id?: string;
  tool_calls?: ToolCall[];
  retrievals?: RetrievalResult[];
  blocks?: SessionContentBlock[];
  isStreaming?: boolean;
  startedAtMs?: number;
  endedAtMs?: number;
  /** Tool currently executing (cleared when tool_end arrives) */
  pendingTool?: { tool: string; input: string; runId: string };
}

export interface SessionHistoryMessage {
  role: string;
  content?: string;
  request_id?: string;
  tool_calls?: ToolCall[];
  retrievals?: RetrievalResult[];
  blocks?: SessionContentBlock[];
}

export interface SessionContinuitySummary {
  source_format: "structured" | "legacy";
  legacy_summary: string | null;
  decisions_and_rationale: string[];
  results_register: string[];
  evidence_register: string[];
  compliance_register: string[];
  open_questions_and_next_actions: string[];
  archive_id: string | null;
  archived_message_count: number;
}

export interface SessionContinuityResponse {
  summaries: SessionContinuitySummary[];
}

export type InspectorTab =
  | "files"
  | "sources"
  | "memory"
  | "usage"
  | "turns";

export interface Session {
  id: string;
  title: string;
  updated_at: number;
  message_count: number;
}

export interface FilesWorkspaceItem {
  path: string;
  name: string;
  artifact_type: string | null;
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

export type TokenizerBackend =
  | "tiktoken_cl100k_base"
  | "deterministic_fallback";

export type TokenizerAccuracy = "model_aligned" | "approximate";

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
  tokenizer_backend: TokenizerBackend;
  tokenizer_accuracy: TokenizerAccuracy;
}

export interface Skill {
  name: string;
  path: string;
  category?: string;
  stage?: string;
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

export type AccessScope = "inspection" | "execution" | "admin";

export type AccessAuthorizationMode = "loopback" | "bearer";

export type AccessScopeStateCode =
  | "checking"
  | "granted"
  | "token_required"
  | "server_misconfigured"
  | "forbidden"
  | "unavailable";

export interface AccessProbeResponse {
  scope: AccessScope;
  authorization_mode: AccessAuthorizationMode | null;
}

export interface AccessScopeState {
  scope: AccessScope;
  status: AccessScopeStateCode;
  authorizationMode: AccessAuthorizationMode | null;
  hasToken: boolean;
  detail: string;
}

export interface SkillRegistryUpdateRequest {
  enabled: boolean;
}

export interface SkillRegistryUpdateResponse {
  name: string;
  enabled: boolean;
}
