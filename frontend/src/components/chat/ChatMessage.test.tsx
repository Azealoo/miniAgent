import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Message, ToolResultEnvelope } from "@/lib/types";
import { makeComplianceReport, makeToolResultEnvelope } from "@/test/fixtures";
import ChatMessage from "./ChatMessage";

function makeToolResult(toolName: string): ToolResultEnvelope {
  return {
    contract_version: "tool_result.v1",
    tool_name: toolName,
    summary: "Computed a compact study summary.",
    structured_payload: null,
    artifact_refs: [],
    warnings: [],
    status: "success",
    outcome: "success",
    metadata: {
      duration_ms: 320,
    },
    source_payload: null,
  };
}

function makeAssistantMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "",
    tool_calls: [],
    ...overrides,
  };
}

function makeUserMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: "user-1",
    role: "user",
    content: "Give me the top three relevant papers around t cells",
    ...overrides,
  };
}

describe("ChatMessage", () => {
  it("renders user prompts as clean right-side bubbles without the prompt sigil", () => {
    render(<ChatMessage message={makeUserMessage()} />);

    const article = screen.getByLabelText("User prompt");
    expect(article.textContent).toBe(
      "Give me the top three relevant papers around t cells"
    );
    expect(screen.queryByText(">", { exact: true })).toBeNull();
  });

  it("shows a unified live activity feed while the assistant is still streaming", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          isStreaming: true,
          pendingTool: {
            tool: "python_repl",
            input: "summarize study",
            runId: "tool-1",
          },
          tool_calls: [
            {
              tool: "python_repl",
              input: "summarize study",
              output: "done",
              run_id: "tool-1",
              result: makeToolResult("python_repl"),
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.queryByText("Activity record")).toBeNull();
    expect(screen.getByText("Running python repl on summarize study.")).toBeTruthy();
    expect(screen.getByText("Ran python repl on summarize study.")).toBeTruthy();
  });

  it("shows a unified live feed while grounding knowledge", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          isStreaming: true,
          retrievals: [
            {
              text: "Relevant study note",
              score: 0.91,
              source: "knowledge/study.md",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Looked at study.md.")).toBeTruthy();
    expect(screen.queryByText("Relevant study note", { exact: false })).toBeNull();
    expect(screen.queryByText("Knowledge Retrieved")).toBeNull();
  });

  it("shows a fallback live activity row before structured events arrive", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          isStreaming: true,
        })}
      />
    );

    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Preparing next step.")).toBeTruthy();
  });

  it("does not show elapsed time in the live thinking header when timing is available", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-02T12:00:03.200Z"));

    try {
      render(
        <ChatMessage
          message={makeAssistantMessage({
            isStreaming: true,
            startedAtMs: Date.parse("2026-04-02T12:00:00.000Z"),
          })}
        />
      );

      expect(screen.queryByText("Elapsed 3.2s so far.")).toBeNull();
      expect(screen.getByText("Preparing next step.")).toBeTruthy();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the live drafting state visible while plain text is still streaming", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          isStreaming: true,
          content: "Draft answer in progress",
        })}
      />
    );

    const content = screen.getByText("Draft answer in progress");
    const label = screen.getByText("Thinking");

    expect(label).toBeTruthy();
    expect(label.className).toContain("apex-thinking-label");
    expect(screen.getByText("Drafting answer.")).toBeTruthy();
    expect(content).toBeTruthy();
    expect(
      label.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("keeps the process feed first while the answer streams separately below it", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          isStreaming: true,
          content: "The study summary is ready.",
          blocks: [
            {
              type: "retrieval",
              query: "study summary",
              results: [
                {
                  text: "Relevant study note",
                  score: 0.91,
                  source: "knowledge/study.md",
                },
              ],
            },
            {
              type: "text",
              text: "The study",
            },
            {
              type: "tool_use",
              tool: "python_repl",
              input: "summarize study",
              run_id: "tool-1",
            },
            {
              type: "tool_result",
              tool: "python_repl",
              output: "done",
              run_id: "tool-1",
              result: makeToolResult("python_repl"),
            },
            {
              type: "text",
              text: " summary is ready.",
            },
          ],
        })}
      />
    );

    const label = screen.getByText("Thinking");
    const sourceLine = screen.getByText("Looked at study.md.");
    const startedLine = screen.getByText("Started python repl on summarize study.");
    const finishedLine = screen.getByText("Ran python repl on summarize study.");
    const content = screen.getByText("The study summary is ready.");

    expect(label).toBeTruthy();
    expect(sourceLine).toBeTruthy();
    expect(startedLine).toBeTruthy();
    expect(finishedLine).toBeTruthy();
    expect(content).toBeTruthy();
    expect(
      label.compareDocumentPosition(sourceLine) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      sourceLine.compareDocumentPosition(startedLine) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      startedLine.compareDocumentPosition(finishedLine) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      finishedLine.compareDocumentPosition(content) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(screen.queryByText("Tool Trace")).toBeNull();
    expect(screen.queryByText("Input")).toBeNull();
    expect(screen.queryByText("Output")).toBeNull();
    expect(screen.queryByText("Structured Payload")).toBeNull();
    expect(screen.queryByText("Source Payload")).toBeNull();
  });

  it("renders live plan and verification blocks above the streamed answer", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          isStreaming: true,
          content: "BioAPEX prepared the final recommendation.",
          blocks: [
            {
              type: "retrieval",
              query: "readiness review",
              results: [
                {
                  text: "Run a compliance check before execution.",
                  score: 0.92,
                  source: "knowledge/readiness-checklist.md",
                },
              ],
            },
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 2 steps.",
              run_id: "plan-run-1",
              plan: {
                goal: "Check readiness",
                steps: [
                  { step_id: "collect", intent: "Look at memory" },
                  { step_id: "report", intent: "Run readiness check" },
                ],
              },
            },
            {
              type: "verification",
              summary: "Verifier verdict: pass. Looks good.",
              verdict: "pass",
              run_id: "verify-run-1",
              verification: {
                verdict: "pass",
                summary: "Looks good.",
              },
            },
            {
              type: "text",
              text: "BioAPEX prepared the final recommendation.",
            },
          ],
        })}
      />
    );

    const label = screen.getByText("Thinking");
    const retrievalLine = screen.getByText("Looked at readiness-checklist.md.");
    const planTitle = screen.getByText("Planning");
    const planStepOne = screen.getByText("Look at memory");
    const planStepTwo = screen.getByText("Run readiness check");
    const verificationTitle = screen.getByText("Verification result");
    const verificationSummary = screen.getByText("Looks good.");
    const content = screen.getByText("BioAPEX prepared the final recommendation.");

    expect(screen.getByText("pass")).toBeTruthy();
    expect(label).toBeTruthy();
    expect(planStepOne).toBeTruthy();
    expect(planStepTwo).toBeTruthy();
    expect(verificationSummary).toBeTruthy();
    expect(screen.queryByText(/Started planning/i)).toBeNull();
    expect(screen.queryByText(/Ran planning/i)).toBeNull();
    expect(screen.queryByText("Planner produced 2 steps.")).toBeNull();
    expect(screen.queryByText("Planning 2 steps to check readiness.")).toBeNull();
    expect(
      label.compareDocumentPosition(retrievalLine) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      retrievalLine.compareDocumentPosition(planTitle) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      planTitle.compareDocumentPosition(planStepOne) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      planStepOne.compareDocumentPosition(verificationTitle) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      verificationTitle.compareDocumentPosition(content) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("hides planner narration and raw plan json when the planning section already captures it", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 2 steps.",
              run_id: "plan-run-1",
              plan: {
                goal: "Check readiness",
                steps: [
                  { step_id: "collect", intent: "Look at memory" },
                  { step_id: "report", intent: "Run readiness check" },
                ],
              },
            },
            {
              type: "text",
              text:
                "I'll help you conduct a readiness review. Let me start by creating a structured plan. " +
                '{"goal":"Check readiness","steps":[{"step_id":"collect"},{"step_id":"report"}]}',
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Look at memory")).toBeTruthy();
    expect(screen.getByText("Run readiness check")).toBeTruthy();
    expect(screen.queryByText(/I'll help you conduct a readiness review/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Check readiness"/i)).toBeNull();
    expect(screen.queryByText("Planning 2 steps to check readiness.")).toBeNull();
  });

  it("hides updated planner thought-process text while keeping the actual follow-up answer", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "updated",
              summary: "Planner updated the repair path.",
              run_id: "plan-run-5",
              plan: {
                goal: "Repair the answer",
                steps: [
                  { step_id: "recheck", intent: "Re-check citations" },
                  { step_id: "repair", intent: "Repair answer" },
                ],
              },
            },
            {
              type: "text",
              text:
                "Based on what I found, I'll update the plan. " +
                "1. Re-check citations\n2. Repair answer",
            },
            {
              type: "text",
              text: "Updated final answer.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Re check citations")).toBeTruthy();
    expect(screen.getByText("Repair answer")).toBeTruthy();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
    expect(screen.queryByText(/update the plan/i)).toBeNull();
    expect(screen.queryByText(/^1\. Re-check citations$/i)).toBeNull();
    expect(screen.queryByText(/^2\. Repair answer$/i)).toBeNull();
  });

  it("keeps the planning steps concise when planner steps are long", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 2 steps.",
              run_id: "plan-run-2",
              plan: {
                goal: "",
                steps: [
                  {
                    step_id: "step_1_scope_and_inventory",
                    intent:
                      "Establish the review scope and identify the minimum project context needed to judge readiness, including study design and comparison groups.",
                  },
                  {
                    step_id: "step_2_collect_required_context",
                    intent:
                      "Inspect core files and metadata needed for readiness, including sample sheets, batch variables, reference genome versions, and QC summaries.",
                  },
                ],
              },
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Scope and inventory")).toBeTruthy();
    expect(screen.getByText("Collect required context")).toBeTruthy();
    expect(screen.queryByText(/Establish the review scope and identify/i)).toBeNull();
    expect(screen.queryByText(/Inspect core files and metadata needed/i)).toBeNull();
    expect(
      screen.queryByText(
        "Planning 2 steps around scope and inventory, then collect required context."
      )
    ).toBeNull();
  });

  it("prefers summarized planning intents over numeric step ids", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 3 steps.",
              run_id: "plan-run-3",
              plan: {
                goal: "",
                steps: [
                  {
                    step_id: "1",
                    intent:
                      "Inspect core files and metadata needed for readiness, including sample sheets and QC summaries.",
                  },
                  {
                    step_id: "2",
                    intent:
                      "Check for compliance and safety issues that could block the analysis before it begins.",
                  },
                  {
                    step_id: "3",
                    intent:
                      "Summarize likely analysis stages and produce a concise readiness recommendation.",
                  },
                ],
              },
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Inspect core files")).toBeTruthy();
    expect(screen.getByText("Review risks and safety")).toBeTruthy();
    expect(screen.getByText("Outline analysis stages")).toBeTruthy();
    expect(screen.queryByText(/^1$/)).toBeNull();
    expect(screen.queryByText(/^2$/)).toBeNull();
    expect(screen.queryByText(/^3$/)).toBeNull();
  });

  it("does not ellipsize moderately long planning labels", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 1 step.",
              run_id: "plan-run-4",
              plan: {
                goal: "",
                steps: [
                  {
                    step_id: "1",
                    intent:
                      "Inspect the local project context and workflow notes before proceeding.",
                  },
                ],
              },
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(
      screen.getByText("Inspect the local project context and workflow notes before proceeding")
    ).toBeTruthy();
    expect(screen.queryByText(/Inspect the local project con…/i)).toBeNull();
  });

  it("hides verifier narration and raw verification json when the verification section already captures it", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "verification",
              summary:
                "Verifier verdict: repair_required. The draft is directionally correct, but it needs one citation.",
              verdict: "repair_required",
              run_id: "verify-run-2",
              verification: {
                verdict: "repair_required",
                summary: "Add one citation.",
                issues: ["Missing citation."],
              },
            },
            {
              type: "text",
              text:
                'Now let me verify this answer with the verification agent: {"verdict":"repair_required","summary":"Add one citation.","issues":["Missing citation."]}',
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Verification result")).toBeTruthy();
    expect(screen.getByText("Add one citation.")).toBeTruthy();
    expect(screen.queryByText(/verification agent/i)).toBeNull();
    expect(screen.queryByText(/"verdict":"repair_required"/i)).toBeNull();
    expect(
      screen.queryByText(
        /The draft is directionally correct, but it needs one citation/i
      )
    ).toBeNull();
  });

  it("prefers actionable verification repair instructions over the generic fallback", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "verification",
              summary:
                "Verifier verdict: repair_required. The draft is broadly aligned with the task, but it misses several readiness items and needs refinement.",
              verdict: "repair_required",
              run_id: "verify-run-3",
              verification: {
                verdict: "repair_required",
                summary:
                  "The draft is broadly aligned with the task, but it misses several readiness items and needs refinement.",
                issues: [
                  "Missing explicit RNA-seq-specific readiness checks.",
                ],
                repair_instructions: [
                  "Add the missing RNA-seq-specific readiness checks before finalizing the answer.",
                ],
              },
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Verification result")).toBeTruthy();
    expect(
      screen.getByText(
        "Add the missing RNA-seq-specific readiness checks before finalizing the answer."
      )
    ).toBeTruthy();
    expect(screen.queryByText("Needs revision.")).toBeNull();
  });

  it("keeps the thinking trail visible above the final response after completion", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: "The study summary is ready.",
          blocks: [
            {
              type: "retrieval",
              query: "study summary",
              results: [
                {
                  text: "Relevant study note",
                  score: 0.91,
                  source: "knowledge/study.md",
                },
              ],
            },
            {
              type: "text",
              text: "The study summary is ready.",
            },
          ],
        })}
      />
    );

    const label = screen.getByText("Thinking");
    const sourceLine = screen.getByText("Looked at study.md.");
    const content = screen.getByText("The study summary is ready.");

    expect(label).toBeTruthy();
    expect(label.className).not.toContain("apex-thinking-label");
    expect(sourceLine).toBeTruthy();
    expect(content).toBeTruthy();
    expect(screen.getByText("The study summary is ready.")).toBeTruthy();
    expect(
      label.compareDocumentPosition(sourceLine) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      sourceLine.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("renders completed block-only history turns with the same process-and-answer layout", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: "",
          tool_calls: [],
          retrievals: [],
          blocks: [
            {
              type: "retrieval",
              query: "archive summary",
              results: [
                {
                  text: "Archived study note",
                  score: 0.87,
                  source: "history/archive-note.md",
                },
              ],
            },
            {
              type: "tool_use",
              tool: "python_repl",
              input: "summarize archive",
              run_id: "archive-tool-1",
            },
            {
              type: "tool_result",
              tool: "python_repl",
              output: "done",
              run_id: "archive-tool-1",
              result: makeToolResult("python_repl"),
            },
            {
              type: "text",
              text: "Archived answer reconstructed from blocks.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Looked at archive-note.md.")).toBeTruthy();
    expect(screen.getByText("Started python repl on summarize archive.")).toBeTruthy();
    expect(screen.getByText("Ran python repl on summarize archive.")).toBeTruthy();
    expect(
      screen.getByText("Archived answer reconstructed from blocks.")
    ).toBeTruthy();
  });

  it("shows a light worked-duration note above the assistant response after it finishes", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: "The study summary is ready.",
          startedAtMs: 0,
          endedAtMs: 3200,
        })}
      />
    );

    const article = screen.getByLabelText("Assistant response");
    const duration = screen.getByText("Worked for 3.2s.");
    const content = screen.getByText("The study summary is ready.");

    expect(duration).toBeTruthy();
    expect(
      duration.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(article).toBeTruthy();
  });

  it("removes the persistent compliance card after the answer finishes", () => {
    const report = makeComplianceReport();

    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: "The study summary is ready.",
          tool_calls: [
            {
              tool: "compliance_preflight",
              input: "{}",
              output: "warning",
              run_id: "tool-2",
              result: makeToolResultEnvelope(report),
            },
          ],
        })}
      />
    );

    expect(screen.getByText("The study summary is ready.")).toBeTruthy();
    expect(screen.queryByText("Compliance")).toBeNull();
    expect(screen.queryByText("rna-human-review")).toBeNull();
    expect(screen.queryByText("Activity record")).toBeNull();
  });

  it("does not render an approval replay prompt when helper-agent blocks are present", () => {
    const report = makeComplianceReport({
      block_status: "blocked",
      final_disposition: "require_approval",
      human_approval_required: true,
      preflight_disposition: "require_approval",
      runtime_state: "approval_required",
    });

    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "updated",
              summary: "Planner updated the repair path.",
              run_id: "plan-run-2",
              plan: {
                goal: "Repair the answer",
                steps: [{ step_id: "repair", intent: "Repair answer" }],
              },
            },
          ],
          tool_calls: [
            {
              tool: "compliance_preflight",
              input: "{}",
              output: "approval required",
              run_id: "tool-2",
              result: makeToolResultEnvelope(report),
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Repair answer")).toBeTruthy();
    expect(screen.queryByText("Planner updated the repair path.")).toBeNull();
    expect(
      screen.queryByText(
        /Continue and record message-scoped approval for the original request\?/i
      )
    ).toBeNull();
  });

  it("does not show an inline approval replay prompt for approval-required turns", () => {
    const report = makeComplianceReport({
      block_status: "blocked",
      final_disposition: "require_approval",
      human_approval_required: true,
      preflight_disposition: "require_approval",
      runtime_state: "approval_required",
    });

    render(
      <ChatMessage
        message={makeAssistantMessage({
          tool_calls: [
            {
              tool: "compliance_preflight",
              input: "{}",
              output: "approval required",
              run_id: "tool-2",
              result: makeToolResultEnvelope(report),
            },
          ],
        })}
      />
    );

    expect(
      screen.queryByText(/Continue and record message-scoped approval for the original request\?/i)
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Proceed with approval" })).toBeNull();
    expect(screen.queryByText("Compliance")).toBeNull();
  });
});
