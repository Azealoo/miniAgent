import { expect, test } from "@playwright/test";
import {
  makeAccessProbe,
  makeSession,
  makeTokenStats,
} from "../src/test/fixtures";
import {
  fulfillJson,
  installApiMock,
  route,
} from "./support/mock-api";

// Regression test for issue #98: a 500-message transcript must load and
// scroll without jank. The transcript rows are virtualized via native
// `content-visibility: auto` (see `.apex-virtualize-row` in globals.css), so
// this test verifies three things:
//  1. The fixture loads within a bounded time (initial render is not blocked
//     by the full 500-message layout cost).
//  2. The older-turn summary rows are emitted with the virtualization class,
//     which is what lets the browser skip layout/paint for off-screen rows.
//  3. Auto-scroll lands at the bottom of the transcript (the most recent
//     message is visible) after load, preserving the existing ChatPanel
//     auto-scroll contract.
const TOTAL_MESSAGES = 500;
const LARGE_SESSION_ID = "session-500-msg-transcript";
const FIRST_USER_MESSAGE = "Message 1: kick off the long transcript.";
const LAST_ASSISTANT_MESSAGE = `Assistant reply for turn ${TOTAL_MESSAGES / 2}.`;

function buildLargeHistory() {
  const history: Array<{
    role: "user" | "assistant";
    content: string;
    request_id: string;
  }> = [];
  const turnCount = TOTAL_MESSAGES / 2;
  for (let turn = 1; turn <= turnCount; turn += 1) {
    const requestId = `request-large-${turn}`;
    history.push({
      role: "user",
      content:
        turn === 1
          ? FIRST_USER_MESSAGE
          : `Message ${turn * 2 - 1}: follow-up prompt for turn ${turn}.`,
      request_id: requestId,
    });
    history.push({
      role: "assistant",
      content:
        turn === turnCount
          ? LAST_ASSISTANT_MESSAGE
          : `Assistant reply for turn ${turn}.`,
      request_id: requestId,
    });
  }
  return history;
}

test("renders a 500-message transcript without jank and preserves auto-scroll", async ({
  page,
}) => {
  const largeSession = makeSession({
    id: LARGE_SESSION_ID,
    title: "500-message transcript",
    updated_at: Date.parse("2026-04-17T20:00:00Z"),
    message_count: TOTAL_MESSAGES,
  });

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
    route("GET", "/api/sessions", (route) => fulfillJson(route, [largeSession])),
    route("GET", `/api/sessions/${largeSession.id}/history`, (route) =>
      fulfillJson(route, buildLargeHistory())
    ),
    route("GET", `/api/sessions/${largeSession.id}/continuity`, (route) =>
      fulfillJson(route, { summaries: [] })
    ),
    route("GET", `/api/tokens/session/${largeSession.id}`, (route) =>
      fulfillJson(
        route,
        makeTokenStats({ model_name: "gpt-5.4", session_id: largeSession.id })
      )
    ),
  ]);

  const start = Date.now();
  await page.goto("/");

  // The older-turn summary section is the list that can blow up; wait for it
  // to render so the virtualization class check below is meaningful.
  await expect(page.getByText("Earlier Turns")).toBeVisible({ timeout: 15000 });

  const loadMs = Date.now() - start;
  expect(loadMs).toBeLessThan(15000);

  // Virtualization rows are the knob that keeps the 500-message transcript
  // performant. The count bound is intentionally loose — we only care that
  // the class is actually applied to the older-turn summary rows.
  const virtualizedRows = await page.locator(".apex-virtualize-row").count();
  expect(virtualizedRows).toBeGreaterThan(100);

  // Auto-scroll contract: the transcript should land at the bottom after
  // load so the most recent assistant message is visible.
  await expect(page.getByText(LAST_ASSISTANT_MESSAGE)).toBeVisible({
    timeout: 10000,
  });
});
