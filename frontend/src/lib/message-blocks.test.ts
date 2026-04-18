import { describe, expect, it } from "vitest";
import {
  getMessageRetrievals,
  getMessageToolCalls,
} from "./message-blocks";
import type { Message } from "./types";

describe("block-derived message helpers", () => {
  it("derives tool calls and retrievals from blocks when no legacy fields exist on Message", () => {
    const message: Message = {
      id: "assistant-1",
      role: "assistant",
      content: "Reviewed the readiness checklist.",
      blocks: [
        {
          type: "retrieval",
          query: "readiness review",
          results: [
            {
              source: "knowledge/readiness-checklist.md",
              score: 0.91,
              text: "Inspect the readiness checklist before execution.",
            },
          ],
        },
        {
          type: "tool_use",
          tool: "read_file",
          input: "knowledge/readiness-checklist.md",
          run_id: "tool-1",
        },
        {
          type: "tool_result",
          tool: "read_file",
          output: "Read knowledge/readiness-checklist.md.",
          run_id: "tool-1",
        },
        {
          type: "text",
          text: "Reviewed the readiness checklist.",
        },
      ],
    };

    const toolCalls = getMessageToolCalls(message);
    const retrievals = getMessageRetrievals(message);

    expect(toolCalls).toHaveLength(1);
    expect(toolCalls[0]).toMatchObject({
      tool: "read_file",
      input: "knowledge/readiness-checklist.md",
      output: "Read knowledge/readiness-checklist.md.",
      run_id: "tool-1",
    });

    expect(retrievals).toHaveLength(1);
    expect(retrievals[0]).toMatchObject({
      source: "knowledge/readiness-checklist.md",
      score: 0.91,
    });
  });

  it("returns empty arrays for a block-only message with no tool_use or retrieval blocks", () => {
    const message: Message = {
      id: "assistant-plain",
      role: "assistant",
      content: "Plain text answer.",
      blocks: [{ type: "text", text: "Plain text answer." }],
    };

    expect(getMessageToolCalls(message)).toEqual([]);
    expect(getMessageRetrievals(message)).toEqual([]);
  });
});
