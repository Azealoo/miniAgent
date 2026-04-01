import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import AppShell from "@/components/layout/AppShell";
import {
  makeAccessProbe,
  makeArtifactRegistryRecord,
  makeComplianceReport,
  makeFilesWorkspaceItem,
  makeHistoryMessage,
  makeSession,
  makeStudySummary,
  makeSkillRegistryEntry,
  makeTokenStats,
  makeToolResultEnvelope,
  makeWorkflowArtifactEvent,
  makeWorkflowDoneEvent,
  makeWorkflowStartEvent,
  makeWorkflowStepEndEvent,
  makeWorkflowStepStartEvent,
} from "@/test/fixtures";
import {
  installMockFetch,
  jsonResponse,
  route,
  sseResponse,
  textResponse,
} from "@/test/mock-fetch";

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

describe("AppShell frontend contract coverage", () => {
  it("creates a session, assembles a streamed response, renders workflow/compliance state, and previews generated files", async () => {
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
    const qaArtifact = makeArtifactRegistryRecord({
      path: fileItem.path,
      run_id: "run-rnaseq-1",
      workflow: "rnaseq_qc_de",
      source_workflow: "rnaseq_qc_de",
      dataset_id: "dataset-alpha",
    });
    const studies = [
      makeStudySummary({
        study_id: "dataset-alpha",
        title: "Alpha Cohort",
        latest_activity_at: "2026-03-24T19:20:00Z",
        run_count: 2,
      }),
      makeStudySummary({
        study_id: "dataset-beta",
        title: "Beta Cohort",
        latest_activity_at: "2026-03-24T20:20:00Z",
        run_count: 5,
        export_available: false,
        active_run_state: "active",
        compliance_state: "warning_issued",
      }),
      makeStudySummary({
        study_id: "dataset-gamma",
        title: "Gamma Cohort",
        latest_activity_at: "2026-03-23T20:20:00Z",
        run_count: 1,
        evidence_state: "mixed",
        qa_state: "warning",
      }),
    ];
    const fetchMock = installMockFetch([
      buildAccessRoute({
        inspection: "granted",
        execution: "granted",
        admin: "granted",
      }),
      route("GET", "/api/sessions", () => jsonResponse([]), { once: true }),
      route("GET", "/api/config/rag-mode", () => jsonResponse({ rag_mode: false })),
      route("POST", "/api/sessions", () => jsonResponse(createdSession)),
      route(
        "POST",
        "/api/chat",
        async (request) => {
          const body = (await request.json()) as {
            message: string;
            selected_workflow: string | null;
          };
          expect(body.message).toBe("Run the BioAPEX RNA-seq workflow.");
          expect(body.selected_workflow).toBe("rnaseq_qc_de");

          return sseResponse(
            [
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
            ],
            { chunkSize: 31 }
          );
        },
        { once: true }
      ),
      route("GET", "/api/sessions", () => jsonResponse([createdSession]), { once: true }),
      route(
        "GET",
        `/api/sessions/${createdSession.id}/files/summary`,
        () => jsonResponse({ items: [fileItem] })
      ),
      route("GET", "/api/studies", () => jsonResponse({ items: studies })),
      route("GET", "/api/artifacts/registry", () =>
        jsonResponse({
          artifact_root: "artifacts",
          generated_at: "2026-03-24T18:40:00Z",
          invalid_count: 0,
          matched_count: 1,
          records: [qaArtifact],
          registry_path: "artifacts/registry.json",
          total_count: 1,
          valid_count: 1,
        })
      ),
      route("GET", "/api/files/raw", (_request, url) => {
        const path = url.searchParams.get("path");
        if (path === fileItem.path) {
          return textResponse("# QC Summary\n\n- PASS\n- 1 warning retained for review\n", {
            headers: {
              "Content-Type": "text/markdown; charset=utf-8",
            },
          });
        }

        throw new Error(`unexpected raw file request for ${path}`);
      }),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    const textarea = await screen.findByPlaceholderText(
      "Describe the scientific question, workflow step, or evidence task you want BioAPEX to handle."
    );
    await waitFor(() => {
      expect(textarea.hasAttribute("disabled")).toBe(false);
    });

    await user.click(screen.getByRole("button", { name: "Choose workflow" }));
    await user.click(screen.getByRole("button", { name: "RNA-seq QC + DE" }));
    await user.type(textarea, "Run the BioAPEX RNA-seq workflow.");
    await user.keyboard("{Enter}");

    expect(await screen.findByText("BioAPEX assembled the response.")).toBeTruthy();
    expect(await screen.findByText("Knowledge Retrieved")).toBeTruthy();
    expect((await screen.findAllByText("RNA-seq QC + DE")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Warning")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Open Files workspace" }));

    expect((await screen.findAllByText("Output Files")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("qc-summary.md")).length).toBeGreaterThan(0);
    expect(await screen.findByText("QC Summary")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Open Artifacts workspace" }));
    expect(
      await screen.findByRole("heading", { level: 2, name: "Artifact Registry" })
    ).toBeTruthy();
    expect((await screen.findAllByText("qc-summary.md")).length).toBeGreaterThan(0);
    await user.click(await screen.findByRole("button", { name: "Open Related Study" }));

    expect(await screen.findByRole("heading", { name: "Alpha Cohort" })).toBeTruthy();

    const searchInput = screen.getByPlaceholderText(
      "Search by study, assay, organism, privacy, or state"
    );
    await user.type(searchInput, "gamma");

    expect(screen.getAllByRole("button", { name: /Select study/i })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Select study Gamma Cohort" })).toBeTruthy();

    await user.clear(searchInput);
    await user.selectOptions(screen.getByRole("combobox", { name: "Sort studies" }), "title");

    const studyButtons = screen.getAllByRole("button", { name: /Select study/i });
    expect(studyButtons[0].textContent).toContain("Alpha Cohort");
    expect(studyButtons[1].textContent).toContain("Beta Cohort");

    fetchMock.restore();
  });

  it("loads sources, memory, skills, usage, and artifact registry flows against contract-shaped payloads", async () => {
    const session = makeSession({
      id: "session-alpha",
      title: "Saved evidence review",
      updated_at: Date.parse("2026-03-24T18:30:00Z"),
      message_count: 2,
    });
    const blockedReport = makeComplianceReport({
      block_status: "blocked",
      final_disposition: "block",
      human_approval_required: true,
      preflight_disposition: "block",
      runtime_state: "blocked",
      triggered_rules: [
        {
          rule_id: "blocked-human-subjects",
          category: "human_subjects",
          trigger_text: "patient cohort",
          severity: "high",
          recommended_action: "block",
        },
      ],
    });
    const featureSkill = makeSkillRegistryEntry();
    const cleanupSkill = makeSkillRegistryEntry({
      category: "housekeeping",
      description: "Clean up project housekeeping tasks",
      enabled: false,
      location: "/gpfs/projects/hrbomics/miniAgent/.codex/skills/cleanup/SKILL.md",
      name: "cleanup",
      source_path: "/gpfs/projects/hrbomics/miniAgent/.codex/skills/cleanup/SKILL.md",
      tags: ["cleanup"],
    });
    const qaArtifact = makeArtifactRegistryRecord();
    const complianceArtifact = makeArtifactRegistryRecord({
      artifact_id: "artifact-2",
      artifact_type: "compliance_report",
      path: "artifacts/compliance/compliance-report.json",
      run_id: "run-compliance-1",
      workflow: "protocol_executor",
      source_workflow: "protocol_executor",
    });
    const studies = [
      makeStudySummary({
        study_id: "dataset-alpha",
        title: "Alpha Cohort",
        latest_activity_at: "2026-03-24T19:20:00Z",
        run_count: 2,
      }),
      makeStudySummary({
        study_id: "dataset-beta",
        title: "Beta Cohort",
        latest_activity_at: "2026-03-24T20:20:00Z",
        run_count: 5,
        export_available: false,
        active_run_state: "active",
        compliance_state: "warning_issued",
      }),
      makeStudySummary({
        study_id: "dataset-gamma",
        title: "Gamma Cohort",
        latest_activity_at: "2026-03-23T20:20:00Z",
        run_count: 1,
        evidence_state: "mixed",
        qa_state: "warning",
      }),
    ];
    const fetchMock = installMockFetch([
      buildAccessRoute({
        inspection: "granted",
        execution: "granted",
        admin: "token_required",
      }),
      route("GET", "/api/sessions", () => jsonResponse([session]), { once: true }),
      route(
        "GET",
        `/api/sessions/${session.id}/history`,
        () =>
          jsonResponse([
            { role: "user", content: "Review the latest workflow evidence." },
            makeHistoryMessage({
              content: "Evidence and artifacts are ready.",
              request_id: "request-history-1",
              retrievals: [
                {
                  source: "knowledge/study_protocol.md",
                  score: 0.91,
                  text: "Protocol guidance for the active RNA-seq cohort.",
                },
              ],
              tool_calls: [
                {
                  tool: "compliance_preflight",
                  input: "{}",
                  output: "blocked",
                  run_id: "tool-blocked-1",
                  result: makeToolResultEnvelope(blockedReport),
                },
              ],
              workflow_events: [
                makeWorkflowStartEvent({ request_id: "request-history-1" }),
                makeWorkflowArtifactEvent({ request_id: "request-history-1" }),
                makeWorkflowDoneEvent({ request_id: "request-history-1" }),
              ],
            }),
          ]),
        { once: true }
      ),
      route(
        "GET",
        `/api/tokens/session/${session.id}`,
        () =>
          jsonResponse(
            makeTokenStats({
              model_name: "gpt-5.4",
              session_id: session.id,
            })
          )
      ),
      route("GET", "/api/studies", () => jsonResponse({ items: studies })),
      route("GET", "/api/files", (_request, url) => {
        const path = url.searchParams.get("path");

        if (path === "memory/MEMORY.md") {
          return jsonResponse({
            path,
            content: "# Long-term Memory\n\n## project\n- dataset: BRCA1 cohort\n",
          });
        }

        if (path === featureSkill.location) {
          return jsonResponse({
            path,
            content:
              "# Feature Workflow\n\nManage the BioAPEX current-feature workflow from scoping through review and completion\n",
          });
        }

        throw new Error(`unexpected file read for ${path}`);
      }),
      route(
        "GET",
        "/api/skills/registry",
        () => jsonResponse([featureSkill, cleanupSkill])
      ),
      route("GET", "/api/artifacts/registry", (_request, url) => {
        const workflow = url.searchParams.get("workflow");
        const allRecords = [qaArtifact, complianceArtifact];
        const filtered =
          workflow && workflow.length > 0
            ? allRecords.filter((record) => record.workflow === workflow)
            : allRecords;

        return jsonResponse({
          artifact_root: "artifacts",
          generated_at: "2026-03-24T18:40:00Z",
          invalid_count: 0,
          matched_count: filtered.length,
          records: filtered,
          registry_path: "artifacts/registry.json",
          total_count: allRecords.length,
          valid_count: filtered.length,
        });
      }),
      route("GET", "/api/files/raw", (_request, url) => {
        const path = url.searchParams.get("path");
        if (path === qaArtifact.path) {
          return textResponse("# QC Summary\n\nRetained in the registry browser.\n", {
            headers: {
              "Content-Type": "text/markdown; charset=utf-8",
            },
          });
        }
        if (path === complianceArtifact.path) {
          return textResponse(
            JSON.stringify({ blocked: true, reason: "patient cohort" }, null, 2),
            {
              headers: {
                "Content-Type": "application/json",
              },
            }
          );
        }

        throw new Error(`unexpected raw file request for ${path}`);
      }),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    expect(await screen.findByText("Evidence and artifacts are ready.")).toBeTruthy();
    expect(await screen.findByText("Token needed")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Inspector Sources" }));
    expect(await screen.findByText("Citations")).toBeTruthy();
    expect(await screen.findByText("Provenance verified")).toBeTruthy();
    expect((await screen.findAllByText("Blocked")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Inspector Memory" }));
    expect(await screen.findByText("Context Memory")).toBeTruthy();
    expect(await screen.findByText("BRCA1 cohort")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Inspector Skills" }));
    expect(await screen.findByText("Registry")).toBeTruthy();
    expect(await screen.findByText("feature")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /feature/i }));
    expect(await screen.findByText("Skill File")).toBeTruthy();
    expect(
      await screen.findByText("Admin access requires a bearer token for this client.")
    ).toBeTruthy();
    const toggleSkillButton = screen.getByRole("button", { name: "Disable Skill" });
    expect(toggleSkillButton.hasAttribute("disabled")).toBe(true);
    await waitFor(() => {
      expect(
        fetchMock.captured.some((request) =>
          request.url.includes(
            `/api/files?path=${encodeURIComponent(featureSkill.location)}`
          )
        )
      ).toBe(true);
    });
    expect(
      fetchMock.captured.some(
        (request) =>
          request.method !== "GET" &&
          request.url.includes(
            `/api/skills/registry/${encodeURIComponent(featureSkill.name)}`
          )
      )
    ).toBe(false);

    await user.click(screen.getByRole("button", { name: "Inspector Usage" }));
    expect(await screen.findByText("gpt-5.4")).toBeTruthy();
    expect((await screen.findAllByText("Model-aligned")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("cl100k_base")).length).toBeGreaterThan(0);
    expect(
      screen.getByText("Counts use the model-aligned cl100k_base tokenizer.")
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Open Artifacts workspace" }));
    expect(await screen.findByText("Artifact Registry")).toBeTruthy();
    expect((await screen.findAllByText("qc-summary.md")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("compliance-report.json")).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Workflow"), {
      target: { value: "rnaseq_qc_de" },
    });

    await waitFor(() => {
      expect(screen.queryByText("compliance-report.json")).toBeNull();
    });
    expect(screen.getAllByText("qc-summary.md").length).toBeGreaterThan(0);

    fetchMock.restore();
  });

  it("labels approximate usage counts honestly when the fallback tokenizer is active", async () => {
    const session = makeSession({
      id: "session-fallback",
      title: "Fallback usage review",
      updated_at: Date.parse("2026-04-01T16:20:00Z"),
      message_count: 2,
    });
    const fetchMock = installMockFetch([
      buildAccessRoute({
        inspection: "granted",
        execution: "granted",
        admin: "granted",
      }),
      route("GET", "/api/sessions", () => jsonResponse([session]), { once: true }),
      route("GET", "/api/config/rag-mode", () => jsonResponse({ rag_mode: false })),
      route(
        "GET",
        `/api/sessions/${session.id}/history`,
        () =>
          jsonResponse([
            { role: "user", content: "Show the offline-safe usage path." },
            makeHistoryMessage({
              content: "Fallback counts are active for this session.",
            }),
          ])
      ),
      route(
        "GET",
        `/api/tokens/session/${session.id}`,
        () =>
          jsonResponse(
            makeTokenStats({
              model_name: "gpt-5.4",
              session_id: session.id,
              tokenizer_backend: "deterministic_fallback",
              tokenizer_accuracy: "approximate",
            })
          )
      ),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    expect(await screen.findByText("Fallback counts are active for this session.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Inspector Usage" }));

    expect((await screen.findAllByText("Approximate")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Local fallback")).length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "Counts use a deterministic local fallback and may differ from model-side totals."
      )
    ).toBeTruthy();

    fetchMock.restore();
  });

  it("surfaces inspection and admin bearer-token requirements without calling protected inspection endpoints", async () => {
    const fetchMock = installMockFetch([
      buildAccessRoute({
        inspection: "token_required",
        execution: "granted",
        admin: "token_required",
      }),
    ]);

    render(React.createElement(AppShell));

    expect(
      await screen.findByText("Inspection access is required to browse saved sessions.")
    ).toBeTruthy();
    expect(await screen.findByText("Token needed")).toBeTruthy();
    expect(fetchMock.captured.some((request) => request.url.includes("/api/sessions"))).toBe(
      false
    );

    fetchMock.restore();
  });

  it("blocks execution-protected chat and session mutations when execution access is unavailable", async () => {
    const fetchMock = installMockFetch([
      buildAccessRoute({
        inspection: "granted",
        execution: "token_required",
        admin: "token_required",
      }),
      route("GET", "/api/sessions", () => jsonResponse([]), { once: true }),
    ]);

    render(React.createElement(AppShell));

    expect(await screen.findByText("Chat is unavailable from this client")).toBeTruthy();

    const textarea = await screen.findByPlaceholderText(
      "Execution access requires a bearer token for this client."
    );
    expect(textarea.hasAttribute("disabled")).toBe(true);

    const newButton = screen.getByRole("button", { name: "New" });
    expect(newButton.hasAttribute("disabled")).toBe(true);
    expect(newButton.getAttribute("title")).toBe(
      "Execution access requires a bearer token for this client."
    );

    expect(
      fetchMock.captured.some(
        (request) =>
          request.method === "POST" &&
          (request.url.includes("/api/sessions") || request.url.includes("/api/chat"))
      )
    ).toBe(false);

    fetchMock.restore();
  });

  it("preserves the last good workspace when switching to a session whose history load fails", async () => {
    const sessionAlpha = makeSession({
      id: "session-alpha",
      title: "Alpha session",
      updated_at: Date.parse("2026-03-24T18:10:00Z"),
    });
    const sessionBeta = makeSession({
      id: "session-beta",
      title: "Beta session",
      updated_at: Date.parse("2026-03-24T18:11:00Z"),
    });
    const fetchMock = installMockFetch([
      buildAccessRoute({
        inspection: "granted",
        execution: "granted",
        admin: "token_required",
      }),
      route("GET", "/api/sessions", () => jsonResponse([sessionAlpha, sessionBeta]), {
        once: true,
      }),
      route(
        "GET",
        `/api/sessions/${sessionAlpha.id}/history`,
        () =>
          jsonResponse([
            { role: "user", content: "Load alpha" },
            makeHistoryMessage({ content: "Session alpha history" }),
          ]),
        { once: true }
      ),
      route(
        "GET",
        `/api/sessions/${sessionBeta.id}/history`,
        () => jsonResponse({ detail: "Saved history unavailable." }, { status: 500 }),
        { once: true }
      ),
    ]);

    const user = userEvent.setup();
    render(React.createElement(AppShell));

    expect(await screen.findByText("Session alpha history")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Beta session/i }));

    expect(await screen.findByText("Saved history could not load")).toBeTruthy();
    expect(screen.getByText("Session alpha history")).toBeTruthy();

    fetchMock.restore();
  });
});
