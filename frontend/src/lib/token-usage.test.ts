import { describe, expect, it } from "vitest";
import type { Message, TokenStats } from "./types";
import {
  estimateUsageFromMessages,
  summarizeSessionUsage,
} from "./token-usage";

function makeMessage(overrides: Partial<Message>): Message {
  return {
    id: overrides.id ?? "message-1",
    role: overrides.role ?? "assistant",
    content: overrides.content ?? "",
    tool_calls: overrides.tool_calls ?? [],
    blocks: overrides.blocks ?? [],
    ...overrides,
  };
}

function makeTrackedUsage(overrides: Partial<TokenStats> = {}): TokenStats {
  return {
    session_id: "session-alpha",
    system_tokens: 200,
    message_tokens: 600,
    total_tokens: 800,
    input_tokens: 500,
    output_tokens: 300,
    tool_tokens: 120,
    tracked_total_tokens: 920,
    context_window_tokens: 4000,
    context_window_remaining_tokens: 3200,
    model_name: "gpt-5.4",
    tokenizer_backend: "tiktoken_cl100k_base",
    tokenizer_accuracy: "model_aligned",
    ...overrides,
  };
}

describe("token usage helpers", () => {
  it("estimates transcript and tool usage from messages", () => {
    const stats = estimateUsageFromMessages("session-alpha", [
      makeMessage({
        id: "user-1",
        role: "user",
        content: "Plan the BRCA1 review.",
      }),
      makeMessage({
        id: "assistant-1",
        role: "assistant",
        content: "I reviewed the latest evidence.",
        tool_calls: [
          {
            tool: "read_file",
            input: "knowledge/brca1.md",
            output: "Loaded BRCA1 notes.",
          },
        ],
      }),
    ]);

    expect(stats.session_id).toBe("session-alpha");
    expect(stats.input_tokens).toBeGreaterThan(0);
    expect(stats.output_tokens).toBeGreaterThan(0);
    expect(stats.tool_tokens).toBeGreaterThan(0);
    expect(stats.tracked_total_tokens).toBe(
      stats.input_tokens + stats.output_tokens + stats.tool_tokens
    );
    expect(stats.tokenizer_accuracy).toBe("approximate");
  });

  it("merges tracked session usage with a live in-flight request estimate", () => {
    const summary = summarizeSessionUsage({
      sessionId: "session-alpha",
      exactTokens: makeTrackedUsage(),
      exactMessageCount: 2,
      messages: [
        makeMessage({
          id: "user-old",
          role: "user",
          content: "Previous request.",
        }),
        makeMessage({
          id: "assistant-old",
          role: "assistant",
          content: "Previous answer.",
        }),
        makeMessage({
          id: "user-live",
          role: "user",
          content: "Current streamed request.",
        }),
        makeMessage({
          id: "assistant-live",
          role: "assistant",
          content: "Current streamed answer.",
          pendingTool: {
            tool: "read_file",
            input: "knowledge/current.md",
            runId: "tool-live",
          },
        }),
      ],
    });

    expect(summary?.origin).toBe("tracked_live");
    expect(summary?.stats.session_id).toBe("session-alpha");
    expect(summary?.stats.tracked_total_tokens).toBeGreaterThan(920);
    expect(summary?.stats.total_tokens).toBeGreaterThan(800);
    expect(summary?.stats.tokenizer_accuracy).toBe("approximate");
    expect(summary?.stats.context_window_remaining_tokens).toBeLessThan(3200);
  });
});
