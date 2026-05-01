/**
 * Hand-written types + re-exports.
 *
 * Backend-shaped DTOs (tool contracts, session blocks, runtime events) are
 * generated from pydantic models into ``./types.generated`` and re-exported
 * here. Anything UI-only (inspector view models, hybrid chat Message,
 * synthetic parse_error event, access-scope state) stays hand-written below.
 *
 * Drift is caught by:
 *   - ``backend/tests/test_shared_types_schema.py`` — JSON snapshot vs pydantic.
 *   - ``frontend/src/lib/types.generated.test.ts`` — codegen vs committed .ts.
 *
 * Regenerate the generated DTOs with:
 *   python -m codegen.shared_types             # from backend/
 *   npm run codegen:types                      # from frontend/
 */

// ────────────────────────────────────────────────────────────────────────
// Generated DTOs — re-exported verbatim where backend ↔ frontend match.
// ────────────────────────────────────────────────────────────────────────

export type {
  JsonValue,
  JsonObject,
  ToolArtifactRef,
  ToolResultError,
  SessionTextBlock,
  SessionUsageBlock,
  ChatStreamTokenEvent,
  ChatStreamPlanCreatedEvent,
  ChatStreamPlanUpdatedEvent,
  ChatStreamVerificationResultEvent,
  ChatStreamNewResponseEvent,
  ChatStreamCompactionEvent,
  ChatStreamDoneEvent,
  ChatStreamErrorEvent,
  ChatStreamRetrievalErrorEvent,
  ChatStreamToolStartEvent,
  ChatStreamToolChunkEvent,
  ChatStreamWorkflowStepStartedEvent,
  ChatStreamWorkflowStepEndedEvent,
  ChatStreamWorkflowStepFailedEvent,
  TurnExit,
} from "./types.generated";

import type {
  JsonObject,
  ToolArtifactRef,
  ToolResultError,
  ToolResultEnvelope as GeneratedToolResultEnvelope,
  ChatStreamToolEndEvent as GeneratedChatStreamToolEndEvent,
  ChatStreamToolAwaitingApprovalEvent as GeneratedChatStreamToolAwaitingApprovalEvent,
  ChatStreamRetrievalEvent as GeneratedChatStreamRetrievalEvent,
  ChatStreamTokenEvent,
  ChatStreamToolStartEvent,
  ChatStreamToolChunkEvent,
  ChatStreamPlanCreatedEvent,
  ChatStreamPlanUpdatedEvent,
  ChatStreamVerificationResultEvent,
  ChatStreamNewResponseEvent,
  ChatStreamCompactionEvent,
  ChatStreamDoneEvent,
  ChatStreamErrorEvent,
  ChatStreamRetrievalErrorEvent,
  TurnExit,
  ChatStreamWorkflowStepStartedEvent,
  ChatStreamWorkflowStepEndedEvent,
  ChatStreamWorkflowStepFailedEvent,
  SessionTextBlock,
  SessionUsageBlock,
  SessionPlanBlock as GeneratedSessionPlanBlock,
  SessionVerificationBlock as GeneratedSessionVerificationBlock,
  SessionToolUseBlock as GeneratedSessionToolUseBlock,
  SessionToolResultBlock as GeneratedSessionToolResultBlock,
  SessionRetrievalBlock as GeneratedSessionRetrievalBlock,
  SessionApprovalGateBlock as GeneratedSessionApprovalGateBlock,
} from "./types.generated";

// ────────────────────────────────────────────────────────────────────────
// Frontend-tightened DTOs
//
// The backend emits these fields as generic dicts on the wire; the frontend
// treats them as their typed shapes after the zod parser in
// ``runtime-events.ts`` has validated the envelope. We compose the tighter
// shape from the generated base so a backend-side field addition still
// propagates, while the overridden field stays specific.
// ────────────────────────────────────────────────────────────────────────

export interface RetrievalResult {
  text: string;
  score: number;
  source: string;
  memory_type?: string;
  memory_type_label?: string;
  memory_name?: string;
  memory_description?: string;
}

