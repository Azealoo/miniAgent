/**
 * Transport-neutral RuntimeEvent schema — frontend zod mirror.
 *
 * Keep this file in sync with `backend/runtime/events.py`. The drift-guard in
 * `backend/tests/test_runtime_events.py` regenerates the shared JSON schema on
 * every run; the vitest `runtime-events.test.ts` asserts the zod shapes here
 * enforce the same required fields, so both sides fail fast when one side
 * moves without the other.
 *
 * SSE is the current adapter in `api.ts`, but any stdin/WebSocket consumer can
 * reuse `parseRuntimeEvent` to validate an incoming payload.
 */
import { z } from "zod";

export const RUNTIME_EVENT_SCHEMA_VERSION = 1 as const;

export const RUNTIME_EVENT_TYPES = [
  "retrieval",
  "token",
  "tool_start",
  "tool_end",
  "tool_awaiting_approval",
  "tool_chunk",
  "plan_created",
  "plan_updated",
  "verification_result",
  "new_response",
  "compaction_event",
  "done",
  "error",
  "workflow_step_started",
  "workflow_step_ended",
  "workflow_step_failed",
] as const;

export type RuntimeEventType = (typeof RUNTIME_EVENT_TYPES)[number];

// Missing schema_version defaults to the current schema so the zod consumer can
// accept legacy SSE payloads during a backend rollout without silently losing
// events. Unknown-value cases (e.g., a future schema_version=2 payload hitting
// a v1 client) still flow through validation and can be gated downstream.
const schemaVersionField = z
  .number()
  .int()
  .optional()
  .default(RUNTIME_EVENT_SCHEMA_VERSION);

const requestIdField = z.string().nullish();
const eventIndexField = z.number().int().min(1).nullish();

const jsonObjectSchema = z
  .record(z.string(), z.unknown())
  .readonly()
  .or(z.record(z.string(), z.unknown()));

const RetrievalResultSchema = z
  .object({})
  .catchall(z.unknown());

