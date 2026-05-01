import { describe, expect, it } from "vitest";
import {
  ApiPayloadError,
  isApiPayloadError,
  validateSessionHistory,
} from "@/lib/api-payload";

const PATH = "/api/sessions/abc/history";

function expectPayloadError(fn: () => unknown): ApiPayloadError {
  try {
    fn();
  } catch (error) {
    if (!isApiPayloadError(error)) {
      throw new Error(
        `Expected ApiPayloadError, got ${error instanceof Error ? error.name : typeof error}`
      );
    }
    return error;
  }
  throw new Error("Expected validateSessionHistory to throw, but it returned.");
}

describe("validateSessionHistory", () => {
  it("accepts user messages with non-empty content", () => {
    const result = validateSessionHistory(
      [{ role: "user", content: "Hello" }],
      PATH
    );
    expect(result).toHaveLength(1);
    expect(result[0]?.role).toBe("user");
  });

  it("accepts assistant messages whose payload is carried by blocks only", () => {
    const result = validateSessionHistory(
      [
        {
          role: "assistant",
          blocks: [{ type: "text", text: "Reviewed the readiness checklist." }],
        },
      ],
      PATH
    );
    expect(result).toHaveLength(1);
    expect(result[0]?.blocks).toHaveLength(1);
  });

  it("accepts assistant messages whose payload is only tool_calls", () => {
    const result = validateSessionHistory(
      [
        {
          role: "assistant",
          tool_calls: [
            { tool: "read_file", input: "knowledge/x.md", output: "..." },
          ],
        },
      ],
      PATH
    );
    expect(result).toHaveLength(1);
  });

  it("accepts assistant messages whose payload is only retrievals", () => {
    const result = validateSessionHistory(
      [
        {
          role: "assistant",
          retrievals: [
            { source: "knowledge/x.md", score: 0.91, text: "..." },
          ],
        },
      ],
      PATH
    );
    expect(result).toHaveLength(1);
  });

  it("rejects messages missing both content and blocks (silent blank row)", () => {
    const error = expectPayloadError(() =>
      validateSessionHistory([{ role: "assistant" }], PATH)
    );
    expect(error.path).toBe(PATH);
    expect(error.detail).toMatch(/content.*blocks/);
    expect(error.message).toContain("session history");
  });

  it("rejects messages where content is empty/whitespace and blocks is empty", () => {
    const error = expectPayloadError(() =>
      validateSessionHistory(
        [{ role: "assistant", content: "   ", blocks: [] }],
        PATH
      )
    );
    expect(error.detail).toMatch(/missing or empty/);
  });

  it("rejects messages where every supporting field is empty", () => {
    const error = expectPayloadError(() =>
      validateSessionHistory(
        [
          {
            role: "assistant",
            content: "",
            blocks: [],
            tool_calls: [],
            retrievals: [],
          },
        ],
        PATH
      )
    );
    expect(error.detail).toMatch(/missing or empty/);
  });

  it("still rejects payloads where content is not a string when present", () => {
    const error = expectPayloadError(() =>
      validateSessionHistory(
        [{ role: "assistant", content: 42, blocks: [{ type: "text", text: "ok" }] }],
        PATH
      )
    );
    expect(error.detail).toMatch(/"content" to be a string/);
  });

  it("rejects payloads whose blocks field has an invalid block shape", () => {
    const error = expectPayloadError(() =>
      validateSessionHistory(
        [
          {
            role: "assistant",
            blocks: [{ type: "tool_use", tool: "read_file" /* missing input */ }],
          },
        ],
        PATH
      )
    );
    expect(error.detail).toMatch(/"input"/);
  });

  it("identifies the offending row by index in the error label", () => {
    const error = expectPayloadError(() =>
      validateSessionHistory(
        [
          { role: "user", content: "hi" },
          { role: "assistant" },
        ],
        PATH
      )
    );
    expect(error.message).toContain("session history item 2");
  });
});
