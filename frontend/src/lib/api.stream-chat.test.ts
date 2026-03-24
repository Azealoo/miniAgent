import { describe, expect, it, vi } from "vitest";
import { streamChat } from "./api";
import {
  makeComplianceReport,
  makeToolResultEnvelope,
  makeWorkflowDoneEvent,
  makeWorkflowStartEvent,
} from "@/test/fixtures";
import { sseResponse } from "@/test/mock-fetch";

describe("streamChat", () => {
  it("parses chunked SSE payloads across retrieval, tool, workflow, and done events", async () => {
    const complianceReport = makeComplianceReport();
    const toolResult = makeToolResultEnvelope(complianceReport);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      sseResponse(
        [
          {
            type: "retrieval",
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
          { type: "token", content: "BioAPEX " },
          { type: "tool_start", tool: "compliance_preflight", input: "{}", run_id: "tool-1" },
          {
            type: "tool_end",
            tool: "compliance_preflight",
            output: "warning",
            run_id: "tool-1",
            result: toolResult,
          },
          makeWorkflowStartEvent(),
          { type: "new_response" },
          makeWorkflowDoneEvent(),
          { type: "done", content: "BioAPEX complete.", request_id: "request-1" },
        ],
        { chunkSize: 23 }
      )
    );

    const retrievals: Array<{ query: string; count: number }> = [];
    const tokens: string[] = [];
    const toolStarts: string[] = [];
    const toolEnds: string[] = [];
    const workflowEvents: string[] = [];
    let sawNewResponse = false;
    let finalContent = "";
    let finalRequestId = "";

    await streamChat(
      "Run the RNA-seq workflow.",
      "session-1",
      {
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
        onWorkflowEvent: (event) => {
          workflowEvents.push(event.type);
        },
        onNewResponse: () => {
          sawNewResponse = true;
        },
        onDone: (content, requestId) => {
          finalContent = content;
          finalRequestId = requestId ?? "";
        },
        onTitle: () => {},
        onError: (error) => {
          throw new Error(`unexpected stream error: ${error}`);
        },
      },
      {
        attachedIdentifiers: ["artifacts/input/dataset.csv"],
        selectedWorkflow: "rnaseq_qc_de",
      }
    );

    expect(retrievals).toEqual([{ query: "rnaseq patient cohort", count: 1 }]);
    expect(tokens.join("")).toBe("BioAPEX ");
    expect(toolStarts).toEqual(["compliance_preflight"]);
    expect(toolEnds).toEqual(["compliance_preflight"]);
    expect(workflowEvents).toEqual(["workflow_start", "workflow_done"]);
    expect(sawNewResponse).toBe(true);
    expect(finalContent).toBe("BioAPEX complete.");
    expect(finalRequestId).toBe("request-1");

    const init = fetchSpy.mock.calls[0]?.[1];
    expect(init).toBeTruthy();
    const parsedBody = JSON.parse(String(init?.body));
    expect(parsedBody).toMatchObject({
      attached_identifiers: ["artifacts/input/dataset.csv"],
      message: "Run the RNA-seq workflow.",
      selected_workflow: "rnaseq_qc_de",
      session_id: "session-1",
      stream: true,
    });
  });
});
