"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  Download,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { getHealth } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Message, WorkflowStreamEvent } from "@/lib/types";

function getWorkflowSummary(messages: Message[]) {
  const events = messages.flatMap((message) => message.workflow_events ?? []);
  let workflowName: string | null = null;
  let status: "ready" | "running" | "blocked" = "ready";

  for (const event of events) {
    if (event.type === "workflow_start") {
      workflowName = event.workflow_name;
      status = event.lifecycle_status === "blocked" ? "blocked" : "running";
    }

    if (event.type === "workflow_blocked") {
      status = "blocked";
    }

    if (event.type === "workflow_done") {
      status = event.lifecycle_status === "blocked" ? "blocked" : "ready";
    }
  }

  return { workflowName, status, events };
}

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

function StatusLabel({
  tone = "neutral",
  label,
  dot = false,
}: {
  tone?: "neutral" | "accent" | "warning";
  label: string;
  dot?: boolean;
}) {
  const toneClass =
    tone === "accent"
      ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
      : tone === "warning"
        ? "border-[rgba(194,136,47,0.18)] bg-[rgba(194,136,47,0.1)] text-[rgb(142,98,29)]"
        : "border-[var(--shell-border)] bg-[var(--panel-soft)] text-slate-500";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${toneClass}`}
    >
      {dot && (
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            tone === "warning"
              ? "bg-[rgb(194,136,47)]"
              : tone === "accent"
                ? "bg-[var(--apex-accent)]"
                : "bg-slate-400"
          }`}
        />
      )}
      {label}
    </span>
  );
}

type ConnectionState = "checking" | "connected" | "offline" | "unavailable";

export default function Navbar() {
  const { sessions, currentSessionId, messages, ragMode, isStreaming } = useApp();
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("checking");

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
        setConnectionState("checking");
      }

      controller?.abort();
      const requestController = new AbortController();
      controller = requestController;

      try {
        await getHealth(requestController.signal);
        if (active && controller === requestController) {
          setConnectionState("connected");
        }
      } catch {
        if (
          active &&
          controller === requestController &&
          !requestController.signal.aborted
        ) {
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
  const { workflowName, status } = getWorkflowSummary(messages);

  const connectionLabel =
    connectionState === "connected"
      ? "Connected"
      : connectionState === "offline"
        ? "Offline"
        : connectionState === "unavailable"
          ? "Unavailable"
          : "Checking";

  const connectionTone =
    connectionState === "connected"
      ? "accent"
      : connectionState === "checking"
        ? "neutral"
        : "warning";

  const handleExport = () => {
    const title = activeSession?.title ?? "BioAPEX Workspace";
    const content = buildExportMarkdown(title, messages);
    const blob = new Blob([content], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "bioapex-session"}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-[var(--shell-border)] bg-[rgba(255,255,255,0.94)] backdrop-blur">
      <div className="mx-auto flex h-[var(--navbar-height)] w-full max-w-[1460px] items-center gap-4 px-4 sm:px-5">
        <div className="flex min-w-0 items-center gap-4">
          <div className="flex items-center gap-2 border-r border-[var(--shell-border)] pr-4">
            <span className="h-2 w-2 rounded-full bg-[var(--apex-accent)]" />
            <span className="text-[13px] font-semibold tracking-tight text-slate-700">
              BioAPEX
            </span>
          </div>

          <div className="flex min-w-0 items-center gap-1.5">
            <span className="truncate text-lg font-semibold text-slate-800">
              {activeSession?.title ?? "BioAPEX Workspace"}
            </span>
            <ChevronDown size={16} className="flex-shrink-0 text-slate-400" />
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          <StatusLabel
            label={connectionLabel}
            tone={connectionTone}
            dot
          />

          {workflowName && (
            <span className="hidden items-center gap-1.5 text-[11px] font-medium text-slate-500 lg:inline-flex">
              <Sparkles size={12} className="text-slate-400" />
              {workflowName}
            </span>
          )}

          <StatusLabel label={ragMode ? "RAG" : "RAG Off"} tone={ragMode ? "accent" : "neutral"} />

          <span className="hidden items-center gap-1.5 text-[11px] font-medium text-slate-500 md:inline-flex">
            <ShieldCheck
              size={12}
              className={status === "blocked" ? "text-[rgb(194,136,47)]" : "text-[var(--apex-accent)]"}
            />
            {status === "blocked" ? "Attention" : isStreaming ? "Running" : "Ready"}
          </span>

          <button
            onClick={handleExport}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--shell-border)] bg-[var(--panel-strong)] px-3 py-1.5 text-[11px] font-semibold text-slate-600 transition-colors hover:bg-[var(--panel-soft)]"
            title="Export the current session transcript"
          >
            <Download size={13} />
            <span className="hidden sm:inline">Export</span>
          </button>

          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[var(--apex-accent)] text-xs font-semibold text-white">
            B
          </span>
        </div>
      </div>
    </header>
  );
}
