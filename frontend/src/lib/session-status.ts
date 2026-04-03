import type { Message, ToolCall } from "./types";

export type ReadinessState = "ready" | "reviewing" | "warning" | "blocked";

export interface ReadinessSummary {
  state: ReadinessState;
  label: string;
  detail: string | null;
}

function humanizeWarning(value: string): string {
  return value.replaceAll("_", " ");
}

function firstMeaningfulText(values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    const trimmed = value?.trim();
    if (trimmed) {
      return trimmed;
    }
  }

  return null;
}

export function getReadinessSummary(
  messages: Message[],
  options?: {
    isStreaming?: boolean;
  }
): ReadinessSummary {
  const latestRequestMessages = getLatestRequestMessages(messages);
  const latestRequestSummary = summarizeReadinessFromMessages(latestRequestMessages);

  if (latestRequestSummary) {
    return latestRequestSummary;
  }

  if (options?.isStreaming) {
    return {
      state: "reviewing",
      label: "Reviewing",
      detail: "Evaluating the latest request.",
    };
  }

  return {
    state: "ready",
    label: "Ready",
    detail: "No active warnings in this workspace.",
  };
}

export function getLatestRequestMessages(messages: Message[]): Message[] {
  const latestAssistantBlock = getLatestAssistantBlock(messages);

  if (latestAssistantBlock.some((message) => !message.request_id)) {
    return latestAssistantBlock;
  }

  const latestRequestId = findLatestRequestId(messages);

  if (latestRequestId) {
    return messages.filter((message) => message.request_id === latestRequestId);
  }

  return latestAssistantBlock;
}

function findLatestRequestId(messages: Message[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const requestId = messages[index]?.request_id;
    if (requestId) {
      return requestId;
    }
  }

  return null;
}

function getLatestAssistantBlock(messages: Message[]): Message[] {
  let end = -1;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") {
      end = index;
      break;
    }
  }

  if (end === -1) {
    return [];
  }

  let start = end;
  while (start - 1 >= 0 && messages[start - 1]?.role === "assistant") {
    start -= 1;
  }

  return messages.slice(start, end + 1);
}

function getToolCallsNewestFirst(messages: Message[]): ToolCall[] {
  const calls: ToolCall[] = [];

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const toolCalls = messages[messageIndex]?.tool_calls ?? [];
    for (let callIndex = toolCalls.length - 1; callIndex >= 0; callIndex -= 1) {
      calls.push(toolCalls[callIndex]);
    }
  }

  return calls;
}

function summarizeReadinessFromMessages(messages: Message[]): ReadinessSummary | null {
  for (const call of getToolCallsNewestFirst(messages)) {
    const summary = summarizeReadinessFromToolCall(call);
    if (summary) {
      return summary;
    }
  }

  return null;
}

function summarizeReadinessFromToolCall(call: ToolCall): ReadinessSummary | null {
  const result = call.result;
  if (!result) return null;

  const warnings = result.warnings ?? [];
  const blockingWarning = warnings.find(
    (warning) => warning.includes("blocked") || warning.includes("violation")
  );
  if (result.status === "error" || blockingWarning) {
    return {
      state: "blocked",
      label: "Blocked",
      detail:
        firstMeaningfulText([
          result.error?.message,
          blockingWarning ? `Latest action was blocked: ${humanizeWarning(blockingWarning)}.` : null,
        ]) ?? "The latest action did not complete.",
    };
  }

  if (warnings.length > 0 || result.outcome === "success_empty") {
    return {
      state: "warning",
      label: "Attention",
      detail:
        firstMeaningfulText([
          result.summary,
          warnings[0] ? `Latest action finished with ${humanizeWarning(warnings[0])}.` : null,
          result.outcome === "success_empty" ? "Latest action completed without new material." : null,
        ]) ?? "Latest action finished with warnings.",
    };
  }

  if (result.status === "success" || result.outcome === "success") {
    return {
      state: "ready",
      label: "Ready",
      detail:
        firstMeaningfulText([result.summary]) ??
        "Latest action completed without active warnings.",
    };
  }

  return null;
}
