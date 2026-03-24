import { expect, test } from "@playwright/test";
import {
  makeAccessProbe,
  makeComplianceReport,
  makeFilesWorkspaceItem,
  makeHistoryMessage,
  makeSession,
  makeSkillRegistryEntry,
  makeTokenStats,
  makeToolResultEnvelope,
  makeWorkflowArtifactEvent,
  makeWorkflowDoneEvent,
  makeWorkflowStartEvent,
  makeWorkflowStepEndEvent,
  makeWorkflowStepStartEvent,
} from "../src/test/fixtures";
import {
  fulfillJson,
  fulfillSse,
  fulfillText,
  installApiMock,
  route,
  type BrowserMockRoute,
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

function buildArtifactRegistryRoute() {
  return route("GET", "/api/artifacts/registry", (route) =>
    fulfillJson(route, {
      artifact_root: "artifacts",
      generated_at: "2026-03-24T19:05:00Z",
      invalid_count: 0,
      matched_count: 0,
      records: [],
      registry_path: "artifacts/registry.json",
      total_count: 0,
      valid_count: 0,
    })
  );
}

function buildSessionTokensRoute(): BrowserMockRoute {
  return {
    match: (method, url) =>
      method === "GET" && url.pathname.startsWith("/api/tokens/session/"),
    handle: (route, url) =>
      fulfillJson(
        route,
        makeTokenStats({
          model_name: "gpt-5.4",
          session_id: url.pathname.split("/").at(-1) ?? "session-alpha",
        })
      ),
  };
}

test("creates a session in the browser, streams chat, and previews generated files", async ({
  page,
}) => {
  const createdSession = makeSession({
    id: "session-new",
    title: "RNA-seq compliance run",
    updated_at: Date.parse("2026-03-24T19:00:00Z"),
    message_count: 2,
  });
  const fileItem = makeFilesWorkspaceItem({
    path: "artifacts/reports/qc-summary.md",
    name: "qc-summary.md",
    run_id: "run-rnaseq-1",
  });
  const warningReport = makeComplianceReport();

  await installApiMock(page, [
    buildAccessRoute({
      inspection: "granted",
      execution: "granted",
      admin: "granted",
    }),
    buildArtifactRegistryRoute(),
    buildSessionTokensRoute(),
    route("GET", "/api/sessions", (route) => fulfillJson(route, []), { once: true }),
    route("GET", "/api/config/rag-mode", (route) =>
      fulfillJson(route, { rag_mode: false })
    ),
    route("POST", "/api/sessions", (route) => fulfillJson(route, createdSession), {
      once: true,
    }),
    route(
      "POST",
      "/api/chat",
      async (route) => {
        const body = JSON.parse(route.request().postData() ?? "{}") as {
          message: string;
          selected_workflow: string | null;
        };
        expect(body.message).toBe("Run the BioAPEX RNA-seq workflow.");
        expect(body.selected_workflow).toBe("rnaseq_qc_de");

        await fulfillSse(route, [
          {
            type: "retrieval",
            query: "rnaseq patient cohort",
            results: [
              {
                source: "knowledge/study_protocol.md",
                score: 0.91,
                text: "Protocol guidance for the active RNA-seq cohort.",
              },
            ],
          },
          { type: "token", content: "BioAPEX assembled the response." },
          {
            type: "tool_start",
            tool: "compliance_preflight",
            input: "{}",
            run_id: "tool-1",
            request_id: "request-chat-1",
          },
          makeWorkflowStartEvent({ request_id: "request-chat-1" }),
          makeWorkflowStepStartEvent({ request_id: "request-chat-1" }),
          makeWorkflowStepEndEvent({ request_id: "request-chat-1" }),
          {
            type: "tool_end",
            tool: "compliance_preflight",
            output: "warning",
            run_id: "tool-1",
            request_id: "request-chat-1",
            result: makeToolResultEnvelope(warningReport),
          },
          makeWorkflowArtifactEvent({ request_id: "request-chat-1" }),
          makeWorkflowDoneEvent({ request_id: "request-chat-1" }),
          {
            type: "title",
            session_id: createdSession.id,
            title: createdSession.title,
          },
          {
            type: "done",
            content: "BioAPEX assembled the response.",
            request_id: "request-chat-1",
          },
        ]);
      },
      { once: true }
    ),
    route("GET", "/api/sessions", (route) => fulfillJson(route, [createdSession]), {
      once: true,
    }),
    route("GET", `/api/sessions/${createdSession.id}/files/summary`, (route) =>
      fulfillJson(route, { items: [fileItem] })
    ),
    route("GET", "/api/files/raw", async (route, url) => {
      const path = url.searchParams.get("path");
      if (path === fileItem.path) {
        await fulfillText(
          route,
          "# QC Summary\n\n- PASS\n- 1 warning retained for review\n",
          {
            contentType: "text/markdown; charset=utf-8",
          }
        );
        return;
      }

      throw new Error(`Unexpected raw file request for ${path}`);
    }),
  ]);

  await page.goto("/");

  const textarea = page.getByPlaceholder(
    "Describe the scientific question, workflow step, or evidence task you want BioAPEX to handle."
  );
  await expect(textarea).toBeEnabled();

  await page.getByRole("button", { name: "Choose workflow" }).click();
  await page.getByRole("button", { name: "RNA-seq QC + DE" }).click();
  await textarea.fill("Run the BioAPEX RNA-seq workflow.");
  await textarea.press("Enter");

  await expect(page.getByText("BioAPEX assembled the response.")).toBeVisible();
  await expect(page.getByText("Knowledge Retrieved")).toBeVisible();
  await expect(page.getByText("Warning").first()).toBeVisible();

  await page.getByRole("button", { name: "Open Files workspace" }).click();
  await expect(page.getByRole("heading", { name: "Output Files" })).toBeVisible();
  await expect(page.getByText("qc-summary.md").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "QC Summary" })).toBeVisible();
});