const RetrievalRuntimeEventSchema = z
  .object({
    type: z.literal("retrieval"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    query: z.string(),
    results: z.array(RetrievalResultSchema),
  })
  .strict();

const TokenRuntimeEventSchema = z
  .object({
    type: z.literal("token"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    content: z.string(),
  })
  .strict();

const ToolStartRuntimeEventSchema = z
  .object({
    type: z.literal("tool_start"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    tool: z.string(),
    input: z.string(),
    run_id: z.string(),
  })
  .strict();

const ToolEndRuntimeEventSchema = z
  .object({
    type: z.literal("tool_end"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    tool: z.string(),
    output: z.string(),
    run_id: z.string(),
    result: jsonObjectSchema.nullish(),
    policy: jsonObjectSchema.nullish(),
  })
  .strict();

const ToolAwaitingApprovalRuntimeEventSchema = z
  .object({
    type: z.literal("tool_awaiting_approval"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    tool: z.string(),
    input: z.string(),
    run_id: z.string(),
    reason: z.string(),
    message: z.string(),
    result: jsonObjectSchema.nullish(),
    policy: jsonObjectSchema.nullish(),
  })
  .strict();

const ToolChunkRuntimeEventSchema = z
  .object({
    type: z.literal("tool_chunk"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    tool: z.string(),
    run_id: z.string(),
    chunk_index: z.number().int().min(0),
    chunk: z.string(),
    terminal: z.boolean().default(false),
  })
  .strict();

const PlanCreatedRuntimeEventSchema = z
  .object({
    type: z.literal("plan_created"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    summary: z.string(),
    plan: jsonObjectSchema,
    run_id: z.string().nullish(),
    tool_trace: z.array(jsonObjectSchema).nullish(),
  })
  .strict();

const PlanUpdatedRuntimeEventSchema = z
  .object({
    type: z.literal("plan_updated"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    summary: z.string(),
    plan: jsonObjectSchema,
    run_id: z.string().nullish(),
    tool_trace: z.array(jsonObjectSchema).nullish(),
  })
  .strict();

const VerificationResultRuntimeEventSchema = z
  .object({
    type: z.literal("verification_result"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    summary: z.string(),
    verdict: z.enum(["pass", "repair_required", "fail"]),
    verification: jsonObjectSchema,
    run_id: z.string().nullish(),
    tool_trace: z.array(jsonObjectSchema).nullish(),
  })
  .strict();

const NewResponseRuntimeEventSchema = z
  .object({
    type: z.literal("new_response"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
  })
  .strict();

const CompactionRuntimeEventSchema = z
  .object({
    type: z.literal("compaction_event"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    from_turn: z.number().int(),
    to_turn: z.number().int(),
    summary: z.string(),
    saved_tokens: z.number().int(),
  })
  .strict();

const DoneRuntimeEventSchema = z
  .object({
    type: z.literal("done"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    content: z.string(),
    session_id: z.string().nullish(),
    turn_status: z
      .enum(["ok", "awaiting_approval", "budget_exceeded", "error", "cancelled"])
      .nullish(),
  })
  .strict();

const ErrorRuntimeEventSchema = z
  .object({
    type: z.literal("error"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    error: z.string(),
  })
  .strict();

const WorkflowStepStartedRuntimeEventSchema = z
  .object({
    type: z.literal("workflow_step_started"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    workflow_id: z.string(),
    run_id: z.string(),
    step_id: z.string(),
    step_index: z.number().int().min(1),
    total_steps: z.number().int().min(1),
    label: z.string().nullish(),
    attempt: z.number().int().min(1).default(1),
  })
  .strict();

const WorkflowStepEndedRuntimeEventSchema = z
  .object({
    type: z.literal("workflow_step_ended"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    workflow_id: z.string(),
    run_id: z.string(),
    step_id: z.string(),
    step_index: z.number().int().min(1),
    total_steps: z.number().int().min(1),
    duration_ms: z.number().int().min(0),
    outputs: jsonObjectSchema.nullish(),
  })
  .strict();

const WorkflowStepFailedRuntimeEventSchema = z
  .object({
    type: z.literal("workflow_step_failed"),
    schema_version: schemaVersionField,
    request_id: requestIdField,
    event_index: eventIndexField,
    workflow_id: z.string(),
    run_id: z.string(),
    step_id: z.string(),
    step_index: z.number().int().min(1),
    total_steps: z.number().int().min(1),
    duration_ms: z.number().int().min(0),
    error: z.string(),
    failure_policy: z.enum([
      "fail_workflow",
      "block_workflow",
      "continue_with_warning",
    ]),
    attempt: z.number().int().min(1).default(1),
  })
  .strict();

export const RuntimeEventSchema = z.discriminatedUnion("type", [
  RetrievalRuntimeEventSchema,
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
  DoneRuntimeEventSchema,
  ErrorRuntimeEventSchema,
  WorkflowStepStartedRuntimeEventSchema,
  WorkflowStepEndedRuntimeEventSchema,
  WorkflowStepFailedRuntimeEventSchema,
]);

export type RuntimeEvent = z.infer<typeof RuntimeEventSchema>;

export const RUNTIME_EVENT_SCHEMAS: Record<
  RuntimeEventType,
  z.ZodTypeAny
> = {
  retrieval: RetrievalRuntimeEventSchema,
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
  done: DoneRuntimeEventSchema,
  error: ErrorRuntimeEventSchema,
  workflow_step_started: WorkflowStepStartedRuntimeEventSchema,
  workflow_step_ended: WorkflowStepEndedRuntimeEventSchema,
  workflow_step_failed: WorkflowStepFailedRuntimeEventSchema,
};

export type RuntimeEventParseSuccess = {
  ok: true;
  event: RuntimeEvent;
};

export type RuntimeEventParseFailure = {
  ok: false;
  error: string;
};

export type RuntimeEventParseResult =
  | RuntimeEventParseSuccess
  | RuntimeEventParseFailure;

export function parseRuntimeEvent(payload: unknown): RuntimeEventParseResult {
  const result = RuntimeEventSchema.safeParse(payload);
  if (result.success) {
    return { ok: true, event: result.data };
  }

  const issues = result.error.issues
    .map((issue) => {
      const path = issue.path.length > 0 ? issue.path.join(".") : "(root)";
      return `${path}: ${issue.message}`;
    })
    .join("; ");

  return {
    ok: false,
    error: issues || "Malformed runtime event payload.",
  };
}
