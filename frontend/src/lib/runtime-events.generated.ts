/**
 * AUTO-GENERATED. Do not edit by hand.
 *
 * Produced by scripts/codegen-types.ts from
 * backend/runtime/events.schema.json. The hand-written
 * ./runtime-events.ts re-exports from this file and adds the
 * `parseRuntimeEvent` helper that every SSE payload flows through.
 *
 * Regenerate with:
 *   python -m codegen.shared_types             # from backend/
 *   npm run codegen:types                      # from frontend/
 */
import { z } from "zod";

export const RUNTIME_EVENT_SCHEMA_VERSION = 2 as const;

export const TURN_EXIT_REASONS = ["success", "tool_error", "user_abort", "context_limit", "token_budget", "approval_denied", "awaiting_approval"] as const;
export type TurnExitReason = (typeof TURN_EXIT_REASONS)[number];

/** Structured terminal-state payload carried on every ``done`` event. */
export const TurnExitSchema = z
  .object({
    exit_code: z.number().int(),
    reason: z.enum(TURN_EXIT_REASONS),
    summary: z.string().nullish(),
  })
  .strict();
export type TurnExit = z.infer<typeof TurnExitSchema>;

export const COMPACTION_PHASES = ["snip", "microcompact", "collapse", "autocompact"] as const;
export type CompactionPhase = (typeof COMPACTION_PHASES)[number];

export const RetrievalRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    query: z.string(),
    request_id: z.string().nullish(),
    results: z.array(z.record(z.string(), z.unknown())),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    type: z.literal("retrieval"),
  })
  .strict();
/** Non-fatal signal that a RAG retrieval attempt raised. */
export const RetrievalErrorRuntimeEventSchema = z
  .object({
    error_type: z.string(),
    event_index: z.number().int().min(1).nullish(),
    message: z.string(),
    query: z.string(),
    request_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    type: z.literal("retrieval_error"),
  })
  .strict();
export const TokenRuntimeEventSchema = z
  .object({
    content: z.string(),
    event_index: z.number().int().min(1).nullish(),
    request_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    type: z.literal("token"),
  })
  .strict();
export const ToolStartRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    input: z.string(),
    request_id: z.string().nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    tool: z.string(),
    type: z.literal("tool_start"),
  })
  .strict();
export const ToolEndRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    output: z.string(),
    policy: z.record(z.string(), z.unknown()).nullish(),
    request_id: z.string().nullish(),
    result: z.record(z.string(), z.unknown()).nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    tool: z.string(),
    type: z.literal("tool_end"),
  })
  .strict();
/** Emitted when policy gates a tool call pending human approval. */
export const ToolAwaitingApprovalRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    input: z.string(),
    message: z.string(),
    policy: z.record(z.string(), z.unknown()).nullish(),
    reason: z.string(),
    request_id: z.string().nullish(),
    result: z.record(z.string(), z.unknown()).nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    tool: z.string(),
    type: z.literal("tool_awaiting_approval"),
  })
  .strict();
/** Mid-tool partial output for streaming-capable tools. */
export const ToolChunkRuntimeEventSchema = z
  .object({
    chunk: z.string(),
    chunk_index: z.number().int().min(0),
    event_index: z.number().int().min(1).nullish(),
    request_id: z.string().nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    terminal: z.boolean().default(false),
    tool: z.string(),
    type: z.literal("tool_chunk"),
  })
  .strict();
export const PlanCreatedRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    plan: z.record(z.string(), z.unknown()),
    request_id: z.string().nullish(),
    run_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    summary: z.string(),
    tool_trace: z.array(z.record(z.string(), z.unknown())).nullish(),
    type: z.literal("plan_created"),
  })
  .strict();
export const PlanUpdatedRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    plan: z.record(z.string(), z.unknown()),
    request_id: z.string().nullish(),
    run_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    summary: z.string(),
    tool_trace: z.array(z.record(z.string(), z.unknown())).nullish(),
    type: z.literal("plan_updated"),
  })
  .strict();
export const VerificationResultRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    request_id: z.string().nullish(),
    run_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    summary: z.string(),
    tool_trace: z.array(z.record(z.string(), z.unknown())).nullish(),
    type: z.literal("verification_result"),
    verdict: z.enum(["pass", "repair_required", "fail"]),
    verification: z.record(z.string(), z.unknown()),
  })
  .strict();
export const NewResponseRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    request_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    type: z.literal("new_response"),
  })
  .strict();
