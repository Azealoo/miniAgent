import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  Message,
  RetrievalResult,
  SessionContentBlock,
  ToolCall,
} from "@/lib/types";
import {
  makeGenericToolResultEnvelope,
  makeHistoryMessage,
  makeSessionContinuitySummary,
} from "@/test/fixtures";
import { installMockFetch, jsonResponse, route } from "@/test/mock-fetch";
import SessionHistorySummary from "./SessionHistorySummary";

const mockSendMessage = vi.fn(async () => {});

vi.mock("@/lib/store", () => ({
  useApp: () => ({
    isStreaming: false,
    sendMessage: mockSendMessage,
  }),
  useAppOptional: () => null,
}));

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

function makeMessage(overrides: MessageFixtureOverrides = {}): Message {
  const { tool_calls, retrievals, blocks, ...rest } = overrides;
  const content = rest.content ?? "";
  const derivedBlocks =
    blocks ?? buildBlocksFromLegacy(tool_calls, retrievals, content);
  return {
    id: rest.id ?? `message-${Math.random().toString(16).slice(2)}`,
    role: rest.role ?? "assistant",
    content,
    blocks: derivedBlocks,
    ...rest,
  };
}

afterEach(() => {
  mockSendMessage.mockClear();
});

describe("SessionHistorySummary", () => {
  it("compacts older visible turns while keeping recent turns expanded", async () => {
    const user = userEvent.setup();
    const messages: Message[] = [
      makeMessage({
        id: "user-1",
        role: "user",
        content: "Review the alpha run.",
        request_id: "request-1",
      }),
      makeMessage({
        id: "assistant-1",
        role: "assistant",
        content: "Alpha run summary.",
        request_id: "request-1",
        retrievals: [
          {
            source: "knowledge/alpha.md",
            score: 0.9,
            text: "Alpha lab note.",
          },
        ],
        tool_calls: [
          {
            tool: "read_file",
            input: "knowledge/alpha.md",
            output: "Read knowledge/alpha.md.",
            run_id: "tool-1",
            result: makeGenericToolResultEnvelope({
              artifact_refs: [
                {
                  artifact_type: "file",
                  path: "knowledge/alpha.md",
                  label: "alpha.md",
                },
              ],
              structured_payload: {
                path: "knowledge/alpha.md",
                content_preview: "Alpha lab note.",
              },
              summary: "Read knowledge/alpha.md.",
            }),
          },
        ],
      }),
      makeMessage({
        id: "user-2",
        role: "user",
        content: "Review the beta run.",
        request_id: "request-2",
      }),
      makeMessage({
        id: "assistant-2",
        role: "assistant",
        content: "Beta run summary.",
        request_id: "request-2",
      }),
      makeMessage({
        id: "user-3",
        role: "user",
        content: "Review the gamma run.",
        request_id: "request-3",
      }),
      makeMessage({
        id: "assistant-3",
        role: "assistant",
        content: "Gamma run summary.",
        request_id: "request-3",
      }),
      makeMessage({
        id: "user-4",
        role: "user",
        content: "Review the delta run.",
        request_id: "request-4",
      }),
      makeMessage({
        id: "assistant-4",
        role: "assistant",
        content: "Delta run summary.",
        request_id: "request-4",
      }),
    ];

    render(
      <SessionHistorySummary
        currentSessionId="session-alpha"
        messages={messages}
        continuitySummaries={[]}
      />
    );

    expect(screen.getByText("Earlier Turns")).toBeTruthy();
    expect(screen.getByText("Review the alpha run.")).toBeTruthy();
    expect(screen.getByText("1 tool")).toBeTruthy();
    expect(screen.getByText("1 source")).toBeTruthy();
    expect(screen.getByText("Beta run summary.")).toBeTruthy();
    expect(screen.getByText("Gamma run summary.")).toBeTruthy();
    expect(screen.getByText("Delta run summary.")).toBeTruthy();

    await user.click(
      screen.getByRole("button", {
        name: "Show older turn Review the alpha run.",
      })
    );

    expect((await screen.findAllByText("Alpha run summary.")).length).toBeGreaterThan(0);
  });

  it("uses normalized assistant content for older-turn summaries so planner chatter stays hidden", () => {
    const messages: Message[] = [
      makeMessage({
        id: "user-plan-1",
        role: "user",
        content: "Check readiness.",
        request_id: "request-plan-1",
      }),
      makeMessage({
        id: "assistant-plan-1",
        role: "assistant",
        content: "",
        request_id: "request-plan-1",
        blocks: [
          {
            type: "plan",
            event: "updated",
            summary: "Planner updated the repair path.",
            run_id: "plan-run-1",
            plan: {
              goal: "Repair the answer",
              steps: [{ step_id: "repair", intent: "Repair answer" }],
            },
          },
          {
            type: "text",
            text:
              "Based on what I found, I'll update the plan. " +
              "1. Repair answer\n\nUpdated final answer.",
          },
        ],
      }),
      makeMessage({
        id: "user-2",
        role: "user",
        content: "Review beta.",
        request_id: "request-2",
      }),
      makeMessage({
        id: "assistant-2",
        role: "assistant",
        content: "Beta run summary.",
        request_id: "request-2",
      }),
      makeMessage({
        id: "user-3",
        role: "user",
        content: "Review gamma.",
        request_id: "request-3",
      }),
      makeMessage({
        id: "assistant-3",
        role: "assistant",
        content: "Gamma run summary.",
        request_id: "request-3",
      }),
      makeMessage({
        id: "user-4",
        role: "user",
        content: "Review delta.",
        request_id: "request-4",
      }),
      makeMessage({
        id: "assistant-4",
        role: "assistant",
        content: "Delta run summary.",
        request_id: "request-4",
      }),
    ];

    render(
      <SessionHistorySummary
        currentSessionId="session-history"
        messages={messages}
        continuitySummaries={[]}
      />
    );

    expect(screen.getByText("Earlier Turns")).toBeTruthy();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
    expect(screen.queryByText(/update the plan/i)).toBeNull();
  });

  it("hides helper-only replan json from expanded older turns", async () => {
    const user = userEvent.setup();
    const messages: Message[] = [
      makeMessage({
        id: "user-history-1",
        role: "user",
        content: "Repair the earlier answer.",
        request_id: "request-history-1",
      }),
      makeMessage({
        id: "assistant-history-1a",
        role: "assistant",
        content:
          "Based on what I found, I'll update the plan. " +
          '{"goal":"Repair the answer","steps":[{"step_id":"repair","intent":"Repair answer"}]}',
        request_id: "request-history-1",
      }),
      makeMessage({
        id: "assistant-history-1b",
        role: "assistant",
        content: "Updated final answer.",
        request_id: "request-history-1",
      }),
      makeMessage({
        id: "user-history-2",
        role: "user",
        content: "Review beta.",
        request_id: "request-history-2",
      }),
      makeMessage({
        id: "assistant-history-2",
        role: "assistant",
        content: "Beta run summary.",
        request_id: "request-history-2",
      }),
      makeMessage({
        id: "user-history-3",
        role: "user",
        content: "Review gamma.",
        request_id: "request-history-3",
      }),
      makeMessage({
        id: "assistant-history-3",
        role: "assistant",
        content: "Gamma run summary.",
        request_id: "request-history-3",
      }),
      makeMessage({
        id: "user-history-4",
        role: "user",
        content: "Review delta.",
        request_id: "request-history-4",
      }),
      makeMessage({
        id: "assistant-history-4",
        role: "assistant",
        content: "Delta run summary.",
        request_id: "request-history-4",
      }),
    ];

    render(
      <SessionHistorySummary
        currentSessionId="session-expanded-history"
        messages={messages}
        continuitySummaries={[]}
      />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Show older turn Repair the earlier answer.",
      })
    );

    expect(
      (await screen.findAllByText("Updated final answer.")).length
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/update the plan/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Repair the answer"/i)).toBeNull();
  });

  it("hides helper-only replan json from recent visible turns", () => {
    const messages: Message[] = [
      makeMessage({
        id: "user-recent-1",
        role: "user",
        content: "Initial request.",
        request_id: "request-recent-1",
      }),
      makeMessage({
        id: "assistant-recent-1",
        role: "assistant",
        content: "Initial answer.",
        request_id: "request-recent-1",
      }),
      makeMessage({
        id: "user-recent-2",
        role: "user",
        content: "Please repair that.",
        request_id: "request-recent-2",
      }),
      makeMessage({
        id: "assistant-recent-2a",
        role: "assistant",
        content:
          "Based on what I found, I'll update the plan. " +
          '{"goal":"Repair the answer","steps":[{"step_id":"repair","intent":"Repair answer"}]}',
        request_id: "request-recent-2",
      }),
      makeMessage({
        id: "assistant-recent-2b",
        role: "assistant",
        content: "Repaired answer.",
        request_id: "request-recent-2",
      }),
    ];

    render(
      <SessionHistorySummary
        currentSessionId="session-recent-history"
        messages={messages}
        continuitySummaries={[]}
      />
    );

    expect(screen.getByText("Initial answer.")).toBeTruthy();
    expect(screen.getByText("Repaired answer.")).toBeTruthy();
    expect(screen.queryByText(/update the plan/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Repair the answer"/i)).toBeNull();
  });

  it("collapses verification retry turns into one visible assistant response", () => {
    const messages: Message[] = [
      makeMessage({
        id: "user-verify-1",
        role: "user",
        content: "Check this request for readiness.",
        request_id: "request-verify-1",
      }),
      makeMessage({
        id: "assistant-verify-1a",
        role: "assistant",
        content: "Draft answer without citation.",
        request_id: "request-verify-1",
        blocks: [
          {
            type: "verification",
            summary: "Verifier verdict: repair_required. Add one citation.",
            verdict: "repair_required",
            run_id: "verify-run-1",
            verification: {
              verdict: "repair_required",
              summary: "Add one citation.",
              issues: ["Missing citation."],
              repair_instructions: ["Cite the evidence review artifact."],
            },
          },
          {
            type: "text",
            text: "Draft answer without citation.",
          },
        ],
      }),
      makeMessage({
        id: "assistant-verify-1b",
        role: "assistant",
        content: "Repaired answer with citation.",
        request_id: "request-verify-1",
      }),
    ];

    render(
      <SessionHistorySummary
        currentSessionId="session-verify-retry"
        messages={messages}
        continuitySummaries={[]}
      />
    );

    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Repaired answer with citation.")).toBeTruthy();
    expect(screen.queryByText("Draft answer without citation.")).toBeNull();
    expect(screen.getAllByLabelText("Assistant response")).toHaveLength(1);
  });

  it("reopens archived continuity summaries on demand", async () => {
    const user = userEvent.setup();
    const fetchMock = installMockFetch([
      route(
        "GET",
        "/api/sessions/session-alpha/archives/1712012234",
        () =>
          jsonResponse([
            { role: "user", content: "Archived request." },
            makeHistoryMessage({
              request_id: "request-archive-1",
              content: "",
              tool_calls: [],
              retrievals: [],
              blocks: [
                {
                  type: "retrieval",
                  query: "archive review",
                  results: [
                    {
                      source: "knowledge/archive-history.md",
                      score: 0.82,
                      text: "Archived study context.",
                    },
                  ],
                },
                {
                  type: "text",
                  text: "Archived answer.",
                },
              ],
            }),
          ])
      ),
    ]);

    render(
      <SessionHistorySummary
        currentSessionId="session-alpha"
        messages={[
          makeMessage({
            id: "recent-user",
            role: "user",
            content: "Current request.",
            request_id: "request-current",
          }),
          makeMessage({
            id: "recent-assistant",
            role: "assistant",
            content: "Current answer.",
            request_id: "request-current",
          }),
        ]}
        continuitySummaries={[makeSessionContinuitySummary()]}
      />
    );

    expect(screen.getByText("Archived Work")).toBeTruthy();
    expect(
      screen.getByText("Reviewed earlier RNA-seq QC and evidence synthesis work.")
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Open archived turns" }));

    expect(await screen.findByText("Archived answer.")).toBeTruthy();
    expect(await screen.findByText("Looked at archive-history.md.")).toBeTruthy();

    fetchMock.restore();
  });
});
