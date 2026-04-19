/**
 * AUTO-GENERATED. Do not edit by hand.
 *
 * Produced by scripts/codegen-types.ts from:
 *   - backend/codegen/shared_types.schema.json
 *   - backend/runtime/events.schema.json
 *
 * Regenerate with:
 *   python -m codegen.shared_types             # from backend/
 *   npm run codegen:types                      # from frontend/
 */

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

/* =========================================================
 * Tool contracts and session content blocks
 * source: backend/codegen/shared_types.schema.json
 * ======================================================= */
export interface SessionApprovalGateBlock {
  input?: string;
  message?: string;
  policy?: JsonObject;
  reason?: string;
  result?: JsonObject;
  run_id?: string;
  tool?: string;
  type: "approval_gate";
}
export interface SessionPlanBlock {
  event?: "created" | "updated";
  plan?: JsonObject;
  run_id?: string;
  summary?: string;
  tool_trace?: JsonObject[];
  type: "plan";
}
export interface SessionRetrievalBlock {
  query?: string;
  results?: JsonObject[];
  type: "retrieval";
}
export interface SessionTextBlock {
  text: string;
  type: "text";
}
export interface SessionToolResultBlock {
  output?: string;
  result?: JsonObject;
  run_id?: string;
  tool?: string;
  type: "tool_result";
}
export interface SessionToolUseBlock {
  input?: string;
  run_id?: string;
  tool?: string;
  type: "tool_use";
}
export interface SessionUsageBlock {
  metadata: JsonObject;
  type: "usage";
}
export interface SessionVerificationBlock {
  run_id?: string;
  summary?: string;
  tool_trace?: JsonObject[];
  type: "verification";
  verdict?: "pass" | "repair_required" | "fail";
  verification?: JsonObject;
}
export interface ToolArtifactRef {
  artifact_type?: string;
  identifier?: string;
  label?: string;
  path?: string;
}
export interface ToolResultEnvelope {
  artifact_refs?: ToolArtifactRef[];
  contract_version?: string;
  error?: ToolResultError;
  metadata?: Record<string, JsonValue>;
  outcome?: "success" | "success_empty" | "blocked" | "invalid_input" | "retriable_failure" | "execution_failure" | "needs_approval" | "streaming_chunk";
  source_payload?: JsonValue;
  status?: "success" | "error";
  structured_payload?: JsonValue;
  summary: string;
  tool_name: string;
  warnings?: string[];
}
export interface ToolResultError {
  code: "blocked" | "invalid_input" | "retriable_failure" | "execution_failure" | "needs_approval";
  message: string;
  retriable?: boolean;
}
export type SessionContentBlock =
  | SessionTextBlock
  | SessionToolUseBlock
  | SessionToolResultBlock
  | SessionRetrievalBlock
  | SessionUsageBlock
  | SessionPlanBlock
  | SessionVerificationBlock
  | SessionApprovalGateBlock;

/* =========================================================
 * Runtime events (SSE / streaming)
 * source: backend/runtime/events.schema.json
 * ======================================================= */
