import { expect, test } from "@playwright/test";
import { makeAccessProbe } from "../src/test/fixtures";
import { fulfillJson, installApiMock, route } from "./support/mock-api";

// Verifies issue #47 acceptance: a fresh session lands on the biology-agent
// chat (composer + biology-first quick actions) rather than a workflow-first
// view, and no user-facing "Flows" copy remains.
test("default navigation lands on the biology-agent chat", async ({ page }) => {
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
    route("GET", "/api/sessions", (route) => fulfillJson(route, [])),
  ]);

  await page.goto("/");

  // Navbar reflects the chat-first reframe.
  await expect(page.getByText("Chat Engine")).toBeVisible();
  await expect(page.getByRole("button", { name: "New Chat" })).toBeVisible();

  // None of the old workflow-first nav pills remain.
  await expect(page.getByRole("button", { name: "Studies" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Ops" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Artifacts" })).toHaveCount(0);

  // Composer is the primary affordance, with the biology-first placeholder.
  const composer = page.getByPlaceholder("Ask any biology related questions");
  await expect(composer).toBeVisible();

  // Empty-state copy frames the workspace as a conversation, not a workflow.
  await expect(page.getByText("Conversation Workspace")).toBeVisible();
  await expect(
    page.getByText("Select a session or start a new one")
  ).toBeVisible();

  // Typing "/" surfaces the biology-agent slash commands.
  await composer.fill("/");
  await expect(page.getByText("Matching Commands")).toBeVisible();
  for (const command of ["/ask", "/rnaseq", "/evidence", "/readiness"]) {
    await expect(page.getByText(command, { exact: true })).toBeVisible();
  }

  // No user-facing "Flows" string survives the reframe.
  await expect(page.getByText(/\bflows?\b/i)).toHaveCount(0);
});
