import { describe, expect, it, vi } from "vitest";
import { streamChat } from "./api";
import { RUNTIME_EVENT_SCHEMA_VERSION } from "./runtime-events";
import { makeGenericToolResultEnvelope } from "@/test/fixtures";
import { sseResponse } from "@/test/mock-fetch";

describe("streamChat", () => {
  it("parses the typed stream contract across retrieval, tool, plan, verification, and done events", async () => {
    const toolResult = makeGenericToolResultEnvelope();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          {
            type: "retrieval",
            event_index: 1,
            query: "rnaseq patient cohort",
            results: [
              {
                source: "knowledge/study_protocol.md",
                score: 0.91,
                text: "Protocol guidance for the active RNA-seq cohort.",
              },
            ],
          },
          "data: {not-json}\n\n",
          { type: "token", content: "BioAPEX ", event_index: 2 },
          {
            type: "tool_start",
            tool: "read_file",
            input: "knowledge/study_protocol.md",
            run_id: "tool-1",
            event_index: 3,
          },
          {
            type: "tool_end",
            tool: "read_file",
            output: "Read knowledge/study_protocol.md.",
            run_id: "tool-1",
            result: toolResult,
            event_index: 4,
          },
          {
            type: "plan_created",
            summary: "Planner produced 2 steps.",
            plan: { goal: "Answer", steps: [{ step_id: "s1" }, { step_id: "s2" }] },
            event_index: 5,
          },
          {
            type: "plan_updated",
            summary: "Planner refined the evidence step.",
            plan: {
              goal: "Answer",
              steps: [{ step_id: "s1" }, { step_id: "s2" }, { step_id: "s3" }],
            },
            event_index: 6,
          },
          {
            type: "verification_result",
            summary: "Verifier verdict: pass. Looks good.",
            verdict: "pass",
            verification: { verdict: "pass", summary: "Looks good." },
            event_index: 7,
          },
          { type: "new_response", event_index: 8 },
          {
            type: "done",
            content: "BioAPEX complete.",
            request_id: "request-1",
            event_index: 9,
          },
        ],
        { chunkSize: 23 }
      )
    );

    const eventTypes: string[] = [];
    const eventIndices: number[] = [];
    const retrievals: Array<{ query: string; count: number }> = [];
    const tokens: string[] = [];
    const toolStarts: string[] = [];
    const toolEnds: string[] = [];
    const planSummaries: string[] = [];
    const verificationVerdicts: string[] = [];
    const parseErrors: string[] = [];
    let sawNewResponse = false;
    let finalContent = "";
    let finalRequestId = "";

    await streamChat(
      "Review the RNA-seq dataset.",
      "session-1",
      {
        onEvent: (event) => {
          eventTypes.push(event.type);
          if (event.event_index) {
            eventIndices.push(event.event_index);
          }
        },
        onRetrieval: (query, results) => {
          retrievals.push({ query, count: results.length });
        },
        onToken: (content) => {
          tokens.push(content);
        },
        onToolStart: (tool) => {
          toolStarts.push(tool);
        },
        onToolEnd: (tool, _output, _runId, result) => {
          toolEnds.push(tool);
          expect(result?.structured_payload).toBeTruthy();
        },
        onPlanCreated: (event) => {
          planSummaries.push(event.summary);
          expect(event.plan.steps).toHaveLength(2);
        },
        onPlanUpdated: (event) => {
          planSummaries.push(event.summary);
          expect(event.plan.steps).toHaveLength(3);
        },
        onVerificationResult: (event) => {
          verificationVerdicts.push(event.verdict);
          expect(event.verification.summary).toBe("Looks good.");
        },
        onNewResponse: () => {
          sawNewResponse = true;
        },
        onDone: (content, requestId) => {
          finalContent = content;
          finalRequestId = requestId ?? "";
        },
        onError: (error) => {
          throw new Error(`unexpected stream error: ${error}`);
        },
        onParseError: (event) => {
          parseErrors.push(event.error);
        },
      }
    );

    expect(retrievals).toEqual([{ query: "rnaseq patient cohort", count: 1 }]);
    expect(tokens.join("")).toBe("BioAPEX ");
    expect(toolStarts).toEqual(["read_file"]);
    expect(toolEnds).toEqual(["read_file"]);
    expect(planSummaries).toEqual([
      "Planner produced 2 steps.",
      "Planner refined the evidence step.",
    ]);
    expect(verificationVerdicts).toEqual(["pass"]);
    expect(sawNewResponse).toBe(true);
    expect(finalContent).toBe("BioAPEX complete.");
    expect(finalRequestId).toBe("request-1");
    expect(parseErrors).toHaveLength(1);
    expect(parseErrors[0]).toMatch(/JSON|runtime event/i);
    expect(eventTypes).toEqual([
      "retrieval",
      "parse_error",
      "token",
      "tool_start",
      "tool_end",
      "plan_created",
      "plan_updated",
      "verification_result",
      "new_response",
      "done",
    ]);
    expect(eventIndices).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init).toBeTruthy();
    const parsedBody = JSON.parse(String(init?.body));
    expect(parsedBody).toMatchObject({
      message: "Review the RNA-seq dataset.",
      session_id: "session-1",
    });
    const headers = new Headers(init?.headers as HeadersInit);
    expect(headers.get("X-Runtime-Event-Schema-Version")).toBe(
      String(RUNTIME_EVENT_SCHEMA_VERSION)
    );
  });

  it("surfaces the structured exit payload on done events to the reducer", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          {
            type: "done",
            content: "final",
            session_id: "session-exit",
            turn_status: "budget_exceeded",
            exit: {
              reason: "token_budget",
              exit_code: 3,
              summary: "turn budget exceeded at 9001 tokens",
            },
            event_index: 1,
          },
        ],
        { chunkSize: 32 }
      )
    );

    const capturedEvents: Array<{ type: string; exit?: unknown }> = [];
    await streamChat("Test exit.", "session-exit", {
      onEvent: (event) => {
        if (event.type === "done") {
          capturedEvents.push({ type: event.type, exit: event.exit });
        } else {
          capturedEvents.push({ type: event.type });
        }
      },
    });

    expect(capturedEvents).toEqual([
      {
        type: "done",
        exit: {
          reason: "token_budget",
          exit_code: 3,
          summary: "turn budget exceeded at 9001 tokens",
        },
      },
    ]);
  });

  it("surfaces typed error events without crashing on malformed SSE chunks", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          "data: {not-json}\n\n",
          {
            type: "error",
            error: "executor boom",
            request_id: "request-2",
            event_index: 1,
          },
        ],
        { chunkSize: 11 }
      )
    );

    const eventTypes: string[] = [];
    const eventIndices: number[] = [];
    const parseErrors: string[] = [];
    let surfacedError = "";
    let surfacedRequestId = "";

    await streamChat(
      "Cause an error.",
      "session-2",
      {
        onEvent: (event) => {
          eventTypes.push(event.type);
          if (event.event_index) {
            eventIndices.push(event.event_index);
          }
        },
        onRetrieval: () => {
          throw new Error("unexpected retrieval");
        },
        onToken: () => {
          throw new Error("unexpected token");
        },
        onToolStart: () => {
          throw new Error("unexpected tool start");
        },
        onToolEnd: () => {
          throw new Error("unexpected tool end");
        },
        onNewResponse: () => {
          throw new Error("unexpected new response");
        },
        onDone: () => {
          throw new Error("unexpected done");
        },
        onError: (error, requestId) => {
          surfacedError = error;
          surfacedRequestId = requestId ?? "";
        },
        onParseError: (event) => {
          parseErrors.push(event.error);
        },
      }
    );

    expect(eventTypes).toEqual(["parse_error", "error"]);
    expect(eventIndices).toEqual([1]);
    expect(parseErrors).toHaveLength(1);
    expect(surfacedError).toBe("executor boom");
    expect(surfacedRequestId).toBe("request-2");

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init).toBeTruthy();
  });

  it("flushes the final buffered event when the stream ends without a trailing blank line", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          {
            type: "token",
            content: "Final answer in progress.",
            request_id: "request-eof-1",
            event_index: 1,
          },
          `data: ${JSON.stringify({
            type: "done",
            content: "Final answer in progress.",
            request_id: "request-eof-1",
            event_index: 2,
          })}`,
        ],
        { chunkSize: 19 }
      )
    );

    const eventTypes: string[] = [];
    const surfacedErrors: string[] = [];
    let finalContent = "";
    let finalRequestId = "";

    await streamChat(
      "Finish the answer cleanly.",
      "session-eof",
      {
        onEvent: (event) => {
          eventTypes.push(event.type);
        },
        onDone: (content, requestId) => {
          finalContent = content;
          finalRequestId = requestId ?? "";
        },
        onError: (error) => {
          surfacedErrors.push(error);
        },
      }
    );

    expect(eventTypes).toEqual(["token", "done"]);
    expect(finalContent).toBe("Final answer in progress.");
    expect(finalRequestId).toBe("request-eof-1");
    expect(surfacedErrors).toEqual([]);
  });

  it("surfaces a synthetic error when the stream closes before a terminal event", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          {
            type: "retrieval",
            query: "memory",
            results: [
              {
                source: "memory/MEMORY.md",
                score: 0.99,
                text: "Remember to inspect memory first.",
              },
            ],
            request_id: "request-truncated-1",
            event_index: 1,
          },
        ],
        { chunkSize: 17 }
      )
    );

    const eventTypes: string[] = [];
    const surfacedErrors: string[] = [];
    const surfacedRequestIds: string[] = [];

    await streamChat(
      "Check latest session.",
      "session-truncated",
      {
        onEvent: (event) => {
          eventTypes.push(event.type);
        },
        onError: (error, requestId) => {
          surfacedErrors.push(error);
          surfacedRequestIds.push(requestId ?? "");
        },
      }
    );

    expect(eventTypes).toEqual(["retrieval", "error"]);
    expect(surfacedErrors).toEqual([
      "The response stream closed before completion.",
    ]);
    expect(surfacedRequestIds).toEqual(["request-truncated-1"]);
  });

  it("dispatches stream_overflow and cancels the reader when the buffered remainder exceeds the cap", async () => {
    const cap = 256;
    // A `data:` line with no terminator longer than the cap, followed by a
    // legitimate `done` event. The cancel() should fire before `done` is
    // surfaced to the dispatcher, so onDone must not be called.
    const oversizedLine = "data: " + "x".repeat(cap + 64);
    const trailingDone = `data: ${JSON.stringify({
      type: "done",
      content: "should not be reached",
      request_id: "request-overflow-trailing",
      event_index: 99,
    })}\n\n`;

    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse([oversizedLine, trailingDone], { chunkSize: 64 })
    );

    const eventTypes: string[] = [];
    const overflows: Array<{
      bufferedBytes: number;
      maxBufferBytes: number;
    }> = [];
    let sawDone = false;
    const surfacedErrors: string[] = [];

    await streamChat(
      "Send a giant payload.",
      "session-overflow",
      {
        onEvent: (event) => {
          eventTypes.push(event.type);
        },
        onStreamOverflow: (event) => {
          overflows.push({
            bufferedBytes: event.bufferedBytes,
            maxBufferBytes: event.maxBufferBytes,
          });
        },
        onDone: () => {
          sawDone = true;
        },
        onError: (error) => {
          surfacedErrors.push(error);
        },
      },
      { maxBufferBytes: cap }
    );

    expect(overflows).toHaveLength(1);
    expect(overflows[0].maxBufferBytes).toBe(cap);
    expect(overflows[0].bufferedBytes).toBeGreaterThan(cap);
    expect(eventTypes).toContain("stream_overflow");
    // Overflow is terminal — no synthetic "stream closed before completion"
    // error and no surfaced trailing `done` event.
    expect(sawDone).toBe(false);
    expect(surfacedErrors).toEqual([]);
  });

  it("cancels the in-flight fetch when the AbortController is aborted", async () => {
    let receivedSignal: AbortSignal | undefined;

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          receivedSignal = init?.signal as AbortSignal | undefined;
          if (receivedSignal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          receivedSignal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
          // Resolve never fires — the fetch stays in flight until aborted.
        })
      );

    const controller = new AbortController();
    const events: string[] = [];
    const surfacedErrors: string[] = [];

    const streamPromise = streamChat(
      "Long-running request.",
      "session-abort",
      {
        signal: controller.signal,
        onEvent: (event) => {
          events.push(event.type);
        },
        onError: (error) => {
          surfacedErrors.push(error);
        },
      }
    );

    // Give the fetch mock a microtask to register the signal listener before
    // aborting, so the abort actually fires inside the pending fetch promise.
    await Promise.resolve();
    controller.abort();

    await expect(streamPromise).rejects.toThrow(/abort/i);

    expect(receivedSignal).toBe(controller.signal);
    expect(receivedSignal?.aborted).toBe(true);
    // No events or synthetic error are dispatched — the abort propagates as a
    // rejected promise instead of a fake terminal event.
    expect(events).toEqual([]);
    expect(surfacedErrors).toEqual([]);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
