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

describe("applyStreamEvent per-event coverage", () => {
  function freshState(): StreamReducerState {
    return {
      messages: [createOptimisticAssistantMessage("assistant-1", 100)],
      streamingMessageId: "assistant-1",
    };
  }

  it("retrieval appends a retrieval block and replaces an existing one", () => {
    let state = freshState();

    state = reduceEvent(
      state,
      {
        type: "retrieval",
        query: "first",
        results: [{ source: "doc.md", score: 0.5, text: "one" }],
        request_id: "request-r",
      },
      110
    );
    let assistant = state.messages[0];
    expect(assistant.request_id).toBe("request-r");
    expect(assistant.blocks).toHaveLength(1);
    expect(assistant.blocks?.[0].type).toBe("retrieval");

    state = reduceEvent(
      state,
      {
        type: "retrieval",
        query: "second",
        results: [{ source: "doc.md", score: 0.9, text: "two" }],
      },
      120
    );
    assistant = state.messages[0];
    const retrievalBlocks = assistant.blocks?.filter(
      (b) => b.type === "retrieval"
    );
    expect(retrievalBlocks).toHaveLength(1);
    if (retrievalBlocks?.[0].type === "retrieval") {
      expect(retrievalBlocks[0].query).toBe("second");
    }
  });

  it("token appends text and merges consecutive token events", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      { type: "token", content: "Hello ", request_id: "request-t" },
      110
    );
    state = reduceEvent(state, { type: "token", content: "world." }, 115);
    const assistant = state.messages[0];
    expect(assistant.content).toBe("Hello world.");
    expect(assistant.blocks).toEqual([{ type: "text", text: "Hello world." }]);
    expect(assistant.request_id).toBe("request-t");
  });

  it("tool_start records a pending tool and appends a tool_use block", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "tool_start",
        tool: "read_file",
        input: "knowledge/a.md",
        run_id: "run-1",
      },
      110
    );
    const assistant = state.messages[0];
    expect(assistant.pendingTool?.runId).toBe("run-1");
    expect(assistant.blocks?.[0]).toMatchObject({
      type: "tool_use",
      tool: "read_file",
      run_id: "run-1",
    });
  });

  it("tool_end clears pending tool and appends a tool_result block", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      { type: "tool_start", tool: "read_file", input: "a.md", run_id: "run-1" },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "tool_end",
        tool: "read_file",
        output: "done",
        run_id: "run-1",
      },
      120
    );
    const assistant = state.messages[0];
    expect(assistant.pendingTool).toBeUndefined();
    const result = assistant.blocks?.find((b) => b.type === "tool_result");
    expect(result).toBeDefined();
    if (result?.type === "tool_result") {
      expect(result.output).toBe("done");
      expect(result.run_id).toBe("run-1");
    }
  });

  it("tool_awaiting_approval converts a pending tool into an approval_gate block", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "tool_start",
        tool: "terminal",
        input: "rm -rf /tmp",
        run_id: "run-apr",
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "tool_awaiting_approval",
        tool: "terminal",
        input: "rm -rf /tmp",
        run_id: "run-apr",
        reason: "requires_approval",
        message: "Awaiting approval",
      },
      120
    );
    const assistant = state.messages[0];
    expect(assistant.pendingTool).toBeUndefined();
    const gate = assistant.blocks?.find((b) => b.type === "approval_gate");
    expect(gate).toBeDefined();
    if (gate?.type === "approval_gate") {
      expect(gate.run_id).toBe("run-apr");
      expect(gate.reason).toBe("requires_approval");
    }
  });

  it("tool_chunk accumulates buffers without mutating the block list", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      { type: "tool_start", tool: "sh", input: "x", run_id: "run-c" },
      110
    );
    const blocksBefore = state.messages[0].blocks?.length ?? 0;
    state = reduceEvent(
      state,
      {
        type: "tool_chunk",
        tool: "sh",
        run_id: "run-c",
        chunk_index: 0,
        chunk: "partial",
        terminal: false,
      },
      120
    );
    const assistant = state.messages[0];
    expect(assistant.blocks?.length).toBe(blocksBefore);
    expect(assistant.toolChunkBuffers?.["run-c"]).toBeDefined();
    expect(assistant.toolChunkBuffers?.["run-c"].chunks[0].text).toBe(
      "partial"
    );
  });

  it("plan_created appends a plan block tagged 'created'", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "plan_created",
        summary: "Plan ready",
        plan: { goal: "g", steps: [] },
        request_id: "request-p",
      },
      110
    );
    const assistant = state.messages[0];
    const plan = assistant.blocks?.find((b) => b.type === "plan");
    expect(plan).toBeDefined();
    if (plan?.type === "plan") {
      expect(plan.event).toBe("created");
      expect(plan.summary).toBe("Plan ready");
    }
  });

  it("plan_updated appends a plan block tagged 'updated'", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "plan_updated",
        summary: "Plan changed",
        plan: { goal: "g", steps: [] },
      },
      110
    );
    const assistant = state.messages[0];
    const plan = assistant.blocks?.find((b) => b.type === "plan");
    expect(plan).toBeDefined();
    if (plan?.type === "plan") {
      expect(plan.event).toBe("updated");
    }
  });

  it("verification_result appends a verification block with verdict", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "verification_result",
        summary: "ok",
        verdict: "pass",
        verification: { verdict: "pass", summary: "ok" },
      },
      110
    );
    const assistant = state.messages[0];
    const verification = assistant.blocks?.find(
      (b) => b.type === "verification"
    );
    expect(verification).toBeDefined();
    if (verification?.type === "verification") {
      expect(verification.verdict).toBe("pass");
    }
  });

  it("new_response closes the streaming message and opens a fresh one", () => {
    let state = freshState();
    state = reduceEvent(state, { type: "new_response" }, 120);
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0].isStreaming).toBe(false);
    expect(state.messages[0].endedAtMs).toBe(120);
    expect(state.messages[1].isStreaming).toBe(true);
    expect(state.streamingMessageId).toBe(state.messages[1].id);
  });

  it("compaction_event is a no-op for the live message tree", () => {
    const state = freshState();
    const result = applyStreamEvent(
      state,
      {
        type: "compaction_event",
        from_turn: 1,
        to_turn: 2,
        summary: "compacted",
        saved_tokens: 100,
      },
      { createMessageId: () => "new", now: 200 }
    );
    expect(result.finished).toBe(false);
    expect(result.messages).toBe(state.messages);
    expect(result.streamingMessageId).toBe(state.streamingMessageId);
  });

  it("done finalizes the streaming message and backfills missing content", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      { type: "done", content: "final answer", request_id: "request-d" },
      200
    );
    const assistant = state.messages[0];
    expect(state.streamingMessageId).toBeNull();
    expect(assistant.isStreaming).toBe(false);
    expect(assistant.content).toBe("final answer");
    expect(assistant.endedAtMs).toBe(200);
    expect(assistant.request_id).toBe("request-d");
  });

  it("done does not overwrite existing streamed content", () => {
    let state = freshState();
    state = reduceEvent(state, { type: "token", content: "streamed" }, 110);
    state = reduceEvent(
      state,
      { type: "done", content: "different final" },
      200
    );
    const assistant = state.messages[0];
    expect(assistant.content).toBe("streamed");
  });

  it("error appends an error block and ends the turn", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      { type: "error", error: "the runtime crashed" },
      210
    );
    const assistant = state.messages[0];
    expect(state.streamingMessageId).toBeNull();
    expect(assistant.isStreaming).toBe(false);
    expect(assistant.endedAtMs).toBe(210);
    expect(assistant.content).toContain("the runtime crashed");
    const lastBlock = assistant.blocks?.at(-1);
    expect(lastBlock?.type).toBe("text");
    if (lastBlock?.type === "text") {
      expect(lastBlock.text).toContain("the runtime crashed");
    }
  });

  it("parse_error does not mutate the message tree or end the stream", () => {
    const state = freshState();
    const result = applyStreamEvent(
      state,
      {
        type: "parse_error",
        error: "bad payload",
        raw: "{oops",
      },
      { createMessageId: () => "new", now: 300 }
    );
    expect(result.finished).toBe(false);
    expect(result.messages).toBe(state.messages);
    expect(result.streamingMessageId).toBe(state.streamingMessageId);
  });

  it("workflow_step_started seeds a running step in workflowSteps", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "workflow_step_started",
        workflow_id: "demo_flow",
        run_id: "wf-1",
        step_id: "step_a",
        step_index: 1,
        total_steps: 2,
        label: "First step",
        attempt: 1,
        request_id: "request-w",
      },
      110
    );
    const assistant = state.messages[0];
    expect(assistant.request_id).toBe("request-w");
    expect(assistant.workflowSteps).toHaveLength(1);
    expect(assistant.workflowSteps?.[0]).toMatchObject({
      workflow_id: "demo_flow",
      run_id: "wf-1",
      step_id: "step_a",
      step_index: 1,
      total_steps: 2,
      status: "running",
      label: "First step",
      attempt: 1,
    });
  });

  it("workflow_step_ended flips a running step to ok and records duration", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "workflow_step_started",
        workflow_id: "demo_flow",
        run_id: "wf-1",
        step_id: "step_a",
        step_index: 1,
        total_steps: 2,
        label: "First step",
        attempt: 1,
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "workflow_step_ended",
        workflow_id: "demo_flow",
        run_id: "wf-1",
        step_id: "step_a",
        step_index: 1,
        total_steps: 2,
        duration_ms: 42,
      },
      120
    );
    const step = state.messages[0].workflowSteps?.[0];
    expect(step?.status).toBe("ok");
    expect(step?.duration_ms).toBe(42);
    expect(step?.label).toBe("First step");
  });

  it("workflow_step_failed flips a running step to failed and carries error + policy", () => {
    let state = freshState();
    state = reduceEvent(
      state,
      {
        type: "workflow_step_started",
        workflow_id: "demo_flow",
        run_id: "wf-1",
        step_id: "step_b",
        step_index: 2,
        total_steps: 2,
        attempt: 1,
      },
      130
    );
    state = reduceEvent(
      state,
      {
        type: "workflow_step_failed",
        workflow_id: "demo_flow",
        run_id: "wf-1",
        step_id: "step_b",
        step_index: 2,
        total_steps: 2,
        duration_ms: 5,
        error: "RuntimeError: kaboom",
        failure_policy: "fail_workflow",
        attempt: 1,
      },
      140
    );
    const steps = state.messages[0].workflowSteps;
    expect(steps).toHaveLength(1);
    expect(steps?.[0]).toMatchObject({
      status: "failed",
      error: "RuntimeError: kaboom",
      failure_policy: "fail_workflow",
      duration_ms: 5,
    });
  });

  it("workflow step events for multiple steps preserve insertion order", () => {
    let state = freshState();
    const base = {
      workflow_id: "demo_flow" as const,
      run_id: "wf-2" as const,
      total_steps: 2,
      attempt: 1,
    };
    state = reduceEvent(
      state,
      {
        type: "workflow_step_started",
        ...base,
        step_id: "step_a",
        step_index: 1,
      },
      110
    );
    state = reduceEvent(
      state,
      {
        type: "workflow_step_ended",
        ...base,
        step_id: "step_a",
        step_index: 1,
        duration_ms: 10,
      },
      115
    );
    state = reduceEvent(
      state,
      {
        type: "workflow_step_started",
        ...base,
        step_id: "step_b",
        step_index: 2,
      },
      120
    );
    const ids = state.messages[0].workflowSteps?.map((step) => step.step_id);
    expect(ids).toEqual(["step_a", "step_b"]);
    const statuses = state.messages[0].workflowSteps?.map((step) => step.status);
    expect(statuses).toEqual(["ok", "running"]);
  });

  it("returns state unchanged when no streaming message is active", () => {
    const state: StreamReducerState = {
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "hi",
          blocks: [{ type: "text", text: "hi" }],
        },
      ],
      streamingMessageId: null,
    };
    const result = applyStreamEvent(
      state,
      { type: "token", content: "ignored" },
      { createMessageId: () => "new", now: 400 }
    );
    expect(result.messages).toBe(state.messages);
    expect(result.streamingMessageId).toBeNull();
    expect(result.finished).toBe(false);
  });
});
