import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import AppShell from "@/components/layout/AppShell";
import {
  makeAccessProbe,
  makeGenericToolResultEnvelope,
  makeSession,
  makeTokenStats,
} from "@/test/fixtures";
import { installMockFetch, jsonResponse, route, sseResponse } from "@/test/mock-fetch";

type AccessState = "granted" | "token_required" | "forbidden" | "server_misconfigured";

function buildAccessRoute(config: {
  admin: AccessState;
  execution: AccessState;
  inspection: AccessState;
}) {
  return route("GET", "/api/access/probe", (_request, url) => {
    const scope = url.searchParams.get("scope") as keyof typeof config;
    const state = config[scope];

    if (state === "granted") {
      return jsonResponse(makeAccessProbe(scope));
    }
    if (state === "token_required") {
      return jsonResponse({ detail: "Bearer token required." }, { status: 401 });
    }
    if (state === "forbidden") {
      return jsonResponse(
        { detail: "This route requires local access or a configured bearer token." },
        { status: 403 }
      );
    }

    return jsonResponse(
      { detail: "Configured bearer token environment variable BIOAPEX_TOKEN is empty." },
      { status: 503 }
    );
  });
}

function buildBaseRoutes(options?: {
  sessions?:
    | Array<ReturnType<typeof makeSession>>
    | (() => Array<ReturnType<typeof makeSession>>);
}) {
  const sessions = options?.sessions;
  const getSessions =
    typeof sessions === "function" ? sessions : () => sessions ?? [];
  return [
    route("GET", "/", () => jsonResponse({ service: "miniOpenClaw", status: "ok" })),
    buildAccessRoute({
      inspection: "granted",
      execution: "granted",
      admin: "granted",
    }),
    route("GET", "/api/sessions", () => jsonResponse(getSessions())),
  ];
}

let activeFetchMock: ReturnType<typeof installMockFetch> | null = null;

function hasTextContent(text: string) {
  return (_content: string, node: Element | null) =>
    node?.textContent?.includes(text) ?? false;
}

afterEach(() => {
  activeFetchMock?.restore();
  activeFetchMock = null;
});

