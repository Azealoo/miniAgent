"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ChevronDown,
  Download,
  GitBranch,
  KeyRound,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  ACCESS_SCOPES,
  accessStatusBadgeLabel,
  getOverallAccessSummary,
  scopeRequirement,
} from "@/lib/access-control";
import { getHealth } from "@/lib/api";
import {
  getReadinessSummary,
  getWorkflowSummary,
  isWorkflowSelectionPending,
  type ReadinessState,
  type WorkflowSummary,
} from "@/lib/session-status";
import { useApp } from "@/lib/store";
import type { AccessScope, Message, WorkflowStreamEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

function buildExportMarkdown(title: string, messages: Message[]) {
  const lines: string[] = [
    `# ${title}`,
    "",
    `Exported: ${new Date().toISOString()}`,
    "",
  ];

  messages.forEach((message) => {
    lines.push(`## ${message.role === "user" ? "User" : "BioAPEX"}`);
    lines.push(message.content || "(empty response)");

    if (message.retrievals?.length) {
      lines.push("");
      lines.push("Retrieved sources:");
      message.retrievals.forEach((result) => {
        lines.push(`- ${result.source} (score ${result.score.toFixed(3)})`);
      });
    }

    if (message.workflow_events?.length) {
      lines.push("");
      lines.push("Workflow events:");
      message.workflow_events.forEach((event) => {
        lines.push(`- ${formatWorkflowEvent(event)}`);
      });
    }

    if (message.tool_calls?.length) {
      lines.push("");
      lines.push("Tool calls:");
      message.tool_calls.forEach((call) => {
        lines.push(`- ${call.tool}`);
      });
    }

    lines.push("");
  });

  return lines.join("\n").trim() + "\n";
}

function formatWorkflowEvent(event: WorkflowStreamEvent) {
  switch (event.type) {
    case "workflow_start":
      return `${event.workflow_name} started`;
    case "workflow_done":
      return `${event.workflow_id} ${event.lifecycle_status}`;
    case "workflow_blocked":
      return `${event.workflow_id} blocked: ${event.reason}`;
    case "workflow_step_start":
      return `${event.step_label} running`;
    case "workflow_step_end":
      return `${event.step_label} ${event.status}`;
    case "workflow_artifact":
      return `${event.scope}: ${event.artifact.path}`;
  }
}

type StatusTone = "neutral" | "accent" | "warning" | "danger" | "info";
type ConnectionState =
  | "checking"
  | "reconnecting"
  | "connected"
  | "offline"
  | "unavailable";

function StatusPill({
  label,
  leading,
  tone = "neutral",
  title,
  className,
}: {
  label: string;
  leading?: ReactNode;
  tone?: StatusTone;
  title?: string;
  className?: string;
}) {
  const toneClass =
    tone === "accent"
      ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
      : tone === "warning"
        ? "border-[rgba(194,136,47,0.2)] bg-[rgba(194,136,47,0.1)] text-[rgb(142,98,29)]"
        : tone === "danger"
          ? "border-[rgba(189,72,72,0.18)] bg-[rgba(189,72,72,0.1)] text-[rgb(149,49,49)]"
          : tone === "info"
            ? "border-[rgba(52,126,183,0.18)] bg-[rgba(52,126,183,0.1)] text-[rgb(48,96,143)]"
            : "border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-500";

  return (
    <span
      title={title}
      className={cn(
        "inline-flex min-w-0 items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[11px] font-medium",
        toneClass,
        className
      )}
    >
      {leading}
      <span className="truncate">{label}</span>
    </span>
  );
}

function ConnectionDot({ tone }: { tone: StatusTone }) {
  const dotClass =
    tone === "accent"
      ? "bg-[var(--apex-accent)]"
      : tone === "warning"
        ? "bg-[rgb(194,136,47)]"
        : tone === "danger"
          ? "bg-[rgb(189,72,72)]"
          : tone === "info"
            ? "bg-[rgb(52,126,183)]"
            : "bg-slate-400";

  return <span className={cn("h-1.5 w-1.5 rounded-full", dotClass)} />;
}

function authDraftsFromState(state: {
  inspectionBearerToken?: string | null;
  executionBearerToken?: string | null;
  adminBearerToken?: string | null;
}): Record<AccessScope, string> {
  return {
    inspection: state.inspectionBearerToken ?? "",
    execution: state.executionBearerToken ?? "",
    admin: state.adminBearerToken ?? "",
  };
}

function readinessTone(state: ReadinessState): StatusTone {
  if (state === "blocked") return "danger";
  if (state === "warning" || state === "approval_required") return "warning";
  if (state === "approved") return "info";
  if (state === "ready") return "accent";
  return "neutral";
}

function formatWorkflowLabel(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function workflowLabel(
  summary: WorkflowSummary,
  selectedWorkflow: string | null,
  selectionPending: boolean
): string | null {
  if (selectionPending && selectedWorkflow) {
    return formatWorkflowLabel(selectedWorkflow);
  }

  if (summary.workflowName) {
    return summary.workflowName;
  }

  if (selectedWorkflow) {
    return formatWorkflowLabel(selectedWorkflow);
  }

  if (summary.workflowId) {
    return formatWorkflowLabel(summary.workflowId);
  }

  return null;
}

function workflowTone(
  summary: WorkflowSummary,
  selectedWorkflow: string | null,
  selectionPending: boolean
): StatusTone {
  if (summary.status === "blocked" || summary.status === "failed") return "danger";
  if (workflowLabel(summary, selectedWorkflow, selectionPending)) return "accent";
  return "neutral";
}

function describeWorkflow(
  summary: WorkflowSummary,
  selectedWorkflow: string | null,
  selectionPending: boolean
): string {
  const label = workflowLabel(summary, selectedWorkflow, selectionPending);

  if (!label) {
    return "No active workflow selected.";
  }

  if (selectionPending) {
    return `${label} is selected and waiting to start.`;
  }

  if (!summary.workflowName) {
    return `${label} is selected and waiting to start.`;
  }

  const statusLabel =
    summary.status === "blocked"
      ? "blocked"
      : summary.status === "failed"
        ? "failed"
        : summary.status === "not_started"
          ? "not started"
          : summary.status === "running"
            ? "in progress"
            : summary.status === "completed"
              ? "completed"
              : "idle";
  const parts = [`${label} is ${statusLabel}.`];

  if (summary.currentStep) {
    parts.push(`Current step: ${summary.currentStep}.`);
  }

  if (summary.totalSteps !== null) {
    parts.push(`${summary.completedSteps}/${summary.totalSteps} steps completed.`);
  } else if (summary.observedSteps > 0) {
    parts.push(
      `${summary.completedSteps}/${summary.observedSteps} observed steps completed.`
    );
  }

  if (summary.blockedReason) {
    parts.push(summary.blockedReason);
  }

  if (summary.failureReason) {
    parts.push(summary.failureReason);
  }

  return parts.join(" ");
}

function exportFilename(title: string): string {
  return (
    title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
    "bioapex-session"
  );
}

export default function Navbar() {
  const {
    apiAuthState,
    accessByScope,
    setAccessToken,
    clearAccessTokens,
    refreshAccessState,
    sessions,
    currentSessionId,
    messages,
    ragMode,
    canManageRagMode,
    setRagMode,
    isStreaming,
    selectedWorkflow,
  } = useApp();
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("checking");
  const [accessPanelOpen, setAccessPanelOpen] = useState(false);
  const [accessDrafts, setAccessDrafts] = useState<Record<AccessScope, string>>(
    authDraftsFromState(apiAuthState)
  );
  const hasResolvedConnection = useRef(false);
  const accessPanelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setAccessDrafts(authDraftsFromState(apiAuthState));
  }, [apiAuthState]);

  useEffect(() => {
    if (!accessPanelOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!accessPanelRef.current?.contains(event.target as Node)) {
        setAccessPanelOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [accessPanelOpen]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    let active = true;
    let controller: AbortController | null = null;

    const checkBackendHealth = async (showChecking = false) => {
      if (!active) return;

      if (!window.navigator.onLine) {
        controller?.abort();
        setConnectionState("offline");
        return;
      }

      if (showChecking) {
        setConnectionState(
          hasResolvedConnection.current ? "reconnecting" : "checking"
        );
      }

      controller?.abort();
      const requestController = new AbortController();
      controller = requestController;

      try {
        await getHealth(requestController.signal);
        if (active && controller === requestController) {
          hasResolvedConnection.current = true;
          setConnectionState("connected");
        }
      } catch {
        if (
          active &&
          controller === requestController &&
          !requestController.signal.aborted
        ) {
          hasResolvedConnection.current = true;
          setConnectionState(
            window.navigator.onLine ? "unavailable" : "offline"
          );
        }
      }
    };

    const handleOnline = () => {
      void checkBackendHealth(true);
    };

    const handleOffline = () => {
      controller?.abort();
      setConnectionState("offline");
    };

    void checkBackendHealth(true);
    const intervalId = window.setInterval(() => {
      void checkBackendHealth();
    }, 30000);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(intervalId);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const workflowSummary = getWorkflowSummary(messages);
  const pendingWorkflowSelection = isWorkflowSelectionPending(
    messages,
    selectedWorkflow
  );
  const readinessSummary = getReadinessSummary(messages, {
    workflowSummary,
    isStreaming,
  });
  const title = activeSession?.title ?? "BioAPEX Workspace";
  const activeWorkflowLabel = workflowLabel(
    workflowSummary,
    selectedWorkflow,
    pendingWorkflowSelection
  );

  const connectionLabel =
    connectionState === "connected"
      ? "Connected"
      : connectionState === "offline"
        ? "Offline"
        : connectionState === "unavailable"
          ? "Unavailable"
          : connectionState === "reconnecting"
            ? "Reconnecting"
            : "Checking";

  const connectionTone: StatusTone =
    connectionState === "connected"
      ? "accent"
      : connectionState === "reconnecting"
        ? "info"
        : connectionState === "offline" || connectionState === "unavailable"
          ? "danger"
          : "neutral";
  const accessSummary = getOverallAccessSummary(accessByScope);

  const handleAccessDraftChange = (scope: AccessScope, value: string) => {
    setAccessDrafts((current) => ({
      ...current,
      [scope]: value,
    }));
  };

  const handleApplyAccessTokens = () => {
    ACCESS_SCOPES.forEach((scope) => {
      setAccessToken(scope, accessDrafts[scope]);
    });
  };

  const handleClearAccessTokens = () => {
    clearAccessTokens();
  };

  const handleExport = () => {
    const content = buildExportMarkdown(title, messages);
    const blob = new Blob([content], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${exportFilename(title)}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <header className="sticky top-0 z-40 flex-shrink-0 border-b border-[var(--shell-border)] bg-[rgba(255,255,255,0.94)] backdrop-blur">
      <div className="mx-auto flex h-[var(--navbar-height)] w-full max-w-[1460px] items-center gap-3 px-3 sm:px-5">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
          <div className="flex h-9 flex-shrink-0 items-center gap-2 rounded-full border border-[var(--shell-border)] bg-[rgba(255,255,255,0.82)] px-3">
            <span className="h-2 w-2 rounded-full bg-[var(--apex-accent)]" />
            <span className="text-[13px] font-semibold tracking-tight text-slate-700">
              BioAPEX
            </span>
          </div>

          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Workspace
            </p>
            <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
              <span className="truncate text-[15px] font-semibold tracking-tight text-slate-800 sm:text-base">
                {title}
              </span>
              <ChevronDown size={15} className="flex-shrink-0 text-slate-400" />
            </div>
          </div>
        </div>

        <div className="relative ml-auto flex items-center gap-1.5 sm:gap-2">
          <StatusPill
            label={connectionLabel}
            tone={connectionTone}
            title="Backend connection status"
            leading={<ConnectionDot tone={connectionTone} />}
          />

          <div ref={accessPanelRef} className="relative">
            <button
              type="button"
              onClick={() => setAccessPanelOpen((value) => !value)}
              className={cn(
                "inline-flex min-w-0 items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[11px] font-medium transition-colors",
                accessSummary.tone === "accent"
                  ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)] hover:bg-[rgba(35,130,83,0.16)]"
                  : accessSummary.tone === "warning"
                    ? "border-[rgba(194,136,47,0.2)] bg-[rgba(194,136,47,0.1)] text-[rgb(142,98,29)] hover:bg-[rgba(194,136,47,0.16)]"
                    : accessSummary.tone === "danger"
                      ? "border-[rgba(189,72,72,0.18)] bg-[rgba(189,72,72,0.1)] text-[rgb(149,49,49)] hover:bg-[rgba(189,72,72,0.16)]"
                      : "border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-500 hover:bg-white hover:text-slate-700"
              )}
              title={accessSummary.detail}
            >
              <KeyRound size={12} className="flex-shrink-0" />
              <span className="hidden truncate sm:inline">{accessSummary.label}</span>
            </button>

            {accessPanelOpen ? (
              <div className="absolute right-0 top-full z-50 mt-2 w-[min(26rem,calc(100vw-2rem))] rounded-[22px] border border-[var(--shell-border)] bg-[rgba(255,255,255,0.98)] p-4 shadow-[0_20px_48px_rgba(29,42,33,0.14)] backdrop-blur">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      Access Control
                    </p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">
                      {accessSummary.label}
                    </p>
                    <p className="mt-1 text-[12px] leading-5 text-slate-500">
                      {accessSummary.detail}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void refreshAccessState()}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--shell-border)] bg-white text-slate-500 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-700"
                    title="Recheck access scopes"
                  >
                    <RefreshCw size={13} />
                  </button>
                </div>

                <div className="mt-4 space-y-3">
                  {ACCESS_SCOPES.map((scope) => {
                    const state = accessByScope[scope];
                    return (
                      <div
                        key={scope}
                        className="rounded-[18px] border border-[rgba(226,232,240,0.95)] bg-[rgba(248,250,252,0.9)] px-3 py-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-700">
                              {scope}
                            </p>
                            <p className="mt-1 text-[11px] leading-5 text-slate-500">
                              {scopeRequirement(scope)}
                            </p>
                          </div>
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em]",
                              state.status === "granted"
                                ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]"
                                : state.status === "checking"
                                  ? "border-[rgba(148,163,184,0.24)] bg-[rgba(248,250,252,0.94)] text-slate-600"
                                  : state.status === "server_misconfigured"
                                    ? "border-[rgba(217,119,6,0.22)] bg-[rgba(255,247,237,0.95)] text-amber-700"
                                    : "border-[rgba(220,38,38,0.18)] bg-[rgba(254,242,242,0.95)] text-rose-700"
                            )}
                          >
                            {accessStatusBadgeLabel(state)}
                          </span>
                        </div>

                        <p className="mt-2 text-[12px] leading-5 text-slate-600">
                          {state.detail}
                        </p>

                        <label className="mt-3 block">
                          <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                            Bearer token
                          </span>
                          <input
                            type="password"
                            value={accessDrafts[scope]}
                            onChange={(event) =>
                              handleAccessDraftChange(scope, event.target.value)
                            }
                            placeholder={`Optional ${scope} token`}
                            className="w-full rounded-[12px] border border-[var(--shell-border)] bg-white px-3 py-2 text-[13px] text-slate-700 outline-none placeholder:text-slate-400 focus:border-[var(--apex-accent)]"
                          />
                        </label>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <p className="w-full text-[11px] leading-5 text-slate-500">
                    Tokens stay in memory for this browser tab and clear on reload.
                  </p>
                  <button
                    type="button"
                    onClick={handleApplyAccessTokens}
                    className="inline-flex items-center gap-2 rounded-full border border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] px-3 py-1.5 text-[11px] font-semibold text-[var(--apex-accent-strong)] transition-colors hover:bg-[rgba(35,130,83,0.16)]"
                  >
                    <ShieldCheck size={12} />
                    Apply Tokens
                  </button>
                  <button
                    type="button"
                    onClick={handleClearAccessTokens}
                    className="inline-flex items-center gap-2 rounded-full border border-[var(--shell-border)] bg-white px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800"
                  >
                    Clear Tokens
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <StatusPill
            label={activeWorkflowLabel ?? "No workflow"}
            tone={workflowTone(
              workflowSummary,
              selectedWorkflow,
              pendingWorkflowSelection
            )}
            title={describeWorkflow(
              workflowSummary,
              selectedWorkflow,
              pendingWorkflowSelection
            )}
            className="hidden max-w-[220px] md:inline-flex"
            leading={<GitBranch size={12} className="flex-shrink-0" />}
          />

          {canManageRagMode ? (
            <button
              type="button"
              onClick={() => void setRagMode(!ragMode)}
              className={cn(
                "hidden min-w-0 items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[11px] font-medium transition-colors sm:inline-flex",
                ragMode
                  ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)] hover:bg-[rgba(35,130,83,0.16)]"
                  : "border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-500 hover:bg-white hover:text-slate-700"
              )}
              title={
                ragMode
                  ? "Retrieval-augmented generation is enabled. Click to disable it."
                  : "Retrieval-augmented generation is disabled. Click to enable it."
              }
            >
              <Sparkles size={12} className="flex-shrink-0" />
              <span className="truncate">{ragMode ? "RAG On" : "RAG Off"}</span>
            </button>
          ) : null}

          <StatusPill
            label={readinessSummary.label}
            tone={readinessTone(readinessSummary.state)}
            title={readinessSummary.detail ?? undefined}
            leading={
              readinessSummary.state === "blocked" ||
              readinessSummary.state === "warning" ||
              readinessSummary.state === "approval_required" ? (
                <ShieldAlert size={12} className="flex-shrink-0" />
              ) : (
                <ShieldCheck size={12} className="flex-shrink-0" />
              )
            }
          />

          <button
            onClick={handleExport}
            disabled={messages.length === 0}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold transition-colors",
              messages.length === 0
                ? "cursor-not-allowed border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-400"
                : "border-[rgba(35,130,83,0.18)] bg-[var(--panel-strong)] text-slate-700 hover:bg-[var(--apex-accent-soft)] hover:text-[var(--apex-accent-strong)]"
            )}
            title={
              messages.length === 0
                ? "Start a conversation to export this workspace."
                : "Export the current session transcript."
            }
          >
            <Download size={13} className="flex-shrink-0" />
            <span className="hidden sm:inline">Export</span>
          </button>

          <div
            title="Local workspace profile"
            className="inline-flex items-center gap-2 rounded-full border border-[var(--shell-border)] bg-[var(--panel-strong)] px-1.5 py-1"
          >
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[var(--apex-accent)] text-[11px] font-semibold text-white">
              B
            </span>
            <span className="hidden pr-1 text-[11px] font-medium text-slate-600 lg:inline">
              Local
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
