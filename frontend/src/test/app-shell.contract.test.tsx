import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import AppShell from "@/components/layout/AppShell";
import {
  makeAccessProbe,
  makeGenericToolResultEnvelope,
  makeSession,
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
  sessions?: Array<ReturnType<typeof makeSession>>;
}) {
  const sessions = options?.sessions ?? [];
  return [
    route("GET", "/", () => jsonResponse({ service: "miniOpenClaw", status: "ok" })),
    buildAccessRoute({
      inspection: "granted",
      execution: "granted",
      admin: "granted",
    }),
    route("GET", "/api/sessions", () => jsonResponse(sessions)),
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
    expect(screen.queryByText("Quick Start")).toBeNull();
    expect(screen.queryByText("Recent Files")).toBeNull();
    expect(screen.queryByText(/chat-only shell/i)).toBeNull();
  });

  it("auto-creates a session, keeps multi-segment assistant turns, and exposes streamed process artifacts in the inspector", async () => {
    const createdSession = makeSession({
      id: "session-chat-only",
      title: "Chat-only checklist pass",
      updated_at: Date.parse("2026-04-02T18:00:00Z"),
      message_count: 2,
    });
    let sessions: Array<ReturnType<typeof makeSession>> = [];

    activeFetchMock = installMockFetch([
      ...buildBaseRoutes({ sessions }),
      route("POST", "/api/sessions", () => {
        sessions = [createdSession];
        return jsonResponse(createdSession);
      }),
      route(
        "POST",
        "/api/chat",
        async (request) => {
          const body = (await request.json()) as Record<string, unknown>;
          expect(body).toMatchObject({
            message: "Check this request for readiness.",
            session_id: createdSession.id,
            stream: true,
            attached_identifiers: [],
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
                summary: "Verifier verdict: pass. Looks good.",
                verdict: "pass",
                verification: { verdict: "pass", summary: "Looks good." },
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
      (
        await screen.findAllByText(hasTextContent("BioAPEX reviewed the request."), {
          selector: "p",
        })
      ).length
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(hasTextContent("BioAPEX prepared the final recommendation."), {
        selector: "p",
      })
    ).toBeTruthy();
    expect((await screen.findAllByText("Planning")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Verification result")).length).toBeGreaterThan(0);
    expect(screen.getByText("Look at memory")).toBeTruthy();
    expect(screen.getByText("Run readiness check")).toBeTruthy();
    expect(screen.queryByText("Planner produced 2 steps.")).toBeNull();
    expect(screen.queryByText("Planning 2 steps to check readiness.")).toBeNull();
    expect(screen.getByText("Looks good.")).toBeTruthy();
    expect((await screen.findAllByText("readiness-checklist.md")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Turn compliance")).toBeNull();
  });
});