// Pydantic's JSON schema marks fields-with-defaults as optional, but the
// backend always emits them. Tighten the envelope here so consumers can
// iterate without undefined-checks on fields the wire always carries.
export type ToolResultEnvelope = Omit<
  GeneratedToolResultEnvelope,
  "artifact_refs" | "metadata" | "warnings" | "status" | "outcome" | "contract_version"
> & {
  contract_version: string;
  artifact_refs: ToolArtifactRef[];
  metadata: JsonObject;
  warnings: string[];
  status: "success" | "error";
  outcome:
    | "success"
    | "success_empty"
    | "blocked"
    | "invalid_input"
    | "retriable_failure"
    | "execution_failure"
    | "needs_approval"
    | "streaming_chunk";
};

export type ChatStreamToolEndEvent = Omit<
  GeneratedChatStreamToolEndEvent,
  "result"
> & {
  result?: ToolResultEnvelope;
};

export type ChatStreamToolAwaitingApprovalEvent = Omit<
  GeneratedChatStreamToolAwaitingApprovalEvent,
  "result"
> & {
  result?: ToolResultEnvelope;
};

// ``SessionPlanBlock.plan`` / ``SessionVerificationBlock.verification`` are
// marked optional by ``TypedDict(total=False)`` in the backend, but the
// persisted blocks always carry them. Tighten so the inspector UI can render
// them without null-checking.
export type SessionPlanBlock = Omit<GeneratedSessionPlanBlock, "plan"> & {
  plan: JsonObject;
};
export type SessionVerificationBlock = Omit<
  GeneratedSessionVerificationBlock,
  "verification"
> & {
  verification: JsonObject;
};

export type ChatStreamRetrievalEvent = Omit<
  GeneratedChatStreamRetrievalEvent,
  "results"
> & {
  results: RetrievalResult[];
};

// The backend writes these blocks with `tool`/`input`/`output` populated even
// though session_schema.py marks them optional (TypedDict total=False). The
// frontend consumers treat those as present; narrow the types here so the
// store / reducers don't have to re-check every field.
export type SessionToolUseBlock = Omit<
  GeneratedSessionToolUseBlock,
  "tool" | "input"
> & {
  tool: string;
  input: string;
};

export type SessionToolResultBlock = Omit<
  GeneratedSessionToolResultBlock,
  "tool" | "output" | "result"
> & {
  tool: string;
  output: string;
  result?: ToolResultEnvelope;
};

export type SessionRetrievalBlock = Omit<
  GeneratedSessionRetrievalBlock,
  "results"
> & {
  results: RetrievalResult[];
};

// Backend always populates tool/input/run_id/reason/message when it writes
// an approval_gate block, and ``result`` is a generic dict on the wire — we
// tighten both so the inspector UI can render without undefined-checks.
export type SessionApprovalGateBlock = Omit<
  GeneratedSessionApprovalGateBlock,
  "tool" | "input" | "run_id" | "reason" | "message" | "result"
> & {
  tool: string;
  input: string;
  run_id: string;
  reason: string;
  message: string;
  result?: ToolResultEnvelope;
};

export interface SessionWarningBlock {
  type: "warning";
  kind: string;
  message: string;
  missing?: string[];
  cited?: string[];
  included?: string[];
  review_path?: string;
}

export type SessionContentBlock =
  | SessionTextBlock
  | SessionToolUseBlock
  | SessionToolResultBlock
  | SessionRetrievalBlock
  | SessionUsageBlock
  | SessionPlanBlock
  | SessionVerificationBlock
  | SessionApprovalGateBlock
  | SessionWarningBlock;

export interface ToolCall {
  tool: string;
  input: string;
  output: string;
  run_id?: string;
  result?: ToolResultEnvelope;
}

// ────────────────────────────────────────────────────────────────────────
// Synthetic stream events + full client-side ChatStreamEvent union
// ────────────────────────────────────────────────────────────────────────

/**
 * Client-side synthetic event surfaced when an incoming SSE payload fails
 * RuntimeEvent (zod) validation. Never emitted by the backend.
 */
export interface ChatStreamParseErrorEvent {
  request_id?: string;
  event_index?: number;
  type: "parse_error";
  error: string;
  raw?: string;
}

/**
 * Client-side synthetic event emitted when the SSE parser's buffered remainder
 * grows past the configured cap (default 4 MB) without a record terminator.
 * The transport treats this as terminal and cancels the reader to defend
 * against a memory-exhaustion DoS.
 */
