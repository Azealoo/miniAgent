import { describe, expect, it } from "vitest";
import { makeGenericToolResultEnvelope } from "@/test/fixtures";
import {
  applyStreamEvent,
  createOptimisticAssistantMessage,
  type StreamReducerState,
} from "./chat-stream-reducer";
import { getMessageToolCalls } from "./message-blocks";
import type { ChatStreamEvent, Message } from "./types";

function reduceEvent(
  state: StreamReducerState,
  event: ChatStreamEvent,
  now: number
): StreamReducerState {
  return applyStreamEvent(state, event, {
    createMessageId: () => "assistant-2",
    now,
  });
}

describe("applyStreamEvent", () => {
  it("keeps request-id, pending-tool, and new_response semantics on one reducer path", () => {
    const toolResult = makeGenericToolResultEnvelope();
    const userMessage: Message = {
      id: "user-1",
      role: "user",
      content: "Check this request for readiness.",
      blocks: [{ type: "text", text: "Check this request for readiness." }],
    };

    let state: StreamReducerState = {
      messages: [
        userMessage,
        createOptimisticAssistantMessage("assistant-1", 100),
      ],
      streamingMessageId: "assistant-1",
    };

    state = reduceEvent(
      state,
      {
        type: "retrieval",
        query: "readiness review",
        request_id: "request-1",
        results: [
          {
            source: "knowledge/readiness-checklist.md",
            score: 0.92,
            text: "Inspect the readiness checklist before execution.",
          },
        ],
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "tool_start",
        tool: "read_file",
        input: "knowledge/readiness-checklist.md",
        run_id: "tool-1",
        request_id: "request-1",
      },
      120
    );
    state = reduceEvent(
      state,
      {
        type: "tool_end",
        tool: "read_file",
        output: "Read knowledge/readiness-checklist.md.",
        run_id: "tool-1",
        request_id: "request-1",
        result: toolResult,
      },
      130
    );
    state = reduceEvent(
      state,
      {
        type: "plan_created",
        summary: "Planner produced 2 steps.",
        plan: { goal: "Check readiness", steps: [{ step_id: "collect" }, { step_id: "report" }] },
        request_id: "request-1",
      },
      140
    );
    state = reduceEvent(
      state,
      {
        type: "verification_result",
        summary: "Verifier verdict: pass. Looks good.",
        verdict: "pass",
        verification: { verdict: "pass", summary: "Looks good." },
        request_id: "request-1",
      },
      150
    );
    state = reduceEvent(
      state,
      {
        type: "token",
        content: "BioAPEX reviewed the request.",
        request_id: "request-1",
      },
      160
    );
    state = reduceEvent(
      state,
      {
        type: "new_response",
        request_id: "request-1",
      },
      170
    );
    state = reduceEvent(
      state,
      {
        type: "done",
        content: "BioAPEX prepared the final recommendation.",
        request_id: "request-1",
      },
      180
    );

    expect(state.streamingMessageId).toBeNull();
    expect(state.messages).toHaveLength(3);

    const firstAssistant = state.messages[1];
    expect(firstAssistant.request_id).toBe("request-1");
    expect(firstAssistant.content).toBe("BioAPEX reviewed the request.");
    expect(firstAssistant.isStreaming).toBe(false);
    expect(firstAssistant.pendingTool).toBeUndefined();
    expect(getMessageToolCalls(firstAssistant)).toHaveLength(1);
    expect(firstAssistant.blocks?.map((block) => block.type)).toEqual([
      "retrieval",
      "tool_use",
      "tool_result",
      "plan",
      "verification",
      "text",
    ]);

    const repairedAssistant = state.messages[2];
    expect(repairedAssistant.request_id).toBe("request-1");
    expect(repairedAssistant.content).toBe("BioAPEX prepared the final recommendation.");
    expect(repairedAssistant.isStreaming).toBe(false);
    expect(repairedAssistant.endedAtMs).toBe(180);
  });

  it("merges post-plan token chunks into one text block for a live updated-plan segment", () => {
    let state: StreamReducerState = {
      messages: [createOptimisticAssistantMessage("assistant-1", 100)],
      streamingMessageId: "assistant-1",
    };

    state = reduceEvent(
      state,
      {
        type: "plan_updated",
        summary: "Planner updated the repair path.",
        plan: {
          goal: "Repair the answer",
          steps: [
            { step_id: "recheck", intent: "Re-check citations" },
            { step_id: "repair", intent: "Repair answer" },
          ],
        },
        request_id: "request-2",
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "token",
        content: "Based on what I found, I'll update the plan. ",
        request_id: "request-2",
      },
      120
    );
    state = reduceEvent(
      state,
      {
        type: "token",
        content: "1. Re-check citations\n2. Repair answer\n\nUpdated final answer.",
        request_id: "request-2",
      },
      130
    );

    const assistant = state.messages[0];
    expect(assistant.blocks).toEqual([
      {
        type: "plan",
        event: "updated",
        summary: "Planner updated the repair path.",
        plan: {
          goal: "Repair the answer",
          steps: [
            { step_id: "recheck", intent: "Re-check citations" },
            { step_id: "repair", intent: "Repair answer" },
          ],
        },
        run_id: undefined,
        tool_trace: undefined,
      },
      {
        type: "text",
        text:
          "Based on what I found, I'll update the plan. " +
          "1. Re-check citations\n2. Repair answer\n\nUpdated final answer.",
      },
    ]);
  });

  it("appends an approval_gate block when the runtime emits tool_awaiting_approval", () => {
    let state: StreamReducerState = {
      messages: [createOptimisticAssistantMessage("assistant-1", 100)],
      streamingMessageId: "assistant-1",
    };

    state = reduceEvent(
      state,
      {
        type: "tool_start",
        tool: "terminal",
        input: "rm -rf /tmp/staging",
        run_id: "run-approval-1",
        request_id: "request-approval",
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "tool_awaiting_approval",
        tool: "terminal",
        input: "rm -rf /tmp/staging",
        run_id: "run-approval-1",
        reason: "requires_approval",
        message: "Tool 'terminal' is gated and needs human approval before it can run.",
        request_id: "request-approval",
      },
      120
    );

    const assistant = state.messages[0];
    expect(assistant.pendingTool).toBeUndefined();
    const approvalBlock = assistant.blocks?.find(
      (block) => block.type === "approval_gate"
    );
    expect(approvalBlock).toBeDefined();
    if (approvalBlock?.type === "approval_gate") {
      expect(approvalBlock.tool).toBe("terminal");
      expect(approvalBlock.run_id).toBe("run-approval-1");
      expect(approvalBlock.reason).toBe("requires_approval");
      expect(approvalBlock.input).toBe("rm -rf /tmp/staging");
    }
  });

  it("buffers tool_chunk events and flushes them into the tool_result block on tool_end", () => {
    let state: StreamReducerState = {
      messages: [createOptimisticAssistantMessage("assistant-1", 100)],
      streamingMessageId: "assistant-1",
    };

    state = reduceEvent(
      state,
      {
        type: "tool_start",
        tool: "terminal",
        input: "tail -f log",
        run_id: "run-stream-1",
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "tool_chunk",
        tool: "terminal",
        run_id: "run-stream-1",
        chunk_index: 0,
        chunk: "line one\n",
        terminal: false,
      },
      120
    );
    state = reduceEvent(
      state,
      {
        type: "tool_chunk",
        tool: "terminal",
        run_id: "run-stream-1",
        chunk_index: 1,
        chunk: "line two\n",
        terminal: false,
      },
      125
    );
    state = reduceEvent(
      state,
      {
        type: "tool_end",
        tool: "terminal",
        output: "[final]",
        run_id: "run-stream-1",
      },
      130
    );

    const assistant = state.messages[0];
    expect(assistant.toolChunkBuffers).toBeUndefined();
    const result = assistant.blocks?.find(
      (block) =>
        block.type === "tool_result" && block.run_id === "run-stream-1"
    );
    expect(result).toBeDefined();
    if (result?.type === "tool_result") {
      expect(result.output).toBe("line one\nline two\n[final]");
    }
  });
});
