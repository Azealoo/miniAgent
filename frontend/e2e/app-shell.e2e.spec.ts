import { expect, test } from "@playwright/test";
import {
  makeAccessProbe,
  makeGenericToolResultEnvelope,
  makeSession,
  makeTokenStats,
} from "../src/test/fixtures";
import {
  fulfillJson,
  fulfillSse,
  installApiMock,
  route,
} from "./support/mock-api";

type AccessState = "granted" | "token_required" | "forbidden" | "server_misconfigured";

function buildAccessRoute(config: {
  admin: AccessState;
  execution: AccessState;
  inspection: AccessState;
}) {
  return route("GET", "/api/access/probe", async (route, url) => {
    const scope = url.searchParams.get("scope") as keyof typeof config;
    const state = config[scope];

    if (state === "granted") {
      await fulfillJson(route, makeAccessProbe(scope));
      return;
    }
    if (state === "token_required") {
      await fulfillJson(route, { detail: "Bearer token required." }, { status: 401 });
      return;
    }
    if (state === "forbidden") {
      await fulfillJson(
        route,
        { detail: "This route requires local access or a configured bearer token." },
        { status: 403 }
      );
      return;
    }

    await fulfillJson(
      route,
      { detail: "Configured bearer token environment variable BIOAPEX_TOKEN is empty." },
      { status: 503 }
    );
  });
}

test("renders the chat-only shell and streams a response", async ({ page }) => {
  const createdSession = makeSession({
    id: "session-chat-only",
    title: "Chat-only checklist pass",
    updated_at: Date.parse("2026-04-02T18:00:00Z"),
    message_count: 2,
  });
  let sessions: Array<ReturnType<typeof makeSession>> = [];

  await page.route("http://127.0.0.1:8002/", async (route) => {
    await fulfillJson(route, { service: "miniOpenClaw", status: "ok" });
  });

  await installApiMock(page, [
    buildAccessRoute({
      inspection: "granted",
      execution: "granted",
      admin: "granted",
    }),
    route("GET", "/api/sessions", (route) => fulfillJson(route, sessions)),
    route("GET", `/api/tokens/session/${createdSession.id}`, (route) =>
      fulfillJson(
        route,
        makeTokenStats({
          model_name: "gpt-5.4",
          session_id: createdSession.id,
        })
      )
    ),
    route("POST", "/api/sessions", (route) => {
      sessions = [createdSession];
      return fulfillJson(route, createdSession);
    }),
    route("POST", "/api/chat", async (route) => {
      const body = JSON.parse(route.request().postData() ?? "{}") as {
        message: string;
      };
      expect(body).toMatchObject({
        attached_identifiers: [],
        message: "Check this request for readiness.",
        session_id: createdSession.id,
        stream: true,
      });

      await fulfillSse(route, [
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
        { type: "token", content: "BioAPEX reviewed the request." },
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
          type: "done",
          content: "BioAPEX reviewed the request.",
          request_id: "request-chat-only-1",
        },
      ]);
    }),
  ]);

  await page.goto("/");

  await expect(page.getByText("Chat Engine")).toBeVisible();
  await expect(page.getByRole("button", { name: "New Chat" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Studies" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ops" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Artifacts" })).toHaveCount(0);

  await page.getByPlaceholder("Ask any biology related questions").fill(
    "Check this request for readiness."
  );
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("BioAPEX reviewed the request.")).toBeVisible();
  await expect(
    page.getByRole("button", { name: /readiness-checklist\.md/i })
  ).toBeVisible();
  await expect(page.getByRole("banner").getByText("Chat-only checklist pass")).toBeVisible();
});
