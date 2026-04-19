import type {
  ChatStreamDoneEvent,
  ChatStreamErrorEvent,
  ChatStreamEvent,
  ChatStreamWorkflowStepEndedEvent,
  ChatStreamWorkflowStepFailedEvent,
  ChatStreamWorkflowStepStartedEvent,
  Message,
  RetrievalResult,
  SessionContentBlock,
  WorkflowStepState,
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
        const runId = event.run_id ?? event.tool;
        const buffered = takeChunkBuffer(message.toolChunkBuffers, runId);

        return {
          ...message,
          request_id: event.request_id ?? message.request_id,
          blocks: appendSessionBlock(message.blocks, {
            type: "tool_result",
            tool: pending?.tool ?? event.tool,
            output:
              buffered.text.length > 0 && !event.output.includes(buffered.text)
                ? buffered.text + event.output
                : event.output,
            run_id: runId,
            result: event.result,
          }),
          pendingTool: undefined,
          toolChunkBuffers: buffered.next,
        };
      });
    case "tool_awaiting_approval":
      return updateStreamingMessage(state, event, (message) => {
        const pending =
          message.pendingTool?.runId === event.run_id
            ? message.pendingTool
            : null;
        return {
          ...message,
          request_id: event.request_id ?? message.request_id,
          blocks: appendSessionBlock(message.blocks, {
            type: "approval_gate",
            tool: pending?.tool ?? event.tool,
            input: pending?.input ?? event.input,
            run_id: event.run_id,
            reason: event.reason,
            message: event.message,
            result: event.result,
            policy: event.policy,
          }),
          pendingTool: undefined,
        };
      });
    case "tool_chunk":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        toolChunkBuffers: appendChunkToBuffer(
          message.toolChunkBuffers,
          event.run_id,
          event.chunk_index,
          event.chunk
        ),
      }));
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
    case "workflow_step_started":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        workflowSteps: applyWorkflowStepStarted(message.workflowSteps, event),
      }));
    case "workflow_step_ended":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        workflowSteps: applyWorkflowStepEnded(message.workflowSteps, event),
      }));
    case "workflow_step_failed":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        workflowSteps: applyWorkflowStepFailed(message.workflowSteps, event),
      }));
    case "new_response":
      return reduceNewResponseEvent(state, event, options);
    case "compaction_event":
      return {
        messages: state.messages,
        streamingMessageId: state.streamingMessageId,
        finished: false,
      };
    case "warning":
      return updateStreamingMessage(state, event, (message) => ({
        ...message,
        request_id: event.request_id ?? message.request_id,
        blocks: appendSessionBlock(message.blocks, {
          type: "warning",
          kind: event.kind,
          message: event.message,
          missing: event.missing,
          cited: event.cited,
          included: event.included,
          review_path: event.review_path ?? undefined,
        }),
      }));
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
    case "stream_overflow":
      return reduceErrorEvent(
        state,
        {
          type: "error",
          error: `SSE buffer overflow: ${event.bufferedBytes} bytes exceeded the ${event.maxBufferBytes}-byte cap.`,
          request_id: event.request_id,
          event_index: event.event_index,
        },
        options.now
      );
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
      exit: event.exit ?? message.exit,
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

interface ChunkBufferEntry {
  chunks: { index: number; text: string }[];
}

export type ToolChunkBuffers = Record<string, ChunkBufferEntry>;

function appendChunkToBuffer(
  buffers: ToolChunkBuffers | undefined,
  runId: string,
  chunkIndex: number,
  chunkText: string
): ToolChunkBuffers {
  const next: ToolChunkBuffers = { ...(buffers ?? {}) };
  const existing = next[runId]?.chunks ?? [];
  if (existing.some((entry) => entry.index === chunkIndex)) {
    return next;
  }
  const merged = [...existing, { index: chunkIndex, text: chunkText }].sort(
    (a, b) => a.index - b.index
  );
  next[runId] = { chunks: merged };
  return next;
}

function takeChunkBuffer(
  buffers: ToolChunkBuffers | undefined,
  runId: string
): { text: string; next: ToolChunkBuffers | undefined } {
  if (!buffers || !buffers[runId]) {
    return { text: "", next: buffers };
  }
  const text = buffers[runId].chunks.map((entry) => entry.text).join("");
  const next: ToolChunkBuffers = { ...buffers };
  delete next[runId];
  return {
    text,
    next: Object.keys(next).length > 0 ? next : undefined,
  };
}

function workflowStepKey(runId: string, stepId: string): string {
  return `${runId}:${stepId}`;
}

function upsertWorkflowStep(
  steps: WorkflowStepState[] | undefined,
  next: WorkflowStepState
): WorkflowStepState[] {
  const list = [...(steps ?? [])];
  const key = workflowStepKey(next.run_id, next.step_id);
  const index = list.findIndex(
    (entry) => workflowStepKey(entry.run_id, entry.step_id) === key
  );
  if (index >= 0) {
    list[index] = { ...list[index], ...next };
    return list;
  }
  list.push(next);
  return list;
}

function applyWorkflowStepStarted(
  steps: WorkflowStepState[] | undefined,
  event: ChatStreamWorkflowStepStartedEvent
): WorkflowStepState[] {
  return upsertWorkflowStep(steps, {
    workflow_id: event.workflow_id,
    run_id: event.run_id,
    step_id: event.step_id,
    step_index: event.step_index,
    total_steps: event.total_steps,
    status: "running",
    label: event.label ?? undefined,
    attempt: event.attempt ?? 1,
  });
}

function applyWorkflowStepEnded(
  steps: WorkflowStepState[] | undefined,
  event: ChatStreamWorkflowStepEndedEvent
): WorkflowStepState[] {
  const existing = (steps ?? []).find(
    (entry) =>
      workflowStepKey(entry.run_id, entry.step_id) ===
      workflowStepKey(event.run_id, event.step_id)
  );
  return upsertWorkflowStep(steps, {
    workflow_id: event.workflow_id,
    run_id: event.run_id,
    step_id: event.step_id,
    step_index: event.step_index,
    total_steps: event.total_steps,
    status: "ok",
    label: existing?.label,
    attempt: existing?.attempt ?? 1,
    duration_ms: event.duration_ms,
  });
}

function applyWorkflowStepFailed(
  steps: WorkflowStepState[] | undefined,
  event: ChatStreamWorkflowStepFailedEvent
): WorkflowStepState[] {
  const existing = (steps ?? []).find(
    (entry) =>
      workflowStepKey(entry.run_id, entry.step_id) ===
      workflowStepKey(event.run_id, event.step_id)
  );
  return upsertWorkflowStep(steps, {
    workflow_id: event.workflow_id,
    run_id: event.run_id,
    step_id: event.step_id,
    step_index: event.step_index,
    total_steps: event.total_steps,
    status: "failed",
    label: existing?.label,
    attempt: event.attempt ?? existing?.attempt ?? 1,
    duration_ms: event.duration_ms,
    error: event.error,
    failure_policy: event.failure_policy,
  });
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