test("keeps admin-only controls disabled in the browser when admin access is unavailable", async ({
  page,
}) => {
  const session = makeSession({
    id: "session-alpha",
    title: "Saved evidence review",
    updated_at: Date.parse("2026-03-24T18:30:00Z"),
    message_count: 2,
  });
  const featureSkill = makeSkillRegistryEntry();
  const browserMock = await installApiMock(page, [
    buildAccessRoute({
      inspection: "granted",
      execution: "granted",
      admin: "token_required",
    }),
    buildArtifactRegistryRoute(),
    buildSessionTokensRoute(),
    route("GET", "/api/sessions", (route) => fulfillJson(route, [session]), {
      once: true,
    }),
    route("GET", `/api/sessions/${session.id}/history`, (route) =>
      fulfillJson(route, [
        { role: "user", content: "Review the latest workflow evidence." },
        makeHistoryMessage({
          content: "Evidence and artifacts are ready.",
        }),
      ])
    ),
    route("GET", "/api/skills/registry", (route) => fulfillJson(route, [featureSkill])),
    route("GET", "/api/files", async (route, url) => {
      if (url.searchParams.get("path") === featureSkill.location) {
        await fulfillJson(route, {
          path: featureSkill.location,
          content:
            "# Feature Workflow\n\nManage the BioAPEX current-feature workflow from scoping through review and completion\n",
        });
        return;
      }

      throw new Error(`Unexpected file read for ${url.searchParams.get("path")}`);
    }),
  ]);

  await page.goto("/");

  await expect(page.getByText("Evidence and artifacts are ready.")).toBeVisible();
  await page.getByRole("button", { name: "Inspector Skills" }).click();
  await expect(page.getByRole("heading", { name: "Registry" })).toBeVisible();
  await page.getByRole("button", { name: /feature/i }).click();

  await expect(
    page.getByText("Admin access requires a bearer token for this client.")
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Disable Skill" })).toBeDisabled();

  expect(
    browserMock.captured.some(
      (request) =>
        request.method !== "GET" &&
        request.url.includes(
          `/api/skills/registry/${encodeURIComponent(featureSkill.name)}`
        )
    )
  ).toBe(false);
});

test("blocks execution-protected chat and session mutations in the browser", async ({
  page,
}) => {
  const browserMock = await installApiMock(page, [
    buildAccessRoute({
      inspection: "granted",
      execution: "token_required",
      admin: "token_required",
    }),
    buildArtifactRegistryRoute(),
    buildSessionTokensRoute(),
    route("GET", "/api/sessions", (route) => fulfillJson(route, []), {
      once: true,
    }),
  ]);

  await page.goto("/");

  await expect(page.getByText("Chat is unavailable from this client")).toBeVisible();
  await expect(
    page.getByPlaceholder("Execution access requires a bearer token for this client.")
  ).toBeDisabled();
  await expect(page.getByRole("button", { name: "New" })).toBeDisabled();

  expect(
    browserMock.captured.some(
      (request) =>
        request.method === "POST" &&
        (request.url.includes("/api/sessions") || request.url.includes("/api/chat"))
    )
  ).toBe(false);
});
