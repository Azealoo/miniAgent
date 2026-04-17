import type {
  ChatStreamDoneEvent,
  ChatStreamErrorEvent,
  ChatStreamEvent,
  Message,
  RetrievalResult,
  SessionContentBlock,
} from "./types";

export interface StreamReducerState {
  messages: Message[];
  streamingMessageId: string | null;
}

export interface StreamReducerOptions {
  createMessageId: () => string;
  now: number;
}

export interface StreamReducerResult extends StreamReducerState {
  finished: boolean;
}

export function createOptimisticAssistantMessage(
  id: string,
  startedAtMs: number,
  requestId?: string
): Message {
  return {
    id,
    role: "assistant",
    content: "",
    request_id: requestId,
    isStreaming: true,
    startedAtMs,
    blocks: [],
  };
}

export function applyStreamEvent(
  state: StreamReducerState,
  event: ChatStreamEvent,
  options: StreamReducerOptions
): StreamReducerResult {
  switch (event.type) {
    case "retrieval":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        blocks: replaceRetrievalBlock(message.blocks, event.query, event.results),
      }));
    case "token":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        content: message.content + event.content,
        blocks: appendTextBlock(message.blocks, event.content),
      }));
    case "tool_start":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        blocks: appendSessionBlock(message.blocks, {
          type: "tool_use",
          tool: event.tool,
          input: event.input,
          run_id: event.run_id ?? event.tool,
        }),
        pendingTool: {
          tool: event.tool,
          input: event.input,
          runId: event.run_id ?? event.tool,
        },
      }));
    case "tool_end":
      return updateStreamingMessage(state, event, (message) => {
        const pending =
          message.pendingTool?.runId === (event.run_id ?? event.tool)
            ? message.pendingTool
            : null;

        return {
          ...message,
          request_id: event.request_id ?? message.request_id,
          blocks: appendSessionBlock(message.blocks, {
            type: "tool_result",
            tool: pending?.tool ?? event.tool,
            output: event.output,
            run_id: event.run_id ?? event.tool,
            result: event.result,
          }),
          pendingTool: undefined,
        };
      });
    case "plan_created":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        blocks: appendSessionBlock(message.blocks, {
          type: "plan",
          event: "created",
          summary: event.summary,
          run_id: event.run_id,
          plan: event.plan,
          tool_trace: event.tool_trace,
        }),
      }));
    case "plan_updated":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        blocks: appendSessionBlock(message.blocks, {
          type: "plan",
          event: "updated",
          summary: event.summary,
          run_id: event.run_id,
          plan: event.plan,
          tool_trace: event.tool_trace,
        }),
      }));
    case "verification_result":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        blocks: appendSessionBlock(message.blocks, {
          type: "verification",
          summary: event.summary,
          verdict: event.verdict,
          run_id: event.run_id,
          verification: event.verification,
          tool_trace: event.tool_trace,
        }),
      }));
    case "new_response":
      return reduceNewResponseEvent(state, event, options);
    case "compaction_event":
      return {
        messages: state.messages,
        streamingMessageId: state.streamingMessageId,
        finished: false,
      };
    case "done":
      return reduceDoneEvent(state, event, options.now);
    case "error":
      return reduceErrorEvent(state, event, options.now);
    case "parse_error":
      // Parse errors are surfaced through onParseError but should not mutate
      // the message tree or end the stream — a single malformed SSE payload
      // must not corrupt an otherwise healthy turn.
      return {
        messages: state.messages,
        streamingMessageId: state.streamingMessageId,
        finished: false,
      };
  }
}

function updateStreamingMessage(
  state: StreamReducerState,
  event: ChatStreamEvent,
  transform: (message: Message) => Message
): StreamReducerResult {
  const messageId = state.streamingMessageId;
  if (!messageId) {
    return {
      messages: state.messages,
      streamingMessageId: state.streamingMessageId,
      finished: false,
    };
  }

  let changed = false;
  const messages = state.messages.map((message) => {
    if (message.id !== messageId) {
      return message;
    }
    changed = true;
    return transform(message);
  });

  return {
    messages: changed ? messages : state.messages,
    streamingMessageId: state.streamingMessageId,
    finished: false,
  };
}

