import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  Message,
  RetrievalResult,
  SessionContentBlock,
  ToolCall,
  ToolResultEnvelope,
} from "@/lib/types";
import {
  makeComplianceReport,
  makeGenericToolResultEnvelope,
  makeToolResultEnvelope,
} from "@/test/fixtures";
import ChatMessage from "./ChatMessage";

type MessageFixtureOverrides = Partial<Omit<Message, "blocks">> & {
  tool_calls?: ToolCall[];
  retrievals?: RetrievalResult[];
  blocks?: SessionContentBlock[];
};

function buildBlocksFromLegacy(
  toolCalls: ToolCall[] | undefined,
  retrievals: RetrievalResult[] | undefined,
  content: string
): SessionContentBlock[] {
  const blocks: SessionContentBlock[] = [];
  if (retrievals && retrievals.length > 0) {
    blocks.push({ type: "retrieval", results: [...retrievals] });
  }
  for (const call of toolCalls ?? []) {
    blocks.push({
      type: "tool_use",
      tool: call.tool,
      input: call.input,
      run_id: call.run_id,
    });
    blocks.push({
      type: "tool_result",
      tool: call.tool,
      output: call.output,
      run_id: call.run_id,
      result: call.result,
    });
  }
  if (content) {
    blocks.push({ type: "text", text: content });
  }
  return blocks;
}

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

