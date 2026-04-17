import { parseRuntimeEvent } from "./runtime-events";
import type {
  ChatStreamEvent,
  ChatStreamParseErrorEvent,
  JsonObject,
  RetrievalResult,
  ToolResultEnvelope,
} from "./types";

interface ParsedChatStreamChunk {
  bufferedRemainder: string;
  events: ChatStreamEvent[];
}

interface ParseChatStreamChunkOptions {
  flush?: boolean;
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

/**
 * Route an already-decoded payload through the RuntimeEvent zod schema and
 * shape the result into the `ChatStreamEvent` union the app already consumes.
 *
 * Malformed payloads become a synthetic `parse_error` stream event so the app
 * can surface the failure instead of silently dropping it — that matches the
 * issue-21 acceptance criterion.
 */
export function parseChatStreamEventPayload(payload: unknown): ChatStreamEvent {
  const parsed = parseRuntimeEvent(payload);
  if (!parsed.ok) {
    return buildParseErrorEvent(parsed.error, payload);
  }

  const event = parsed.event;
  const requestId = readOptionalString(event.request_id);
  const eventIndex = readOptionalEventIndex(event.event_index);
  const base = {
    request_id: requestId,
    event_index: eventIndex,
  };

  switch (event.type) {
    case "retrieval":
      return {
        type: "retrieval",
        query: event.query,
        results: event.results as unknown as RetrievalResult[],
        ...base,
      };
    case "token":
      return {
        type: "token",
        content: event.content,
        ...base,
      };
    case "tool_start":
      return {
        type: "tool_start",
        tool: event.tool,
        input: event.input,
        run_id: event.run_id,
        ...base,
      };
    case "tool_end":
      return {
        type: "tool_end",
        tool: event.tool,
        output: event.output,
        run_id: event.run_id,
        result: (event.result ?? undefined) as ToolResultEnvelope | undefined,
        policy: (event.policy ?? undefined) as JsonObject | undefined,
        ...base,
      };
    case "plan_created":
      return {
        type: "plan_created",
        summary: event.summary,
        plan: event.plan as JsonObject,
        run_id: event.run_id ?? undefined,
        tool_trace: (event.tool_trace ?? undefined) as JsonObject[] | undefined,
        ...base,
      };
    case "plan_updated":
      return {
        type: "plan_updated",
        summary: event.summary,
        plan: event.plan as JsonObject,
        run_id: event.run_id ?? undefined,
        tool_trace: (event.tool_trace ?? undefined) as JsonObject[] | undefined,
        ...base,
      };
    case "verification_result":
      return {
        type: "verification_result",
        summary: event.summary,
        verdict: event.verdict,
        verification: event.verification as JsonObject,
        run_id: event.run_id ?? undefined,
        tool_trace: (event.tool_trace ?? undefined) as JsonObject[] | undefined,
        ...base,
      };
    case "new_response":
      return { type: "new_response", ...base };
    case "done":
      return {
        type: "done",
        content: event.content,
        session_id: event.session_id ?? undefined,
        ...base,
      };
    case "error":
      return {
        type: "error",
        error: event.error,
        ...base,
      };
  }
}

function buildParseErrorEvent(
  message: string,
  payload: unknown
): ChatStreamParseErrorEvent {
  const envelope =
    typeof payload === "object" && payload !== null
      ? (payload as Record<string, unknown>)
      : undefined;
  const event: ChatStreamParseErrorEvent = {
    type: "parse_error",
    error: message,
    request_id: readOptionalString(envelope?.request_id),
    event_index: readOptionalEventIndex(envelope?.event_index),
  };
  try {
    const raw = JSON.stringify(payload);
    if (typeof raw === "string") {
      event.raw = raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw;
    }
  } catch {
    // payload had a cycle or BigInt — omit raw.
  }
  return event;
}

export function parseChatStreamChunk(
  previousBuffer: string,
  decodedChunk: string,
  options: ParseChatStreamChunkOptions = {}
): ParsedChatStreamChunk {
  const rawBuffer = previousBuffer + decodedChunk;
  const rawEvents = rawBuffer.split("\n\n");
  const bufferedRemainder = rawEvents.pop() ?? "";
  const events: ChatStreamEvent[] = [];

  const eventsToParse =
    options.flush && bufferedRemainder.trim().length > 0
      ? [...rawEvents, bufferedRemainder]
      : rawEvents;

  for (const rawEvent of eventsToParse) {
    for (const line of rawEvent.split("\n")) {
      if (!line.startsWith("data: ")) {
        continue;
      }

      const dataLine = line.slice(6);
      let parsed: unknown;
      try {
        parsed = JSON.parse(dataLine);
      } catch {
        events.push({
          type: "parse_error",
          error: "SSE chunk was not valid JSON.",
          raw: dataLine.length > 2000 ? `${dataLine.slice(0, 2000)}…` : dataLine,
        });
        continue;
      }
      events.push(parseChatStreamEventPayload(parsed));
    }
  }

  return {
    bufferedRemainder:
      options.flush && bufferedRemainder.trim().length > 0
        ? ""
        : bufferedRemainder,
    events,
  };
}