describe("AppShell chat-only contract", () => {
  it("renders the chat-only shell without the removed workspace surfaces", async () => {
    activeFetchMock = installMockFetch(buildBaseRoutes());

    render(React.createElement(AppShell));

    expect(await screen.findByText("Chat Engine")).toBeTruthy();
    expect(screen.getByRole("button", { name: /new chat/i })).toBeTruthy();
    expect(screen.getByPlaceholderText(/search sessions/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /studies/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /ops/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /artifacts/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /upload reference file/i })).toBeNull();
    expect(screen.queryByText("Quick Start")).toBeNull();
    expect(screen.queryByText("Recent Files")).toBeNull();
    expect(screen.queryByText(/chat-only shell/i)).toBeNull();
  });

  it("auto-creates a session, keeps one visible final assistant response per turn, and exposes streamed process artifacts in the inspector", async () => {
    const createdSession = makeSession({
      id: "session-chat-only",
      title: "New Chat",
      updated_at: Date.parse("2026-04-02T18:00:00Z"),
      message_count: 0,
    });
    let sessions: Array<ReturnType<typeof makeSession>> = [];
    const generatedTitle = "Chat-only checklist pass";

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions: () => sessions }),
      route("POST", "/api/sessions", () => {
        sessions = [createdSession];
        return jsonResponse(createdSession);
      }),
      route("POST", `/api/sessions/${createdSession.id}/generate-title`, () => {
        sessions = [{ ...createdSession, title: generatedTitle, message_count: 2 }];
        return jsonResponse({
          session_id: createdSession.id,
          title: generatedTitle,
        });
      }),
      route(
        "POST",
        "/api/chat",
        async (request) => {
          const body = (await request.json()) as Record<string, unknown>;
          expect(body).toMatchObject({
            message: "Check this request for readiness.",
            session_id: createdSession.id,
          });

          return sseResponse(
            [
              {
                type: "retrieval",
                query: "readiness review",
                results: [
                  {
                    source: "knowledge/readiness-checklist.md",
                    score: 0.92,
                    text: "Inspect the readiness checklist before execution.",
                  },
                ],
              },
              {
                type: "tool_start",
                tool: "read_file",
                input: "knowledge/readiness-checklist.md",
                run_id: "tool-1",
                request_id: "request-chat-only-1",
              },
              {
                type: "tool_end",
                tool: "read_file",
                output: "Read knowledge/readiness-checklist.md.",
                run_id: "tool-1",
                request_id: "request-chat-only-1",
                result: makeGenericToolResultEnvelope({
                  artifact_refs: [
                    {
                      artifact_type: "file",
                      path: "knowledge/readiness-checklist.md",
                      label: "readiness-checklist.md",
                    },
                  ],
                  structured_payload: {
                    path: "knowledge/readiness-checklist.md",
                    content_preview: "Inspect the readiness checklist before execution.",
                  },
                  summary: "Read knowledge/readiness-checklist.md.",
                }),
              },
              {
                type: "plan_created",
                summary: "Planner produced 2 steps.",
                plan: {
                  goal: "Check readiness",
                  steps: [
                    { step_id: "collect", intent: "Look at memory" },
                    { step_id: "report", intent: "Run readiness check" },
                  ],
                },
                request_id: "request-chat-only-1",
              },
              {
                type: "verification_result",
                summary: "Verifier verdict: repair_required. Add one citation.",
                verdict: "repair_required",
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
                  repair_instructions: ["Cite the evidence review artifact."],
                },
                request_id: "request-chat-only-1",
              },
              { type: "token", content: "BioAPEX reviewed the request." },
              {
                type: "new_response",
                request_id: "request-chat-only-1",
              },
              { type: "token", content: "BioAPEX prepared the final recommendation." },
              {
                type: "done",
                content: "BioAPEX prepared the final recommendation.",
                request_id: "request-chat-only-1",
              },
            ],
            { chunkSize: 23 }
          );
        }
      ),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    const composer = await screen.findByPlaceholderText(/ask any biology related questions/i);
    await user.type(composer, "Check this request for readiness.");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect(
      screen.getByText(hasTextContent("BioAPEX prepared the final recommendation."), {
        selector: "p",
      })
    ).toBeTruthy();
    expect(screen.queryByText("BioAPEX reviewed the request.")).toBeNull();
    expect(screen.getAllByLabelText("Assistant response")).toHaveLength(1);
    expect((await screen.findAllByText("Planning")).length).toBeGreaterThan(0);
    expect(screen.getByText("Prepared a 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Look at memory.")).toBeTruthy();
    expect(screen.getByText("2. Run readiness check.")).toBeTruthy();
    expect(screen.queryByText("Planning 2 steps to check readiness.")).toBeNull();
    expect((await screen.findAllByText("Verification")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Planner produced 2 steps.")).toBeNull();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Cite the evidence review artifact.")).toBeTruthy();
    expect(screen.queryByText("Verification result")).toBeNull();
    expect((await screen.findAllByText("readiness-checklist.md")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Turn compliance")).toBeNull();
    expect((await screen.findAllByText(generatedTitle)).length).toBeGreaterThan(0);
  });

  it("reconciles the completed turn with saved history so markdown formatting no longer needs a manual refresh", async () => {
    const createdSession = makeSession({
      id: "session-format-sync",
      title: "Format sync",
      updated_at: Date.parse("2026-04-03T18:30:00Z"),
      message_count: 0,
    });
    let sessions: Array<ReturnType<typeof makeSession>> = [];
    let historyRequests = 0;

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions: () => sessions }),
      route("POST", "/api/sessions", () => {
        sessions = [createdSession];
        return jsonResponse(createdSession);
      }),
      route("POST", "/api/chat", async (request) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body).toMatchObject({
          message: "Show the formatted checklist.",
          session_id: createdSession.id,
        });

        sessions = [{ ...createdSession, message_count: 2 }];

        return sseResponse(
          [
            {
              type: "token",
              content: "Final answer\n\n-Not formatted correctly",
              request_id: "request-format-sync-1",
            },
            {
              type: "done",
              content: "Final answer\n\n-Not formatted correctly",
              request_id: "request-format-sync-1",
            },
          ],
          { chunkSize: 17 }
        );
      }),
      route("GET", `/api/sessions/${createdSession.id}/history`, () => {
        historyRequests += 1;
        return jsonResponse([
          { role: "user", content: "Show the formatted checklist." },
          {
            role: "assistant",
            request_id: "request-format-sync-1",
            content: "Final answer\n\n- Not formatted correctly",
            blocks: [
              {
                type: "text",
                text: "Final answer\n\n- Not formatted correctly",
              },
            ],
          },
        ]);
      }),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    const composer = await screen.findByPlaceholderText(/ask any biology related questions/i);
    await user.type(composer, "Show the formatted checklist.");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect(
      await screen.findByText(hasTextContent("Final answer"), { selector: "p" })
    ).toBeTruthy();

    await waitFor(() => {
      expect(historyRequests).toBe(1);
      expect(screen.getByRole("listitem").textContent ?? "").toContain(
        "Not formatted correctly"
      );
    });
  });

  it("hides helper-only planning and verification history messages after reload while keeping the safe process sections", async () => {
    const session = makeSession({
      id: "session-helper-history",
      title: "Helper history",
      updated_at: Date.parse("2026-04-03T19:10:00Z"),
      message_count: 5,
    });

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions: [session] }),
      route("GET", `/api/sessions/${session.id}/history`, () =>
        jsonResponse([
          {
            role: "user",
            content: "Repair the answer.",
            request_id: "request-helper-history-1",
          },
          {
            role: "assistant",
            content:
              "Based on what I found, I'll update the plan. " +
              '{"goal":"Repair the answer","steps":[{"step_id":"recheck","intent":"Re-check citations"},{"step_id":"repair","intent":"Repair answer"}]}',
            request_id: "request-helper-history-1",
          },
          {
            role: "assistant",
            content: "",
            request_id: "request-helper-history-1",
            blocks: [
              {
                type: "plan",
                event: "updated",
                summary: "Planner updated the repair path.",
                run_id: "plan-history-1",
                plan: {
                  goal: "Repair the answer",
                  steps: [
                    { step_id: "recheck", intent: "Re-check citations" },
                    { step_id: "repair", intent: "Repair answer" },
                  ],
                },
              },
            ],
          },
          {
            role: "assistant",
            content:
              'Now let me verify this answer with the verification agent: {"verdict":"repair_required","summary":"Add one citation.","issues":["Missing citation."]}',
            request_id: "request-helper-history-1",
          },
          {
            role: "assistant",
            content: "Updated final answer.",
            request_id: "request-helper-history-1",
            blocks: [
              {
                type: "verification",
                summary:
                  "Verifier verdict: repair_required. The draft is directionally correct, but it needs one citation.",
                verdict: "repair_required",
                run_id: "verify-history-1",
                verification: {
                  verdict: "repair_required",
                  summary: "Add one citation.",
                  issues: ["Missing citation."],
                },
              },
              {
                type: "text",
                text: "Updated final answer.",
              },
            ],
          },
        ])
      ),
    ]);

    render(React.createElement(AppShell));

    expect(await screen.findByText("Planning")).toBeTruthy();
    expect(screen.getByText("Updated the 2-step plan.")).toBeTruthy();
    expect(screen.getByText("1. Re-check citations.")).toBeTruthy();
    expect(screen.getByText("2. Repair answer.")).toBeTruthy();
    expect(screen.getByText("Verification")).toBeTruthy();
    expect(screen.getByText("Needs revision before delivery.")).toBeTruthy();
    expect(screen.getByText("Missing citation.")).toBeTruthy();
    expect(screen.getByText("Updated final answer.")).toBeTruthy();
    expect(screen.queryByText(/update the plan/i)).toBeNull();
    expect(screen.queryByText(/verification agent/i)).toBeNull();
    expect(screen.queryByText(/"goal":"Repair the answer"/i)).toBeNull();
    expect(screen.queryByText(/"verdict":"repair_required"/i)).toBeNull();
    expect(screen.queryByText("Add one citation.")).toBeNull();
  });

  it("preserves ordinary multi-segment assistant history text after reload", async () => {
    const session = makeSession({
      id: "session-plain-history",
      title: "Plain history",
      updated_at: Date.parse("2026-04-03T19:15:00Z"),
      message_count: 3,
    });

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions: [session] }),
      route("GET", `/api/sessions/${session.id}/history`, () =>
        jsonResponse([
          {
            role: "user",
            content: "Compare the two options.",
            request_id: "request-plain-history-1",
          },
          {
            role: "assistant",
            content: "I'll help you compare the two options.",
            request_id: "request-plain-history-1",
          },
          {
            role: "assistant",
            content: "Option A is faster.",
            request_id: "request-plain-history-1",
          },
        ])
      ),
    ]);

    render(React.createElement(AppShell));

    expect(
      await screen.findByText("I'll help you compare the two options.")
    ).toBeTruthy();
    expect(screen.getByText("Option A is faster.")).toBeTruthy();
  });

  it("lets the submit button stop an in-flight streamed response and keep the partial answer", async () => {
    const createdSession = makeSession({
      id: "session-interrupt",
      title: "New Chat",
      updated_at: Date.parse("2026-04-03T19:00:00Z"),
      message_count: 0,
    });
    const generatedTitle = "Interrupted run";
    let sessions: Array<ReturnType<typeof makeSession>> = [];
    let sawAbort = false;

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions: () => sessions }),
      route("POST", "/api/sessions", () => {
        sessions = [createdSession];
        return jsonResponse(createdSession);
      }),
      route("POST", `/api/sessions/${createdSession.id}/generate-title`, () => {
        sessions = [{ ...createdSession, title: generatedTitle, message_count: 2 }];
        return jsonResponse({
          session_id: createdSession.id,
          title: generatedTitle,
        });
      }),
      route("POST", "/api/chat", async (request) => {
        const body = (await request.json()) as Record<string, unknown>;
        expect(body).toMatchObject({
          message: "Interrupt this response.",
          session_id: createdSession.id,
        });

        const encoder = new TextEncoder();
        const streamBody = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                `data: ${JSON.stringify({
                  type: "token",
                  content: "Draft answer in progress.",
                  request_id: "request-interrupt-1",
                })}\n\n`
              )
            );

            request.signal.addEventListener(
              "abort",
              () => {
                sawAbort = true;
                controller.error(
                  new DOMException("The operation was aborted.", "AbortError")
                );
              },
              { once: true }
            );
          },
        });

        return new Response(streamBody, {
          headers: {
            "Content-Type": "text/event-stream",
          },
          status: 200,
        });
      }),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    const composer = await screen.findByPlaceholderText(/ask any biology related questions/i);
    await user.type(composer, "Interrupt this response.");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect(
      (
        await screen.findAllByText(hasTextContent("Draft answer in progress."))
      ).length
    ).toBeGreaterThan(0);

    const stopButton = screen.getByRole("button", { name: /stop response/i });
    expect(stopButton.hasAttribute("disabled")).toBe(false);
    await user.click(stopButton);

    expect(await screen.findByRole("button", { name: /send message/i })).toBeTruthy();
    expect(sawAbort).toBe(true);
    expect(screen.queryByText(/⚠️ Error:/)).toBeNull();
    expect(
      screen.getAllByText(hasTextContent("Draft answer in progress.")).length
    ).toBeGreaterThan(0);
    expect((await screen.findAllByText(generatedTitle)).length).toBeGreaterThan(0);
  });

  it("renders the right-rail usage panel with tracked totals", async () => {
    const session = makeSession({
      id: "session-usage",
      title: "Usage review",
      updated_at: Date.parse("2026-04-03T18:00:00Z"),
      message_count: 2,
    });

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions: [session] }),
      route("GET", `/api/sessions/${session.id}/history`, () =>
        jsonResponse([
          { role: "user", content: "How many tokens have we used?" },
          {
            role: "assistant",
            content: "Tracked usage is available in the inspector.",
          },
        ])
      ),
      route("GET", `/api/tokens/session/${session.id}`, () =>
        jsonResponse(
          makeTokenStats({
            session_id: session.id,
            tracked_total_tokens: 24_847,
            total_tokens: 20_690,
            input_tokens: 12_234,
            output_tokens: 8_456,
            tool_tokens: 4_157,
            context_window_tokens: 128_000,
            context_window_remaining_tokens: 107_310,
            model_name: "gpt-5.4",
          })
        )
      ),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    await user.click(screen.getByRole("button", { name: "Inspector Usage" }));

    expect(await screen.findByText("24,847")).toBeTruthy();
    expect(screen.getByText("12,234")).toBeTruthy();
    expect(screen.getByText("8,456")).toBeTruthy();
    expect(screen.getByText("4,157")).toBeTruthy();
    expect(screen.getByText("20.7K / 128K")).toBeTruthy();
  });
});
