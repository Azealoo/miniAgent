/**
 * Transport-neutral RuntimeEvent schema — frontend zod mirror.
 *
 * The zod schemas and discriminated union live in the auto-generated
 * `./runtime-events.generated.ts` (emitted by `scripts/codegen-types.ts` from
 * `backend/runtime/events.schema.json`). This file re-exports them and
 * supplies the `parseRuntimeEvent` helper that every SSE payload flows
 * through. To add or alter an event, change `backend/runtime/events.py`,
 * regenerate the JSON snapshot (`pytest backend/tests/test_runtime_events.py`)
 * and the TS/zod outputs (`npm run codegen:types` from `frontend/`).
 *
 * SSE is the current adapter in `api.ts`, but any stdin/WebSocket consumer can
 * reuse `parseRuntimeEvent` to validate an incoming payload.
 */
import {
  ChatStreamEventSchema,
  RuntimeEventSchema,
  type RuntimeEvent,
} from "./runtime-events.generated";

export {
  ChatStreamEventSchema,
  RuntimeEventSchema,
  RUNTIME_EVENT_SCHEMAS,
  RUNTIME_EVENT_SCHEMA_VERSION,
  RUNTIME_EVENT_TYPES,
  TURN_EXIT_REASONS,
  TurnExitSchema,
  COMPACTION_PHASES,
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
} from "./runtime-events.generated";

export type {
  ChatStreamEvent,
  RuntimeEvent,
  RuntimeEventType,
  TurnExit,
  TurnExitReason,
  CompactionPhase,
} from "./runtime-events.generated";

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

// Reference the imported symbol so the top-level import isn't pruned as
// unused-for-side-effects; also exposes ChatStreamEventSchema as the canonical
// alias for future call sites that prefer the issue-#105 naming.
void ChatStreamEventSchema;
