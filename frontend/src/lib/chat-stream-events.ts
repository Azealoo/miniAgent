import { parseRuntimeEvent } from "./runtime-events";
import { parseSseChunk } from "./sse-parser";
import type {
  ChatStreamEvent,
  ChatStreamParseErrorEvent,
  ChatStreamPlanCreatedEvent,
  ChatStreamPlanUpdatedEvent,
  ChatStreamVerificationResultEvent,
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
    case "tool_awaiting_approval":
      return {
        type: "tool_awaiting_approval",
        tool: event.tool,
        input: event.input,
        run_id: event.run_id,
        reason: event.reason,
        message: event.message,
        result: (event.result ?? undefined) as ToolResultEnvelope | undefined,
        policy: (event.policy ?? undefined) as JsonObject | undefined,
        ...base,
      };
    case "tool_chunk":
      return {
        type: "tool_chunk",
        tool: event.tool,
        run_id: event.run_id,
        chunk_index: event.chunk_index,
        chunk: event.chunk,
        terminal: event.terminal,
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
    case "compaction_event":
      return {
        type: "compaction_event",
        from_turn: event.from_turn,
        to_turn: event.to_turn,
        summary: event.summary,
        saved_tokens: event.saved_tokens,
        ...base,
      };
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

/**
 * Turn a single raw `data:` payload string into a `ChatStreamEvent`, including
 * the JSON.parse step. Malformed JSON becomes a `parse_error` event rather
 * than being silently dropped.
 */
export function parseChatStreamDataPayload(data: string): ChatStreamEvent {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return {
      type: "parse_error",
      error: "SSE chunk was not valid JSON.",
      raw: data.length > 2000 ? `${data.slice(0, 2000)}…` : data,
    };
  }
  return parseChatStreamEventPayload(parsed);
}

export function parseChatStreamChunk(
  previousBuffer: string,
  decodedChunk: string,
  options: ParseChatStreamChunkOptions = {}
): ParsedChatStreamChunk {
  const { bufferedRemainder, payloads } = parseSseChunk(
    previousBuffer,
    decodedChunk,
    options
  );
  return {
    bufferedRemainder,
    events: payloads.map(parseChatStreamDataPayload),
  };
}

export interface StreamCallbacks {
  signal?: AbortSignal;
  onEvent?: (event: ChatStreamEvent) => void;
  onRetrieval?: (query: string, results: RetrievalResult[]) => void;
  onToken?: (content: string) => void;
  onToolStart?: (
    tool: string,
    input: string,
    runId: string,
    requestId?: string
  ) => void;
  onToolEnd?: (
    tool: string,
    output: string,
    runId: string,
    result?: ToolResultEnvelope,
    requestId?: string
  ) => void;
  onPlanCreated?: (event: ChatStreamPlanCreatedEvent) => void;
  onPlanUpdated?: (event: ChatStreamPlanUpdatedEvent) => void;
  onVerificationResult?: (event: ChatStreamVerificationResultEvent) => void;
  onNewResponse?: () => void;
  onDone?: (content: string, requestId?: string) => void;
  onError?: (error: string, requestId?: string) => void;
  /**
   * Called when an incoming SSE payload fails RuntimeEvent validation. The
   * stream keeps running — malformed events are surfaced, not terminal.
   */
  onParseError?: (event: ChatStreamParseErrorEvent) => void;
}

export interface ChatStreamDispatcher {
  dispatch: (event: ChatStreamEvent) => void;
  sawTerminalEvent: () => boolean;
  lastRequestId: () => string | undefined;
}

/**
 * Build a dispatcher that fans a `ChatStreamEvent` out to the matching
 * `StreamCallbacks` and tracks whether a terminal event has been seen. The
 * transport layer in `api.ts` uses this so it can stay focused on the fetch
 * + reader loop.
 */
export function createChatStreamDispatcher(
  callbacks: StreamCallbacks
): ChatStreamDispatcher {
  let sawTerminalEvent = false;
  let lastRequestId: string | undefined;

  const dispatch = (event: ChatStreamEvent) => {
    if (event.request_id) {
      lastRequestId = event.request_id;
    }
    if (event.type === "done" || event.type === "error") {
      sawTerminalEvent = true;
    }

    callbacks.onEvent?.(event);
    switch (event.type) {
      case "retrieval":
        callbacks.onRetrieval?.(event.query, event.results);
        break;
      case "token":
        callbacks.onToken?.(event.content);
        break;
      case "tool_start":
        callbacks.onToolStart?.(
          event.tool,
          event.input,
          event.run_id ?? event.tool,
          event.request_id
        );
        break;
      case "tool_end":
        callbacks.onToolEnd?.(
          event.tool,
          event.output,
          event.run_id ?? event.tool,
          event.result,
          event.request_id
        );
        break;
      case "plan_created":
        callbacks.onPlanCreated?.(event);
        break;
      case "plan_updated":
        callbacks.onPlanUpdated?.(event);
        break;
      case "verification_result":
        callbacks.onVerificationResult?.(event);
        break;
      case "new_response":
        callbacks.onNewResponse?.();
        break;
      case "done":
        callbacks.onDone?.(event.content, event.request_id);
        break;
      case "error":
        callbacks.onError?.(event.error, event.request_id);
        break;
      case "parse_error":
        callbacks.onParseError?.(event);
        break;
    }
  };

  return {
    dispatch,
    sawTerminalEvent: () => sawTerminalEvent,
    lastRequestId: () => lastRequestId,
  };
}