function makeAssistantMessage(
  overrides: MessageFixtureOverrides = {}
): Message {
  const { tool_calls, retrievals, blocks, ...rest } = overrides;
  const content = rest.content ?? "";
  const derivedBlocks =
    blocks ?? buildBlocksFromLegacy(tool_calls, retrievals, content);
  return {
    id: "assistant-1",
    role: "assistant",
    content,
    blocks: derivedBlocks,
    ...rest,
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

  it("hides structured tool input and output payloads from the user-facing thinking rail", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: "Candidate papers ready.",
          blocks: [
            {
              type: "tool_use",
              tool: "ncbi_eutils",
              input: '{"operation":"esearch","term":"t cells"}',
              run_id: "json-tool-1",
            },
            {
              type: "tool_result",
              tool: "ncbi_eutils",
              output: '{"ids":["123","456","789"]}',
              run_id: "json-tool-1",
              result: makeGenericToolResultEnvelope({
                tool_name: "ncbi_eutils",
                summary: "Fetched candidate paper identifiers.",
              }),
            },
            {
              type: "text",
              text: "Candidate papers ready.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Started ncbi eutils.")).toBeTruthy();
    expect(screen.getByText("Ran ncbi eutils.")).toBeTruthy();
    expect(screen.getByText("Candidate papers ready.")).toBeTruthy();
    expect(screen.queryByText(/"operation":"esearch"/i)).toBeNull();
    expect(screen.queryByText(/"ids":\[/i)).toBeNull();
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
                checks: [
                  {
                    name: "readiness",
                    status: "pass",
                    note: "Core readiness items are covered.",
                  },
                ],
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
    const planningTitle = screen.getByText("Planning");
    const planningSummary = screen.getByText("Prepared a 2-step plan.");
    const planningStepOne = screen.getByText("1. Look at memory.");
    const planningStepTwo = screen.getByText("2. Run readiness check.");
    const verificationTitle = screen.getByText("Verification");
    const verificationSummary = screen.getByText("Passed verification.");
    const verificationCheck = screen.getByText(
      "Readiness check passed: Core readiness items are covered."
    );
    const content = screen.getByText("BioAPEX prepared the final recommendation.");

    expect(screen.queryByText("Verification result")).toBeNull();
    expect(screen.queryByText("pass")).toBeNull();
    expect(label).toBeTruthy();
    expect(planningTitle).toBeTruthy();
    expect(planningSummary).toBeTruthy();
    expect(planningStepOne).toBeTruthy();
    expect(planningStepTwo).toBeTruthy();
    expect(verificationSummary).toBeTruthy();
    expect(verificationCheck).toBeTruthy();
    expect(screen.queryByText(/Started planning/i)).toBeNull();
    expect(screen.queryByText(/Ran planning/i)).toBeNull();
    expect(screen.queryByText("Planner produced 2 steps.")).toBeNull();
    expect(
      label.compareDocumentPosition(retrievalLine) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      retrievalLine.compareDocumentPosition(planningTitle) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      planningTitle.compareDocumentPosition(verificationTitle) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      verificationTitle.compareDocumentPosition(content) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("hides planner-only narration and raw plan json from the user transcript", () => {
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

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Look at memory.")).toBeTruthy();
    expect(screen.getByText("2. Run readiness check.")).toBeTruthy();
    expect(screen.queryByText("Planning 2 steps to check readiness.")).toBeNull();
    expect(screen.queryByText(/I'll help you conduct a readiness review/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Check readiness"/i)).toBeNull();
  });

  it("hides incomplete planner json blobs after the planning preamble", () => {
    const leakedPlannerText =
      "I'll help you find the top three papers around T-cells. " +
      'Let me search PubMed for recent and influential papers on T-cells.{"goal":"Identify, then prepare concise summaries with key findings and relevance.","assumptions":["top three"],"constraints":["Becau';

    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: leakedPlannerText,
          startedAtMs: 0,
          endedAtMs: 15_000,
          blocks: [
            {
              type: "retrieval",
              query: "memory",
              results: [
                {
                  text: "Stored preference note.",
                  score: 0.91,
                  source: "memory/MEMORY.md",
                },
              ],
            },
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 6 steps.",
              run_id: "plan-run-leak",
              plan: {
                goal: "Find top T-cell papers",
                steps: [
                  { step_id: "1", intent: "Search PubMed" },
                  { step_id: "2", intent: "Shortlist papers" },
                  { step_id: "3", intent: "Check recency" },
                  { step_id: "4", intent: "Check influence" },
                  { step_id: "5", intent: "Draft summaries" },
                  { step_id: "6", intent: "Verify final picks" },
                ],
              },
            },
            {
              type: "text",
              text: leakedPlannerText,
            },
          ],
        })}
      />
    );

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Looked at memory.")).toBeTruthy();
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 6-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Search PubMed.")).toBeTruthy();
    expect(screen.getByText("2. Shortlist papers.")).toBeTruthy();
    expect(screen.getByText("3. Check recency.")).toBeTruthy();
    expect(screen.getByText("4. Check influence.")).toBeTruthy();
    expect(screen.getByText("5. Draft summaries.")).toBeTruthy();
    expect(screen.getByText("6. Verify final picks.")).toBeTruthy();
    expect(screen.queryByText("Then continue through 2 more steps.")).toBeNull();
    expect(screen.queryByText(/I'll help you find the top three papers/i)).toBeNull();
    expect(screen.queryByText(/Let me search PubMed/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Identify/i)).toBeNull();
    expect(screen.queryByText(/"constraints":\["Becau/i)).toBeNull();
  });

  it("shows every plan step in the planning rail without truncating long step text", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 5 steps.",
              run_id: "plan-run-t-cells",
              plan: {
                goal: "Find top T-cell papers",
                steps: [
                  {
                    step_id: "scope",
                    intent:
                      "Define the search scope and ranking rubric for T-cell literature so downstream triage favors original, high-impact studies.",
                  },
                  {
                    step_id: "search",
                    intent:
                      "Search PubMed broadly for recent T-cell papers and collect an initial candidate pool with enough breadth for later filtering.",
                  },
                  {
                    step_id: "refine",
                    intent:
                      "Refine the candidate pool to papers most likely to be highly cited and biologically influential rather than generic reviews.",
                  },
                  {
                    step_id: "retrieve",
                    intent:
                      "Retrieve authoritative PubMed evidence cards and cached article payloads for the strongest papers before summarizing them.",
                  },
                  {
                    step_id: "rank",
                    intent:
                      "Rank the final shortlist and draft concise evidence-backed summaries explaining why each paper stands out.",
                  },
                ],
              },
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 5-step plan.")).toBeTruthy();
    expect(
      screen.getByText(
        "1. Define the search scope and ranking rubric for T-cell literature so downstream triage favors original, high-impact studies."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "2. Search PubMed broadly for recent T-cell papers and collect an initial candidate pool with enough breadth for later filtering."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "3. Refine the candidate pool to papers most likely to be highly cited and biologically influential rather than generic reviews."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "4. Retrieve authoritative PubMed evidence cards and cached article payloads for the strongest papers before summarizing them."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "5. Rank the final shortlist and draft concise evidence-backed summaries explaining why each paper stands out."
      )
    ).toBeTruthy();
    expect(screen.queryByText(/Then continue through/i)).toBeNull();
  });

  it("hides helper-only planner turns when no user-facing answer remains", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "tool_use",
              tool: "plan_agent",
              input: "Check readiness",
              run_id: "plan-run-legacy",
            },
            {
              type: "tool_result",
              tool: "plan_agent",
              output: "planner summary",
              run_id: "plan-run-legacy",
              result: makeGenericToolResultEnvelope({
                tool_name: "plan_agent",
                summary: "Planner produced 2 steps.",
                structured_payload: {
                  agent_type: "plan",
                  plan: {
                    goal: "Check readiness",
                    steps: [
                      { step_id: "collect", intent: "Inspect sample sheet" },
                      { step_id: "report", intent: "Decide readiness" },
                    ],
                  },
                  tool_trace: [{ tool: "search_knowledge_base", summary: "context" }],
                },
              }),
            },
            {
              type: "text",
              text:
                "I'll help you assess readiness. Let me start by creating a plan. " +
                '{"goal":"Check readiness","steps":[{"step_id":"collect","intent":"Inspect sample sheet"},{"step_id":"report","intent":"Decide readiness"}]}',
            },
          ],
        })}
      />
    );

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Ran source search.")).toBeTruthy();
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Inspect sample sheet.")).toBeTruthy();
    expect(screen.getByText("2. Decide readiness.")).toBeTruthy();
    expect(screen.queryByText("Planning 2 steps to check readiness.")).toBeNull();
    expect(screen.queryByText(/I'll help you assess readiness/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Check readiness"/i)).toBeNull();
  });

  it("hides completed planning-only messages that only contain planner narration and raw plan json", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          startedAtMs: 0,
          endedAtMs: 19_000,
          blocks: [
            {
              type: "retrieval",
              query: "memory",
              results: [
                {
                  text: "Memory context.",
                  score: 0.91,
                  source: "memory/MEMORY.md",
                },
              ],
            },
            {
              type: "text",
              text:
                "I'll help you find the top three novel papers around T-cells. " +
                "Let me start by planning this task to ensure I use the most effective approach." +
                '{"goal":"Identify papers","steps":[{"step_id":"1","intent":"Search PubMed"}]}',
            },
          ],
        })}
      />
    );

    expect(screen.queryByLabelText("Assistant response")).toBeNull();
    expect(screen.queryByText(/top three novel papers around T-cells/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Identify papers"/i)).toBeNull();
    expect(screen.queryByText("Looked at memory.")).toBeNull();
    expect(screen.queryByText("Worked for 19s.")).toBeNull();
  });

  it("hides completed tool-chatter messages that only narrate the next search step", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          startedAtMs: 0,
          endedAtMs: 7_000,
          blocks: [
            {
              type: "tool_use",
              tool: "ncbi_eutils",
              input: '{"operation":"esearch"}',
              run_id: "tool-search-1",
            },
            {
              type: "tool_result",
              tool: "ncbi_eutils",
              output: "ok",
              run_id: "tool-search-1",
              result: makeToolResult("ncbi_eutils"),
            },
            {
              type: "text",
              text:
                "I see many review articles. Let me search for original research articles instead focusing on novel discoveries.",
            },
          ],
        })}
      />
    );

    expect(screen.queryByLabelText("Assistant response")).toBeNull();
    expect(screen.queryByText(/review articles/i)).toBeNull();
    expect(screen.queryByText(/original research articles/i)).toBeNull();
    expect(screen.queryByText(/Started ncbi eutils/i)).toBeNull();
    expect(screen.queryByText(/Ran ncbi eutils/i)).toBeNull();
    expect(screen.queryByText("Worked for 7.0s.")).toBeNull();
  });

  it("hides completed tool-chatter messages that only narrate plan execution", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          startedAtMs: 0,
          endedAtMs: 7_000,
          blocks: [
            {
              type: "tool_use",
              tool: "ncbi_eutils",
              input: '{"operation":"esearch"}',
              run_id: "tool-search-2",
            },
            {
              type: "tool_result",
              tool: "ncbi_eutils",
              output: "ok",
              run_id: "tool-search-2",
              result: makeToolResult("ncbi_eutils"),
            },
            {
              type: "text",
              text:
                "Now let me execute the plan. First, I'll search PubMed for recent T-cell papers with high impact.",
            },
          ],
        })}
      />
    );

    expect(screen.queryByLabelText("Assistant response")).toBeNull();
    expect(screen.queryByText(/execute the plan/i)).toBeNull();
    expect(screen.queryByText(/search pubmed/i)).toBeNull();
    expect(screen.queryByText(/Started ncbi eutils/i)).toBeNull();
    expect(screen.queryByText(/Ran ncbi eutils/i)).toBeNull();
    expect(screen.queryByText("Worked for 7.0s.")).toBeNull();
  });

  it("hides completed tool-chatter messages that only narrate a more specific follow-up search", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          startedAtMs: 0,
          endedAtMs: 8_200,
          blocks: [
            {
              type: "tool_use",
              tool: "ncbi_eutils",
              input: '{"operation":"esearch"}',
              run_id: "tool-search-3",
            },
            {
              type: "tool_result",
              tool: "ncbi_eutils",
              output: "ok",
              run_id: "tool-search-3",
              result: makeToolResult("ncbi_eutils"),
            },
            {
              type: "text",
              text:
                "Let me get more specific and search for high-impact T-cell papers in top journals.",
            },
          ],
        })}
      />
    );

    expect(screen.queryByLabelText("Assistant response")).toBeNull();
    expect(screen.queryByText(/get more specific/i)).toBeNull();
    expect(screen.queryByText(/top journals/i)).toBeNull();
    expect(screen.queryByText(/Started ncbi eutils/i)).toBeNull();
    expect(screen.queryByText(/Ran ncbi eutils/i)).toBeNull();
    expect(screen.queryByText("Worked for 8.2s.")).toBeNull();
  });

  it("hides updated planner thought-process text from one merged block while keeping the actual follow-up answer", () => {
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
                "1. Re-check citations\n2. Repair answer\n\nUpdated final answer.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Updated the 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Re-check citations.")).toBeTruthy();
    expect(screen.getByText("2. Repair answer.")).toBeTruthy();
    expect(screen.queryByText("Planning 2 steps to repair the answer.")).toBeNull();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
    expect(screen.queryByText(/update the plan/i)).toBeNull();
    expect(screen.queryByText(/^1\. Re-check citations$/i)).toBeNull();
    expect(screen.queryByText(/^2\. Repair answer$/i)).toBeNull();
  });

  it("keeps a legitimate numbered final answer even when a nearby plan block exists", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "updated",
              summary: "Planner updated the repair path.",
              run_id: "plan-run-6",
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
                "1. Add the missing citation.\n2. Explain why the original claim changed.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Updated the 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Re-check citations.")).toBeTruthy();
    expect(screen.getByText("2. Repair answer.")).toBeTruthy();
    expect(screen.queryByText("Planning 2 steps to repair the answer.")).toBeNull();
    expect(screen.getByText("Add the missing citation.")).toBeTruthy();
    expect(
      screen.getByText("Explain why the original claim changed.")
    ).toBeTruthy();
  });

  it("shows full structured planning steps even when the intents are long", () => {
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

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(
      screen.getByText(
        "1. Establish the review scope and identify the minimum project context needed to judge readiness, including study design and comparison groups."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "2. Inspect core files and metadata needed for readiness, including sample sheets, batch variables, reference genome versions, and QC summaries."
      )
    ).toBeTruthy();
    expect(screen.queryByText(/^step_1_scope_and_inventory$/i)).toBeNull();
  });

  it("shows full planner intents in the planning rail without exposing raw step ids", () => {
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

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 3-step plan.")).toBeTruthy();
    expect(
      screen.getByText(
        "1. Inspect core files and metadata needed for readiness, including sample sheets and QC summaries."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "2. Check for compliance and safety issues that could block the analysis before it begins."
      )
    ).toBeTruthy();
    expect(
      screen.getByText(
        "3. Summarize likely analysis stages and produce a concise readiness recommendation."
      )
    ).toBeTruthy();
    expect(screen.queryByText(/^1$/)).toBeNull();
    expect(screen.queryByText(/^2$/)).toBeNull();
    expect(screen.queryByText(/^3$/)).toBeNull();
  });

  it("shows planning steps for legacy or partial step payloads without hiding the section body", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 4 steps.",
              run_id: "plan-run-legacy-steps",
              plan: {
                goal: "Check readiness",
                steps: [
                  "Inspect the metadata sheet",
                  { step_id: "2", title: "Confirm required controls" },
                  {
                    step_id: "qc_review",
                    description: "Review QC thresholds before execution",
                  },
                  { step_id: "4" },
                ],
              },
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 4-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Inspect the metadata sheet.")).toBeTruthy();
    expect(screen.getByText("2. Confirm required controls.")).toBeTruthy();
    expect(
      screen.getByText("3. Review QC thresholds before execution.")
    ).toBeTruthy();
    expect(screen.getByText("4. Step 4.")).toBeTruthy();
  });

  it("hides single-step planner-only labels from the main chat transcript", () => {
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

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 1-step plan.")).toBeTruthy();
    expect(
      screen.getByText(
        "1. Inspect the local project context and workflow notes before proceeding."
      )
    ).toBeTruthy();
  });

  it("hides verifier narration and raw verification json when the verification section already captures it", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "tool_use",
              tool: "verification_agent",
              input: "verify the draft",
              run_id: "verify-run-2",
            },
            {
              type: "tool_result",
              tool: "verification_agent",
              output:
                "Verifier verdict: repair_required. The draft is directionally correct, but it needs one citation.",
              run_id: "verify-run-2",
              result: makeToolResult("verification_agent"),
            },
            {
              type: "verification",
              summary:
                "Verifier verdict: repair_required. The draft is directionally correct, but it needs one citation.",
              verdict: "repair_required",
              run_id: "verify-run-2",
              verification: {
                verdict: "repair_required",
                summary: "Add one citation.",
                checks: [
                  {
                    name: "support",
                    status: "fail",
                    note: "Need evidence.",
                  },
                ],
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

    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Support check failed: Need evidence.")).toBeTruthy();
    expect(screen.getByText("Missing citation.")).toBeTruthy();
    expect(screen.queryByText(/Started verification/i)).toBeNull();
    expect(screen.queryByText(/Ran verification/i)).toBeNull();
    expect(screen.queryByText("Verification result")).toBeNull();
    expect(screen.queryByText(/verification agent/i)).toBeNull();
    expect(screen.queryByText(/"verdict":"repair_required"/i)).toBeNull();
    expect(screen.queryByText("Add one citation.")).toBeNull();
    expect(
      screen.queryByText(
        /The draft is directionally correct, but it needs one citation/i
      )
    ).toBeNull();
  });

  it("keeps verifier tool completion generic before a structured verification result arrives", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          content: "Updated answer.",
          blocks: [
            {
              type: "tool_use",
              tool: "verification_agent",
              input: "verify the revised draft",
              run_id: "verify-run-generic",
            },
            {
              type: "tool_result",
              tool: "verification_agent",
              output:
                "The answer still misses one citation and should add the readiness checklist result before delivery.",
              run_id: "verify-run-generic",
              result: makeToolResult("verification_agent"),
            },
            {
              type: "text",
              text: "Updated answer.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Started verification.")).toBeTruthy();
    expect(screen.getByText("Ran verification.")).toBeTruthy();
    expect(screen.getByText("Updated answer.")).toBeTruthy();
    expect(
      screen.queryByText(
        /misses one citation and should add the readiness checklist result/i
      )
    ).toBeNull();
  });

  it("suppresses malformed verifier json while keeping the generic verification rail visible", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          startedAtMs: 0,
          endedAtMs: 5_700,
          blocks: [
            {
              type: "tool_use",
              tool: "verification_agent",
              input: "verify the drafted citations",
              run_id: "verify-run-malformed",
            },
            {
              type: "tool_result",
              tool: "verification_agent",
              output: "Verifier response streamed.",
              run_id: "verify-run-malformed",
              result: makeToolResult("verification_agent"),
            },
            {
              type: "text",
              text:
                '{"ver. It appears to have fabricated or not credibly answered the task.","checks":[{"name":"Paper relevance","status":"fail","note":"The cited papers do not match the requested topic."}],"issues":["At least one citation appears unreliable"]',
            },
          ],
        })}
      />
    );

    expect(screen.getByLabelText("Assistant response")).toBeTruthy();
    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Started verification.")).toBeTruthy();
    expect(screen.getByText("Ran verification.")).toBeTruthy();
    expect(screen.queryByText(/^\{"ver/i)).toBeNull();
    expect(screen.queryByText(/Paper relevance/i)).toBeNull();
    expect(screen.queryByText(/At least one citation appears unreliable/i)).toBeNull();
    expect(screen.queryByText("Worked for 5.7s.")).toBeNull();
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
                checks: [
                  {
                    name: "readiness coverage",
                    status: "fail",
                    note: "RNA-seq-specific checks are missing.",
                  },
                ],
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

    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.queryByText("Verification result")).toBeNull();
    expect(
      screen.getByText(
        "Add the missing RNA-seq-specific readiness checks before finalizing the answer."
      )
    ).toBeTruthy();
  });

  it("strips colon-prefixed verification feedback json while keeping the repaired answer", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "verification",
              summary: "Verifier verdict: repair_required. Add one citation.",
              verdict: "repair_required",
              run_id: "verify-run-4",
              verification: {
                verdict: "repair_required",
                summary: "Add one citation.",
                issues: ["Missing citation."],
              },
            },
            {
              type: "text",
              text:
                'Let me refine the response based on the verification feedback:{"verdict":"repair_required","summary":"Add one citation.","issues":["Missing citation."]}\n\nRepaired answer.',
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Missing citation.")).toBeTruthy();
    expect(screen.getByText("Repaired answer.")).toBeTruthy();
    expect(screen.queryByText(/verification feedback/i)).toBeNull();
    expect(screen.queryByText(/"verdict":"repair_required"/i)).toBeNull();
    expect(screen.queryByText("Add one citation.")).toBeNull();
  });

  it("strips verification feedback json without a verdict key while keeping the repaired answer", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "verification",
              summary: "Verifier verdict: repair_required. Add one citation.",
              verdict: "repair_required",
              run_id: "verify-run-4b",
              verification: {
                verdict: "repair_required",
                summary: "Add one citation.",
                issues: ["Missing citation."],
                repair_instructions: ["Cite the evidence review artifact."],
              },
            },
            {
              type: "text",
              text:
                'Let me refine the response based on the verification feedback:{"summary":"Add one citation.","issues":["Missing citation."],"repair_instructions":["Cite the evidence review artifact."]}\n\nRepaired answer.',
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Cite the evidence review artifact.")).toBeTruthy();
    expect(screen.getByText("Repaired answer.")).toBeTruthy();
    expect(screen.queryByText(/verification feedback/i)).toBeNull();
    expect(screen.queryByText(/"summary":"Add one citation\."/i)).toBeNull();
    expect(screen.queryByText(/"repair_instructions":/i)).toBeNull();
  });

  it("strips leaked planning and verification process lines from the final answer text", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 2 steps.",
              run_id: "plan-run-7",
              plan: {
                goal: "Repair the answer",
                steps: [
                  { step_id: "collect", intent: "Inspect memory" },
                  { step_id: "repair", intent: "Repair answer" },
                ],
              },
            },
            {
              type: "verification",
              summary: "Verifier verdict: repair_required. Add one citation.",
              verdict: "repair_required",
              run_id: "verify-run-5",
              verification: {
                verdict: "repair_required",
                summary: "Add one citation.",
                issues: ["Missing citation."],
              },
            },
            {
              type: "text",
              text:
                "Started planning.\n" +
                "Ran planning: Planner produced 2 steps.\n" +
                "Started verification.\n" +
                "Ran verification: Verifier verdict: repair_required. Add one citation.\n\n" +
                "Updated final answer.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Inspect memory.")).toBeTruthy();
    expect(screen.getByText("2. Repair answer.")).toBeTruthy();
    expect(screen.queryByText("Planning 2 steps to repair the answer.")).toBeNull();
    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Missing citation.")).toBeTruthy();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
    expect(screen.queryByText(/^Started planning\.$/i)).toBeNull();
    expect(screen.queryByText(/^Ran planning:/i)).toBeNull();
    expect(screen.queryByText(/^Started verification\.$/i)).toBeNull();
    expect(screen.queryByText(/^Ran verification:/i)).toBeNull();
  });

  it("strips verifier process chatter from text blocks even before a structured verification block arrives", () => {
    render(
      <ChatMessage
        message={makeAssistantMessage({
          blocks: [
            {
              type: "plan",
              event: "created",
              summary: "Planner produced 2 steps.",
              run_id: "plan-run-8",
              plan: {
                goal: "Repair the answer",
                steps: [
                  { step_id: "collect", intent: "Inspect memory" },
                  { step_id: "repair", intent: "Repair answer" },
                ],
              },
            },
            {
              type: "tool_use",
              tool: "verification_agent",
              input: "verify the repaired answer",
              run_id: "verify-run-6",
            },
            {
              type: "tool_result",
              tool: "verification_agent",
              output: "Verifier verdict: repair_required. Add one citation.",
              run_id: "verify-run-6",
              result: makeToolResult("verification_agent"),
            },
            {
              type: "text",
              text:
                "Started verification.\n" +
                "Ran verification: Verifier verdict: repair_required. Add one citation.\n\n" +
                "Updated final answer.",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Inspect memory.")).toBeTruthy();
    expect(screen.getByText("2. Repair answer.")).toBeTruthy();
    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Started verification.")).toBeTruthy();
    expect(screen.getByText("Ran verification.")).toBeTruthy();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
    expect(
      screen.queryByText(
        /Verifier verdict: repair_required\. Add one citation\./i
      )
    ).toBeNull();
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
    expect(screen.getByText("Updated the 1-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Repair answer.")).toBeTruthy();
    expect(screen.queryByText("Planning 1 step to repair the answer.")).toBeNull();
    expect(screen.queryByText("Repair answer")).toBeNull();
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
