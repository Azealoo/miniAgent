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

// SSE contract test for issue #60: a canned fixture drives the full runtime
// event sequence and the test asserts both wire-level order/count and UI
// rendering. Uses the mocked-SSE convention already established in
// app-shell.e2e.spec.ts — booting the real FastAPI service from Playwright
// would reintroduce model/tool nondeterminism the fixture has to exclude.
const CANNED_MESSAGE = "Stream every runtime event type for the contract test.";
const REQUEST_ID = "request-chat-stream-contract-1";
const RUN_ID = "tool-contract-1";

const EXPECTED_EVENT_TYPES = [
  "retrieval",
  "token",
  "tool_start",
  "tool_end",
  "plan_created",
  "plan_updated",
  "verification_result",
  "done",
] as const;

function buildCannedSsePayloads() {
  return [
    {
      type: "retrieval",
      query: "sse contract",
      results: [
        {
          source: "knowledge/sse-contract.md",
          score: 0.88,
          text: "SSE contract fixture.",
        },
      ],
      request_id: REQUEST_ID,
    },
    {
      type: "token",
      content: "Streaming every runtime event for the contract.",
      request_id: REQUEST_ID,
    },
    {
      type: "tool_start",
      tool: "read_file",
      input: "knowledge/sse-contract.md",
      run_id: RUN_ID,
      request_id: REQUEST_ID,
    },
    {
      type: "tool_end",
      tool: "read_file",
      output: "Read knowledge/sse-contract.md.",
      run_id: RUN_ID,
      request_id: REQUEST_ID,
      result: makeGenericToolResultEnvelope({
        artifact_refs: [
          {
            artifact_type: "file",
            path: "knowledge/sse-contract.md",
            label: "sse-contract.md",
          },
        ],
        structured_payload: {
          path: "knowledge/sse-contract.md",
          content_preview: "SSE contract fixture.",
        },
        summary: "Read knowledge/sse-contract.md.",
      }),
    },
    {
      type: "plan_created",
      summary: "Planner drafted the initial plan.",
      plan: {
        goal: "Emit the full SSE contract",
        steps: [
          { step_id: "draft", intent: "Draft the contract plan" },
          { step_id: "report", intent: "Report the contract outcome" },
        ],
      },
      request_id: REQUEST_ID,
    },
    {
      type: "plan_updated",
      summary: "Planner refined the plan with a verification step.",
      plan: {
        goal: "Emit the full SSE contract",
        steps: [
          { step_id: "draft", intent: "Draft the contract plan" },
          { step_id: "verify", intent: "Verify the contract plan" },
          { step_id: "report", intent: "Report the contract outcome" },
        ],
      },
      request_id: REQUEST_ID,
    },
    {
      type: "verification_result",
      summary: "Verifier verdict: pass. Contract plan verified.",
      verdict: "pass",
      verification: {
        verdict: "pass",
        summary: "Contract plan verified.",
        checks: [
          {
            name: "sse_contract",
            status: "pass",
            note: "Every expected event arrived in order.",
          },
        ],
      },
      request_id: REQUEST_ID,
    },
    {
      type: "done",
      content: "Streaming every runtime event for the contract.",
      request_id: REQUEST_ID,
    },
  ];
}

function parseSseEventTypes(rawBody: string): string[] {
  const types: string[] = [];
  for (const line of rawBody.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const payload = trimmed.slice("data:".length).trim();
    if (!payload) continue;
    const parsed = JSON.parse(payload) as { type: string };
    types.push(parsed.type);
  }
  return types;
}

test("streams every runtime event in contract order exactly once", async ({
  page,
}) => {
  const chatSession = makeSession({
    id: "session-chat-stream-contract",
    title: "New Chat",
    updated_at: Date.parse("2026-04-17T18:00:00Z"),
    message_count: 0,
  });
  let sessions: Array<ReturnType<typeof makeSession>> = [];
  const generatedTitle = "SSE contract walkthrough";

  await page.route("http://127.0.0.1:8002/", async (route) => {
    await fulfillJson(route, { service: "miniOpenClaw", status: "ok" });
  });

  await installApiMock(page, [
    route("GET", "/api/access/probe", (route, url) => {
      const scope = url.searchParams.get("scope") as
        | "inspection"
        | "execution"
        | "admin";
      return fulfillJson(route, makeAccessProbe(scope));
    }),
    route("GET", "/api/sessions", (route) => fulfillJson(route, sessions)),
    route("GET", `/api/tokens/session/${chatSession.id}`, (route) =>
      fulfillJson(
        route,
        makeTokenStats({ model_name: "gpt-5.4", session_id: chatSession.id })
      )
    ),
    route("POST", "/api/sessions", (route) => {
      sessions = [chatSession];
      return fulfillJson(route, chatSession);
    }),
    route("POST", `/api/sessions/${chatSession.id}/generate-title`, (route) => {
      sessions = [{ ...chatSession, title: generatedTitle, message_count: 2 }];
      return fulfillJson(route, {
        session_id: chatSession.id,
        title: generatedTitle,
      });
    }),
    route("POST", "/api/chat", async (route) => {
      const body = JSON.parse(route.request().postData() ?? "{}") as {
        message: string;
      };
      expect(body).toMatchObject({
        message: CANNED_MESSAGE,
        session_id: chatSession.id,
      });
      await fulfillSse(route, buildCannedSsePayloads());
    }),
  ]);

  // Capture the mocked SSE body so the test can assert wire-level order/count
  // independently of what the reducer chooses to render.
  const chatResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/chat") && response.request().method() === "POST"
  );

  await page.goto("/");

  await expect(page.getByText("Chat Engine")).toBeVisible();

  await page.getByPlaceholder("Ask any biology related questions").fill(
    CANNED_MESSAGE
  );
  await page.getByRole("button", { name: "Send message" }).click();

  const chatResponse = await chatResponsePromise;
  const rawBody = await chatResponse.text();
  const receivedEventTypes = parseSseEventTypes(rawBody);

  expect(receivedEventTypes).toEqual([...EXPECTED_EVENT_TYPES]);

  await expect(
    page.getByText("Streaming every runtime event for the contract.")
  ).toBeVisible();

  await expect(
    page.getByRole("button", { name: /sse-contract\.md/i })
  ).toBeVisible();

  // plan_updated supersedes plan_created live in the same turn, so the UI
  // settles on the 3-step summary rather than the initial 2-step draft.
  await expect(page.getByText("Updated the 3-step plan.")).toBeVisible();
  await expect(page.getByText("2. Verify the contract plan.")).toBeVisible();
  await expect(page.getByText("3. Report the contract outcome.")).toBeVisible();

  await expect(page.getByText("Passed verification.")).toBeVisible();
  await expect(
    page.getByText(
      "Sse contract check passed: Every expected event arrived in order."
    )
  ).toBeVisible();

  await expect(
    page.getByRole("banner").getByText(generatedTitle)
  ).toBeVisible();
});