function reduceNewResponseEvent(
  state: StreamReducerState,
  event: Extract<ChatStreamEvent, { type: "new_response" }>,
  options: StreamReducerOptions
): StreamReducerResult {
  const closedMessages = state.streamingMessageId
    ? state.messages.map((message) =>
        message.id === state.streamingMessageId
          ? {
              ...message,
              request_id: event.request_id ?? message.request_id,
              isStreaming: false,
              endedAtMs: options.now,
            }
          : message
      )
    : state.messages;

  const nextMessage = createOptimisticAssistantMessage(
    options.createMessageId(),
    options.now,
    event.request_id
  );

  return {
    messages: [...closedMessages, nextMessage],
    streamingMessageId: nextMessage.id,
    finished: false,
  };
}

function reduceDoneEvent(
  state: StreamReducerState,
  event: ChatStreamDoneEvent,
  now: number
): StreamReducerResult {
  return finalizeStreamingMessage(state, event, now, (message) => {
    const needsContentBackfill = !message.content && Boolean(event.content);
    return {
      ...message,
      request_id: event.request_id ?? message.request_id,
      content: needsContentBackfill ? event.content : message.content,
      blocks: needsContentBackfill
        ? appendTextBlock(message.blocks, event.content)
        : message.blocks,
      isStreaming: false,
      endedAtMs: now,
    };
  });
}

function reduceErrorEvent(
  state: StreamReducerState,
  event: ChatStreamErrorEvent,
  now: number
): StreamReducerResult {
  return finalizeStreamingMessage(state, event, now, (message) => {
    const errorText =
      (message.content ? "\n\n" : "") + `⚠️ Error: ${event.error}`;
    return {
      ...message,
      request_id: event.request_id ?? message.request_id,
      content: message.content + errorText,
      blocks: appendTextBlock(message.blocks, errorText),
      isStreaming: false,
      endedAtMs: now,
    };
  });
}

function finalizeStreamingMessage(
  state: StreamReducerState,
  event: ChatStreamEvent,
  now: number,
  transform: (message: Message) => Message
): StreamReducerResult {
  const messageId = state.streamingMessageId;
  if (!messageId) {
    return {
      messages: state.messages,
      streamingMessageId: null,
      finished: true,
    };
  }

  const messages = state.messages.map((message) =>
    message.id === messageId
      ? transform({
          ...message,
          endedAtMs: now,
        })
      : message
  );

  return {
    messages,
    streamingMessageId: null,
    finished: true,
  };
}

function appendSessionBlock(
  blocks: SessionContentBlock[] | undefined,
  block: SessionContentBlock
): SessionContentBlock[] {
  return [...(blocks ?? []), block];
}

function appendTextBlock(
  blocks: SessionContentBlock[] | undefined,
  text: string
): SessionContentBlock[] {
  const normalized = text ?? "";
  const next = [...(blocks ?? [])];

  if (!normalized) {
    return next;
  }

  const lastBlock = next.at(-1);
  if (lastBlock?.type === "text") {
    next[next.length - 1] = {
      type: "text",
      text: lastBlock.text + normalized,
    };
    return next;
  }

  next.push({
    type: "text",
    text: normalized,
  });
  return next;
}

function replaceRetrievalBlock(
  blocks: SessionContentBlock[] | undefined,
  query: string,
  results: RetrievalResult[] | undefined
): SessionContentBlock[] {
  const next = [...(blocks ?? [])];
  const retrievalBlock: SessionContentBlock = {
    type: "retrieval",
    query,
    results: results ?? [],
  };

  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index]?.type === "retrieval") {
      next[index] = retrievalBlock;
      return next;
    }
  }

  next.push(retrievalBlock);
  return next;
}
