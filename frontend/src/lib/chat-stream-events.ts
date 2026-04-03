import type {
  ChatStreamDoneEvent,
  ChatStreamErrorEvent,
  ChatStreamEvent,
  ChatStreamNewResponseEvent,
  ChatStreamPlanCreatedEvent,
  ChatStreamPlanUpdatedEvent,
  ChatStreamRetrievalEvent,
  ChatStreamTokenEvent,
  ChatStreamToolEndEvent,
  ChatStreamToolStartEvent,
  ChatStreamVerificationResultEvent,
  JsonObject,
  RetrievalResult,
  ToolResultEnvelope,
} from "./types";

interface ParsedChatStreamChunk {
  bufferedRemainder: string;
  events: ChatStreamEvent[];
}

type UnknownRecord = Record<string, unknown>;

function isObjectRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readOptionalEventIndex(value: unknown): number | undefined {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    return undefined;
  }
  return value;
}

function readObject(value: unknown): JsonObject | null {
  return isObjectRecord(value) ? (value as JsonObject) : null;
}

function readObjectArray(value: unknown): JsonObject[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const objects = value.filter(isObjectRecord);
  return objects.length === value.length ? (objects as JsonObject[]) : undefined;
}

function readRetrievalResult(value: unknown): RetrievalResult | null {
  if (!isObjectRecord(value)) {
    return null;
  }

  const text = readString(value.text);
  const source = readString(value.source);
  const score = typeof value.score === "number" ? value.score : null;
  if (text === null || source === null || score === null || Number.isNaN(score)) {
    return null;
  }

  const result: RetrievalResult = { text, source, score };
  const memoryType = readOptionalString(value.memory_type);
  const memoryTypeLabel = readOptionalString(value.memory_type_label);
  const memoryName = readOptionalString(value.memory_name);
  const memoryDescription = readOptionalString(value.memory_description);

  if (memoryType !== undefined) {
    result.memory_type = memoryType;
  }
  if (memoryTypeLabel !== undefined) {
    result.memory_type_label = memoryTypeLabel;
  }
  if (memoryName !== undefined) {
    result.memory_name = memoryName;
  }
  if (memoryDescription !== undefined) {
    result.memory_description = memoryDescription;
  }

  return result;
}

function readRetrievalResults(value: unknown): RetrievalResult[] | null {
  if (!Array.isArray(value)) {
    return null;
  }

  const results = value.map(readRetrievalResult);
  return results.every((result): result is RetrievalResult => result !== null)
    ? results
    : null;
}

function readToolResultEnvelope(value: unknown): ToolResultEnvelope | undefined {
  return isObjectRecord(value) ? (value as unknown as ToolResultEnvelope) : undefined;
}

function parseRetrievalEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamRetrievalEvent | null {
  const query = readString(payload.query);
  const results = readRetrievalResults(payload.results);
  if (query === null || results === null) {
    return null;
  }
  return {
    type: "retrieval",
    query,
    results,
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseTokenEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamTokenEvent | null {
  const content = readString(payload.content);
  if (content === null) {
    return null;
  }
  return {
    type: "token",
    content,
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseToolStartEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamToolStartEvent | null {
  const tool = readString(payload.tool);
  const input = readString(payload.input);
  if (tool === null || input === null) {
    return null;
  }
  return {
    type: "tool_start",
    tool,
    input,
    run_id: readOptionalString(payload.run_id),
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseToolEndEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamToolEndEvent | null {
  const tool = readString(payload.tool);
  const output = readString(payload.output);
  if (tool === null || output === null) {
    return null;
  }
  return {
    type: "tool_end",
    tool,
    output,
    run_id: readOptionalString(payload.run_id),
    result: readToolResultEnvelope(payload.result),
    policy: readObject(payload.policy) ?? undefined,
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parsePlanCreatedEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamPlanCreatedEvent | null {
  const summary = readString(payload.summary);
  const plan = readObject(payload.plan);
  if (summary === null || plan === null) {
    return null;
  }
  return {
    type: "plan_created",
    summary,
    plan,
    run_id: readOptionalString(payload.run_id),
    tool_trace: readObjectArray(payload.tool_trace),
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parsePlanUpdatedEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamPlanUpdatedEvent | null {
  const summary = readString(payload.summary);
  const plan = readObject(payload.plan);
  if (summary === null || plan === null) {
    return null;
  }
  return {
    type: "plan_updated",
    summary,
    plan,
    run_id: readOptionalString(payload.run_id),
    tool_trace: readObjectArray(payload.tool_trace),
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseVerificationResultEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamVerificationResultEvent | null {
  const summary = readString(payload.summary);
  const verdict = readString(payload.verdict);
  const verification = readObject(payload.verification);
  if (
    summary === null ||
    verification === null ||
    (verdict !== "pass" && verdict !== "repair_required" && verdict !== "fail")
  ) {
    return null;
  }
  return {
    type: "verification_result",
    summary,
    verdict,
    verification,
    run_id: readOptionalString(payload.run_id),
    tool_trace: readObjectArray(payload.tool_trace),
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseNewResponseEvent(
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamNewResponseEvent {
  return {
    type: "new_response",
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseDoneEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamDoneEvent {
  return {
    type: "done",
    content: readString(payload.content) ?? "",
    session_id: readOptionalString(payload.session_id),
    request_id: requestId,
    event_index: eventIndex,
  };
}

function parseErrorEvent(
  payload: UnknownRecord,
  requestId: string | undefined,
  eventIndex: number | undefined
): ChatStreamErrorEvent {
  return {
    type: "error",
    error: readString(payload.error) ?? "Unknown error",
    request_id: requestId,
    event_index: eventIndex,
  };
}

export function parseChatStreamEventPayload(payload: unknown): ChatStreamEvent | null {
  if (!isObjectRecord(payload)) {
    return null;
  }

  const eventType = readString(payload.type);
  const requestId = readOptionalString(payload.request_id);
  const eventIndex = readOptionalEventIndex(payload.event_index);
  if (eventType === null) {
    return null;
  }

  switch (eventType) {
    case "retrieval":
      return parseRetrievalEvent(payload, requestId, eventIndex);
    case "token":
      return parseTokenEvent(payload, requestId, eventIndex);
    case "tool_start":
      return parseToolStartEvent(payload, requestId, eventIndex);
    case "tool_end":
      return parseToolEndEvent(payload, requestId, eventIndex);
    case "plan_created":
      return parsePlanCreatedEvent(payload, requestId, eventIndex);
    case "plan_updated":
      return parsePlanUpdatedEvent(payload, requestId, eventIndex);
    case "verification_result":
      return parseVerificationResultEvent(payload, requestId, eventIndex);
    case "new_response":
      return parseNewResponseEvent(requestId, eventIndex);
    case "done":
      return parseDoneEvent(payload, requestId, eventIndex);
    case "error":
      return parseErrorEvent(payload, requestId, eventIndex);
    default:
      return null;
  }
}

export function parseChatStreamChunk(
  previousBuffer: string,
  decodedChunk: string
): ParsedChatStreamChunk {
  const rawBuffer = previousBuffer + decodedChunk;
  const rawEvents = rawBuffer.split("\n\n");
  const bufferedRemainder = rawEvents.pop() ?? "";
  const events: ChatStreamEvent[] = [];

  for (const rawEvent of rawEvents) {
    for (const line of rawEvent.split("\n")) {
      if (!line.startsWith("data: ")) {
        continue;
      }

      try {
        const parsed = JSON.parse(line.slice(6));
        const event = parseChatStreamEventPayload(parsed);
        if (event) {
          events.push(event);
        }
      } catch {
        continue;
      }
    }
  }

  return {
    bufferedRemainder,
    events,
  };
}