export interface ChatStreamOverflowEvent {
  request_id?: string;
  event_index?: number;
  type: "stream_overflow";
  bufferedBytes: number;
  maxBufferBytes: number;
}

export interface ChatStreamWarningEvent {
  request_id?: string;
  event_index?: number;
  type: "warning";
  kind: string;
  message: string;
  missing: string[];
  cited: string[];
  included: string[];
  review_path?: string | null;
}

export type ChatStreamEvent =
  | ChatStreamRetrievalEvent
  | ChatStreamRetrievalErrorEvent
  | ChatStreamTokenEvent
  | ChatStreamToolStartEvent
  | ChatStreamToolEndEvent
  | ChatStreamToolAwaitingApprovalEvent
  | ChatStreamToolChunkEvent
  | ChatStreamPlanCreatedEvent
  | ChatStreamPlanUpdatedEvent
  | ChatStreamVerificationResultEvent
  | ChatStreamNewResponseEvent
  | ChatStreamCompactionEvent
  | ChatStreamWarningEvent
  | ChatStreamDoneEvent
  | ChatStreamErrorEvent
  | ChatStreamWorkflowStepStartedEvent
  | ChatStreamWorkflowStepEndedEvent
  | ChatStreamWorkflowStepFailedEvent
  | ChatStreamParseErrorEvent
  | ChatStreamOverflowEvent;

export type ChatStreamEventType = ChatStreamEvent["type"];

// ────────────────────────────────────────────────────────────────────────
// Hybrid chat Message — backend shape + client-side streaming fields
// ────────────────────────────────────────────────────────────────────────

export type WorkflowStepStatus = "running" | "ok" | "failed";

export interface WorkflowStepState {
  workflow_id: string;
  run_id: string;
  step_id: string;
  step_index: number;
  total_steps: number;
  status: WorkflowStepStatus;
  label?: string;
  attempt: number;
  duration_ms?: number;
  error?: string;
  failure_policy?:
    | "fail_workflow"
    | "block_workflow"
    | "continue_with_warning";
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  request_id?: string;
  blocks?: SessionContentBlock[];
  isStreaming?: boolean;
  startedAtMs?: number;
  endedAtMs?: number;
  /** Tool currently executing (cleared when tool_end arrives) */
  pendingTool?: { tool: string; input: string; runId: string };
  /**
   * Mid-tool partial outputs, keyed by run_id, accumulated until the matching
   * `tool_end` arrives and the buffer is flushed into the persisted block.
   */
  toolChunkBuffers?: Record<string, { chunks: { index: number; text: string }[] }>;
  /**
   * Live workflow step list, ordered by first-seen ``started`` event. Keyed by
   * ``${run_id}:${step_id}`` so repeated attempts collapse into a single row.
   * Transport-only state — not persisted in session JSON.
   */
  workflowSteps?: WorkflowStepState[];
  /**
   * Terminal exit payload from the last ``done`` event of this turn. Drives the
   * reason-specific pill/banner the UI renders under the assistant message.
   * Absent until the stream terminates; preserved across re-renders so the
   * outcome stays visible after streaming completes.
   */
  exit?: TurnExit;
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

// ────────────────────────────────────────────────────────────────────────
// Evidence / compliance DTOs
//
// These shapes mirror backend/artifacts/schemas.py. Kept hand-written for now;
// they can be folded into the codegen manifest when the evidence/compliance
// path is next touched.
// ────────────────────────────────────────────────────────────────────────

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
  entity_tags?: import("./types.generated").JsonValue;
  grounded_entities?: import("./types.generated").JsonValue;
  grounding_results?: import("./types.generated").JsonValue;
  grounding_requires_clarification: boolean;
  entity_grounding_path?: string | null;
}

export interface EvidenceRetrievalFailure {
  pmid: string;
  error: string;
}

export interface EvidenceRetrievalPayload {
  query?: string | null;
  candidate_records: import("./types.generated").JsonValue[];
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

// ────────────────────────────────────────────────────────────────────────
// UI-only view models (inspector, access-scope state, tokenizer, etc.)
// ────────────────────────────────────────────────────────────────────────

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
