"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ChevronDown,
  Download,
  GitBranch,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { getHealth } from "@/lib/api";
import {
  getReadinessSummary,
  getWorkflowSummary,
  isWorkflowSelectionPending,
  type ReadinessState,
  type WorkflowSummary,
} from "@/lib/session-status";
import { useApp } from "@/lib/store";
import type { Message, WorkflowStreamEvent } from "@/lib/types";
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
  if (summary.status === "blocked") return "danger";
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
      : summary.status === "running"
        ? "running"
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
    sessions,
    currentSessionId,
    messages,
    ragMode,
    isStreaming,
    selectedWorkflow,
  } = useApp();
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("checking");
  const hasResolvedConnection = useRef(false);

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

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <StatusPill
            label={connectionLabel}
            tone={connectionTone}
            title="Backend connection status"
            leading={<ConnectionDot tone={connectionTone} />}
          />

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

          <StatusPill
            label={ragMode ? "RAG On" : "RAG Off"}
            tone={ragMode ? "accent" : "neutral"}
            title={
              ragMode
                ? "Retrieval-augmented generation is enabled."
                : "Retrieval-augmented generation is disabled."
            }
            className="hidden sm:inline-flex"
            leading={<Sparkles size={12} className="flex-shrink-0" />}
          />

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
