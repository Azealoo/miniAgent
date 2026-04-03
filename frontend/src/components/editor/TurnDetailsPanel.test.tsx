import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Message } from "@/lib/types";
import {
  makeGenericToolResultEnvelope,
} from "@/test/fixtures";
import TurnDetailsPanel from "./TurnDetailsPanel";

function makeAssistantMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "",
    tool_calls: [],
    ...overrides,
  };
}

describe("TurnDetailsPanel", () => {
  it("renders block-driven turn details with retrieval, tools, and response text", () => {
    render(
      <TurnDetailsPanel
        messages={[
          {
            id: "user-1",
            role: "user",
            content: "Review the latest evidence.",
            blocks: [
              {
                type: "text",
                text: "Review the latest evidence.",
              },
            ],
          },
          makeAssistantMessage({
            request_id: "request-history-1",
            blocks: [
              {
                type: "retrieval",
                query: "Review the latest evidence.",
                results: [
                  {
                    source: "knowledge/study_protocol.md",
                    score: 0.91,
                    text: "Protocol guidance for the active RNA-seq cohort.",
                  },
                ],
              },
              {
                type: "tool_use",
                tool: "read_file",
                input: "knowledge/study_protocol.md",
                run_id: "tool-1",
              },
              {
                type: "tool_result",
                tool: "read_file",
                output: "Read knowledge/study_protocol.md.",
                run_id: "tool-1",
                result: makeGenericToolResultEnvelope(),
              },
              {
                type: "text",
                text: "Evidence and artifacts are ready.",
              },
            ],
          }),
        ]}
      />
    );

    expect(screen.getByText("Knowledge retrieval")).toBeTruthy();
    expect(
      screen.getByText(/Protocol guidance for the active RNA-seq cohort/i)
    ).toBeTruthy();
    expect(screen.getAllByText("Read File")).toHaveLength(2);
    expect(screen.getByText("Read knowledge/study_protocol.md.")).toBeTruthy();
    expect(screen.getByText("Evidence and artifacts are ready.")).toBeTruthy();
  });

  it("falls back to legacy message fields when session blocks are absent", () => {
    render(
      <TurnDetailsPanel
        messages={[
          makeAssistantMessage({
            content: "Legacy transcript content.",
            retrievals: [
              {
                source: "knowledge/legacy_protocol.md",
                score: 0.73,
                text: "Legacy retrieval context.",
              },
            ],
            tool_calls: [
              {
                tool: "python_repl",
                input: "summarize cohort",
                output: "done",
              },
            ],
          }),
        ]}
      />
    );

    expect(screen.getByText("Knowledge retrieval")).toBeTruthy();
    expect(screen.getByText(/Legacy retrieval context/i)).toBeTruthy();
    expect(screen.getAllByText("Python Repl")).toHaveLength(2);
    expect(screen.getByText("summarize cohort")).toBeTruthy();
    expect(screen.getByText("Legacy transcript content.")).toBeTruthy();
  });

  it("renders helper-agent plan and verification blocks without breaking turn details", () => {
    render(
      <TurnDetailsPanel
        messages={[
          makeAssistantMessage({
            request_id: "request-helper-1",
            blocks: [
              {
                type: "plan",
                event: "created",
                summary: "Planner produced 2 steps.",
                run_id: "plan-run-1",
                plan: {
                  goal: "Answer carefully",
                  steps: [
                    { step_id: "step-1", intent: "Inspect memory" },
                    { step_id: "step-2", intent: "Draft answer" },
                  ],
                },
                tool_trace: [{ tool: "read_file", summary: "memory" }],
              },
              {
                type: "verification",
                summary: "Verifier verdict: repair_required. Add one citation.",
                verdict: "repair_required",
                run_id: "verify-run-1",
                verification: {
                  verdict: "repair_required",
                  summary: "Add one citation.",
                  issues: ["Missing citation."],
                },
                tool_trace: [{ tool: "evidence_review", summary: "reviewed" }],
              },
              {
                type: "text",
                text: "Updated final answer.",
              },
            ],
          }),
        ]}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("created")).toBeTruthy();
    expect(screen.getByText("2 planning steps captured for this turn.")).toBeTruthy();
    expect(screen.queryByText(/Planner produced 2 steps/i)).toBeNull();
    expect(screen.getByText("Verification result")).toBeTruthy();
    expect(screen.getByText("repair required")).toBeTruthy();
    expect(
      screen.getByText("Verification requested revisions for this turn.")
    ).toBeTruthy();
    expect(screen.queryByText(/Add one citation/i)).toBeNull();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
  });

  it("uses normalized assistant content so planner json stays out of turn details", () => {
    render(
      <TurnDetailsPanel
        messages={[
          makeAssistantMessage({
            request_id: "request-helper-leak",
            blocks: [
              {
                type: "plan",
                event: "created",
                summary: "Planner produced 4 steps.",
                run_id: "plan-run-leak",
                plan: {
                  goal: "Find top T-cell papers",
                  steps: [
                    { step_id: "1", intent: "Search PubMed" },
                    { step_id: "2", intent: "Shortlist papers" },
                    { step_id: "3", intent: "Check recency" },
                    { step_id: "4", intent: "Draft summaries" },
                  ],
                },
              },
              {
                type: "text",
                text:
                  "I'll help you find the top three papers around T-cells. " +
                  'Let me search PubMed for recent and influential papers on T-cells.{"goal":"Identify, then prepare concise summaries with key findings.","assumptions":["top three"],"constraints":["Use PubMed"],"steps":[{"step_id":"1"}]}',
              },
            ],
          }),
        ]}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("4 planning steps captured for this turn.")).toBeTruthy();
    expect(screen.queryByText("Response")).toBeNull();
    expect(screen.queryByText(/I'll help you find the top three papers/i)).toBeNull();
    expect(screen.queryByText(/Let me search PubMed/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Identify/i)).toBeNull();
  });
});
