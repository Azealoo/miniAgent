import { expect, test } from "@playwright/test";
import { makeAccessProbe, makeSession, makeTokenStats } from "../src/test/fixtures";
import { fulfillJson, fulfillSse, installApiMock, route } from "./support/mock-api";

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

test("streams workflow_step events and renders a live step list", async ({ page }) => {
  const createdSession = makeSession({
    id: "session-workflow-steps",
    title: "RNA-seq QC run",
    updated_at: Date.parse("2026-04-18T12:00:00Z"),
    message_count: 0,
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
        makeTokenStats({ model_name: "gpt-5.4", session_id: createdSession.id })
      )
    ),
    route("POST", "/api/sessions", (route) => {
      sessions = [createdSession];
      return fulfillJson(route, createdSession);
    }),
    route("POST", `/api/sessions/${createdSession.id}/generate-title`, (route) =>
      fulfillJson(route, {
        session_id: createdSession.id,
        title: createdSession.title,
      })
    ),
    route("POST", "/api/chat", async (route) => {
      const body = JSON.parse(route.request().postData() ?? "{}") as { message: string };
      expect(body).toMatchObject({
        message: "Run the rna-seq QC workflow.",
        session_id: createdSession.id,
      });

      await fulfillSse(route, [
        {
          type: "workflow_step_started",
          workflow_id: "rna-seq-qc",
          run_id: "wf-run-1",
          step_id: "preflight_check",
          step_index: 1,
          total_steps: 2,
          label: "Validate dataset manifest",
          attempt: 1,
          request_id: "request-workflow-1",
        },
        {
          type: "workflow_step_ended",
          workflow_id: "rna-seq-qc",
          run_id: "wf-run-1",
          step_id: "preflight_check",
          step_index: 1,
          total_steps: 2,
          duration_ms: 42,
          request_id: "request-workflow-1",
        },
        {
          type: "workflow_step_started",
          workflow_id: "rna-seq-qc",
          run_id: "wf-run-1",
          step_id: "summarize_qc",
          step_index: 2,
          total_steps: 2,
          label: "Summarize QC metrics",
          attempt: 1,
          request_id: "request-workflow-1",
        },
        {
          type: "workflow_step_failed",
          workflow_id: "rna-seq-qc",
          run_id: "wf-run-1",
          step_id: "summarize_qc",
          step_index: 2,
          total_steps: 2,
          duration_ms: 128,
          error: "KeyError: min_genes",
          failure_policy: "fail_workflow",
          attempt: 1,
          request_id: "request-workflow-1",
        },
        {
          type: "done",
          content: "Workflow run failed at summarize_qc.",
          request_id: "request-workflow-1",
        },
      ]);
    }),
  ]);

  await page.goto("/");

  await page
    .getByPlaceholder("Ask any biology related questions")
    .fill("Run the rna-seq QC workflow.");
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByText("Workflow run failed at summarize_qc.")).toBeVisible();

  // Each workflow_step event lands as a live line in the "Workflow" section of
  // the activity feed; the labels from started events + status from ended/failed
  // events are rendered together so reviewers see every step without scrolling.
  await expect(
    page.getByText("Step 1/2: Validate dataset manifest — done in 42 ms")
  ).toBeVisible();
  await expect(
    page.getByText(
      "Step 2/2: Summarize QC metrics — failed: KeyError: min_genes"
    )
  ).toBeVisible();
});