export interface ChatStreamCompactionEvent {
  event_index?: number;
  from_turn: number;
  phase?: "snip" | "microcompact" | "collapse" | "autocompact";
  request_id?: string;
  saved_tokens: number;
  schema_version?: number;
  summary: string;
  to_turn: number;
  type: "compaction_event";
}
export interface ChatStreamDoneEvent {
  content: string;
  event_index?: number;
  request_id?: string;
  schema_version?: number;
  session_id?: string;
  turn_status?: "ok" | "awaiting_approval" | "budget_exceeded" | "error" | "cancelled";
  type: "done";
}
export interface ChatStreamErrorEvent {
  error: string;
  event_index?: number;
  request_id?: string;
  schema_version?: number;
  type: "error";
}
export interface ChatStreamNewResponseEvent {
  event_index?: number;
  request_id?: string;
  schema_version?: number;
  type: "new_response";
}
export interface ChatStreamPlanCreatedEvent {
  event_index?: number;
  plan: JsonObject;
  request_id?: string;
  run_id?: string;
  schema_version?: number;
  summary: string;
  tool_trace?: JsonObject[];
  type: "plan_created";
}
export interface ChatStreamPlanUpdatedEvent {
  event_index?: number;
  plan: JsonObject;
  request_id?: string;
  run_id?: string;
  schema_version?: number;
  summary: string;
  tool_trace?: JsonObject[];
  type: "plan_updated";
}
export interface ChatStreamRetrievalEvent {
  event_index?: number;
  query: string;
  request_id?: string;
  results: JsonObject[];
  schema_version?: number;
  type: "retrieval";
}
export interface ChatStreamTokenEvent {
  content: string;
  event_index?: number;
  request_id?: string;
  schema_version?: number;
  type: "token";
}
/** Emitted when policy gates a tool call pending human approval. */
export interface ChatStreamToolAwaitingApprovalEvent {
  event_index?: number;
  input: string;
  message: string;
  policy?: JsonObject;
  reason: string;
  request_id?: string;
  result?: JsonObject;
  run_id: string;
  schema_version?: number;
  tool: string;
  type: "tool_awaiting_approval";
}
/** Mid-tool partial output for streaming-capable tools. */
export interface ChatStreamToolChunkEvent {
  chunk: string;
  chunk_index: number;
  event_index?: number;
  request_id?: string;
  run_id: string;
  schema_version?: number;
  terminal?: boolean;
  tool: string;
  type: "tool_chunk";
}
export interface ChatStreamToolEndEvent {
  event_index?: number;
  output: string;
  policy?: JsonObject;
  request_id?: string;
  result?: JsonObject;
  run_id: string;
  schema_version?: number;
  tool: string;
  type: "tool_end";
}
export interface ChatStreamToolStartEvent {
  event_index?: number;
  input: string;
  request_id?: string;
  run_id: string;
  schema_version?: number;
  tool: string;
  type: "tool_start";
}
export interface ChatStreamVerificationResultEvent {
  event_index?: number;
  request_id?: string;
  run_id?: string;
  schema_version?: number;
  summary: string;
  tool_trace?: JsonObject[];
  type: "verification_result";
  verdict: "pass" | "repair_required" | "fail";
  verification: JsonObject;
}
/** Non-fatal diagnostic surfaced to the user during a turn. */
export interface WarningRuntimeEvent {
  cited?: string[];
  event_index?: number;
  included?: string[];
  kind: string;
  message: string;
  missing?: string[];
  request_id?: string;
  review_path?: string;
  schema_version?: number;
  type: "warning";
}
export interface ChatStreamWorkflowStepEndedEvent {
  duration_ms: number;
  event_index?: number;
  outputs?: JsonObject;
  request_id?: string;
  run_id: string;
  schema_version?: number;
  step_id: string;
  step_index: number;
  total_steps: number;
  type: "workflow_step_ended";
  workflow_id: string;
}
export interface ChatStreamWorkflowStepFailedEvent {
  attempt?: number;
  duration_ms: number;
  error: string;
  event_index?: number;
  failure_policy: "fail_workflow" | "block_workflow" | "continue_with_warning";
  request_id?: string;
  run_id: string;
  schema_version?: number;
  step_id: string;
  step_index: number;
  total_steps: number;
  type: "workflow_step_failed";
  workflow_id: string;
}
/** Emitted by the workflow runner before it invokes a step's executor. */
export interface ChatStreamWorkflowStepStartedEvent {
  attempt?: number;
  event_index?: number;
  label?: string;
  request_id?: string;
  run_id: string;
  schema_version?: number;
  step_id: string;
  step_index: number;
  total_steps: number;
  type: "workflow_step_started";
  workflow_id: string;
}
/** Discriminated union of every backend-emitted streaming event. */
export type ChatStreamEventDTO =
  | ChatStreamRetrievalEvent
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
  | WarningRuntimeEvent
  | ChatStreamDoneEvent
  | ChatStreamErrorEvent
  | ChatStreamWorkflowStepStartedEvent
  | ChatStreamWorkflowStepEndedEvent
  | ChatStreamWorkflowStepFailedEvent;