export const CompactionRuntimeEventSchema = z
  .object({
    event_index: z.number().int().min(1).nullish(),
    from_turn: z.number().int(),
    phase: z.enum(["snip", "microcompact", "collapse", "autocompact"]).nullish(),
    request_id: z.string().nullish(),
    saved_tokens: z.number().int(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    summary: z.string(),
    to_turn: z.number().int(),
    type: z.literal("compaction_event"),
  })
  .strict();
/** Non-fatal diagnostic surfaced to the user during a turn. */
export const WarningRuntimeEventSchema = z
  .object({
    cited: z.array(z.string()).default([]),
    event_index: z.number().int().min(1).nullish(),
    included: z.array(z.string()).default([]),
    kind: z.string(),
    message: z.string(),
    missing: z.array(z.string()).default([]),
    request_id: z.string().nullish(),
    review_path: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    type: z.literal("warning"),
  })
  .strict();
export const DoneRuntimeEventSchema = z
  .object({
    content: z.string(),
    event_index: z.number().int().min(1).nullish(),
    exit: TurnExitSchema.nullish(),
    request_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    session_id: z.string().nullish(),
    turn_status: z.enum(["ok", "awaiting_approval", "budget_exceeded", "error", "cancelled"]).nullish(),
    type: z.literal("done"),
  })
  .strict();
export const ErrorRuntimeEventSchema = z
  .object({
    error: z.string(),
    event_index: z.number().int().min(1).nullish(),
    request_id: z.string().nullish(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    type: z.literal("error"),
  })
  .strict();
/** Emitted by the workflow runner before it invokes a step's executor. */
export const WorkflowStepStartedRuntimeEventSchema = z
  .object({
    attempt: z.number().int().min(1).default(1),
    event_index: z.number().int().min(1).nullish(),
    label: z.string().nullish(),
    request_id: z.string().nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    step_id: z.string(),
    step_index: z.number().int().min(1),
    total_steps: z.number().int().min(1),
    type: z.literal("workflow_step_started"),
    workflow_id: z.string(),
  })
  .strict();
export const WorkflowStepEndedRuntimeEventSchema = z
  .object({
    duration_ms: z.number().int().min(0),
    event_index: z.number().int().min(1).nullish(),
    outputs: z.record(z.string(), z.unknown()).nullish(),
    request_id: z.string().nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    step_id: z.string(),
    step_index: z.number().int().min(1),
    total_steps: z.number().int().min(1),
    type: z.literal("workflow_step_ended"),
    workflow_id: z.string(),
  })
  .strict();
export const WorkflowStepFailedRuntimeEventSchema = z
  .object({
    attempt: z.number().int().min(1).default(1),
    duration_ms: z.number().int().min(0),
    error: z.string(),
    event_index: z.number().int().min(1).nullish(),
    failure_policy: z.enum(["fail_workflow", "block_workflow", "continue_with_warning"]),
    request_id: z.string().nullish(),
    run_id: z.string(),
    schema_version: z.number().int().default(RUNTIME_EVENT_SCHEMA_VERSION),
    step_id: z.string(),
    step_index: z.number().int().min(1),
    total_steps: z.number().int().min(1),
    type: z.literal("workflow_step_failed"),
    workflow_id: z.string(),
  })
  .strict();

export const ChatStreamEventSchema = z.discriminatedUnion("type", [
  RetrievalRuntimeEventSchema,
  RetrievalErrorRuntimeEventSchema,
  TokenRuntimeEventSchema,
  ToolStartRuntimeEventSchema,
  ToolEndRuntimeEventSchema,
  ToolAwaitingApprovalRuntimeEventSchema,
  ToolChunkRuntimeEventSchema,
  PlanCreatedRuntimeEventSchema,
  PlanUpdatedRuntimeEventSchema,
  VerificationResultRuntimeEventSchema,
  NewResponseRuntimeEventSchema,
  CompactionRuntimeEventSchema,
  WarningRuntimeEventSchema,
  DoneRuntimeEventSchema,
  ErrorRuntimeEventSchema,
  WorkflowStepStartedRuntimeEventSchema,
  WorkflowStepEndedRuntimeEventSchema,
  WorkflowStepFailedRuntimeEventSchema,
]);
export const RuntimeEventSchema = ChatStreamEventSchema;
export type ChatStreamEvent = z.infer<typeof ChatStreamEventSchema>;
export type RuntimeEvent = ChatStreamEvent;

export const RUNTIME_EVENT_TYPES = ["retrieval", "retrieval_error", "token", "tool_start", "tool_end", "tool_awaiting_approval", "tool_chunk", "plan_created", "plan_updated", "verification_result", "new_response", "compaction_event", "warning", "done", "error", "workflow_step_started", "workflow_step_ended", "workflow_step_failed"] as const;
export type RuntimeEventType = (typeof RUNTIME_EVENT_TYPES)[number];

export const RUNTIME_EVENT_SCHEMAS: Record<RuntimeEventType, z.ZodTypeAny> = {
  retrieval: RetrievalRuntimeEventSchema,
  retrieval_error: RetrievalErrorRuntimeEventSchema,
  token: TokenRuntimeEventSchema,
  tool_start: ToolStartRuntimeEventSchema,
  tool_end: ToolEndRuntimeEventSchema,
  tool_awaiting_approval: ToolAwaitingApprovalRuntimeEventSchema,
  tool_chunk: ToolChunkRuntimeEventSchema,
  plan_created: PlanCreatedRuntimeEventSchema,
  plan_updated: PlanUpdatedRuntimeEventSchema,
  verification_result: VerificationResultRuntimeEventSchema,
  new_response: NewResponseRuntimeEventSchema,
  compaction_event: CompactionRuntimeEventSchema,
  warning: WarningRuntimeEventSchema,
  done: DoneRuntimeEventSchema,
  error: ErrorRuntimeEventSchema,
  workflow_step_started: WorkflowStepStartedRuntimeEventSchema,
  workflow_step_ended: WorkflowStepEndedRuntimeEventSchema,
  workflow_step_failed: WorkflowStepFailedRuntimeEventSchema,
};
