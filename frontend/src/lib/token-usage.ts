import type { Message, SessionContentBlock, TokenStats } from "./types";

export type UsageSummaryOrigin = "tracked" | "tracked_live" | "estimated";

export interface UsageSummary {
  stats: TokenStats;
  origin: UsageSummaryOrigin;
}

function estimateTextTokens(text: string): number {
  const normalized = text.trim();
  if (!normalized) {
    return 0;
  }

  const parts = normalized.match(/[A-Za-z0-9_]+|[^\sA-Za-z0-9_]/g) ?? [];
  return parts.reduce((total, part) => {
    if (/^[A-Za-z0-9_]+$/.test(part)) {
      return total + Math.max(1, Math.ceil(part.length / 4));
    }
    return total + 1;
  }, 0);
}

function textFromBlocks(blocks: SessionContentBlock[] | undefined): string {
  return (blocks ?? [])
    .filter((block): block is Extract<SessionContentBlock, { type: "text" }> => block.type === "text")
    .map((block) => block.text)
    .join("");
}

function messageText(message: Message): string {
  if (message.content.trim()) {
    return message.content;
  }
  return textFromBlocks(message.blocks);
}

function sumToolTokens(messages: Message[]): number {
  return messages.reduce((total, message) => {
    const completed = (message.tool_calls ?? []).reduce(
      (callTotal, call) =>
        callTotal + estimateTextTokens(call.input) + estimateTextTokens(call.output),
      0
    );
    const pending = message.pendingTool
      ? estimateTextTokens(message.pendingTool.input)
      : 0;
    return total + completed + pending;
  }, 0);
}

export function estimateUsageFromMessages(
  sessionId: string,
  messages: Message[],
  options?: {
    contextWindowTokens?: number | null;
    modelName?: string | null;
  }
): TokenStats {
  const inputTokens = messages.reduce(
    (total, message) =>
      total + (message.role === "user" ? estimateTextTokens(messageText(message)) : 0),
    0
  );
  const outputTokens = messages.reduce(
    (total, message) =>
      total + (message.role === "assistant" ? estimateTextTokens(messageText(message)) : 0),
    0
  );
  const toolTokens = sumToolTokens(messages);
  const totalTokens = inputTokens + outputTokens;
  const contextWindowTokens = options?.contextWindowTokens ?? null;

  return {
    session_id: sessionId,
    system_tokens: 0,
    message_tokens: totalTokens,
    total_tokens: totalTokens,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    tool_tokens: toolTokens,
    tracked_total_tokens: totalTokens + toolTokens,
    context_window_tokens: contextWindowTokens,
    context_window_remaining_tokens:
      typeof contextWindowTokens === "number"
        ? Math.max(contextWindowTokens - totalTokens, 0)
        : null,
    model_name: options?.modelName?.trim() || "Not reported",
    tokenizer_backend: "deterministic_fallback",
    tokenizer_accuracy: "approximate",
  };
}

export function summarizeSessionUsage(params: {
  sessionId: string | null;
  messages: Message[];
  exactTokens: TokenStats | null;
  exactMessageCount: number;
}): UsageSummary | null {
  const { exactMessageCount, exactTokens, messages, sessionId } = params;
  if (!sessionId) {
    return null;
  }

  if (!exactTokens || exactTokens.session_id !== sessionId) {
    return {
      stats: estimateUsageFromMessages(sessionId, messages),
      origin: "estimated",
    };
  }

  const liveMessages =
    exactMessageCount < messages.length ? messages.slice(exactMessageCount) : [];
  if (liveMessages.length === 0) {
    return {
      stats: exactTokens,
      origin: "tracked",
    };
  }

  const liveEstimate = estimateUsageFromMessages(sessionId, liveMessages, {
    contextWindowTokens: exactTokens.context_window_tokens,
    modelName: exactTokens.model_name,
  });
  const totalTokens = exactTokens.total_tokens + liveEstimate.total_tokens;

  return {
    origin: "tracked_live",
    stats: {
      ...exactTokens,
      message_tokens: totalTokens - exactTokens.system_tokens,
      total_tokens: totalTokens,
      input_tokens: exactTokens.input_tokens + liveEstimate.input_tokens,
      output_tokens: exactTokens.output_tokens + liveEstimate.output_tokens,
      tool_tokens: exactTokens.tool_tokens + liveEstimate.tool_tokens,
      tracked_total_tokens:
        exactTokens.tracked_total_tokens + liveEstimate.tracked_total_tokens,
      context_window_remaining_tokens:
        typeof exactTokens.context_window_tokens === "number"
          ? Math.max(exactTokens.context_window_tokens - totalTokens, 0)
          : null,
      tokenizer_accuracy: "approximate",
    },
  };
}
