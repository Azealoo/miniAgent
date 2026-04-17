"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Download, KeyRound, RefreshCw } from "lucide-react";
import {
  ACCESS_SCOPES,
  accessStatusBadgeLabel,
  getOverallAccessSummary,
  scopeRequirement,
} from "@/lib/access-control";
import { getHealth } from "@/lib/api";
import {
  getMessageRetrievals,
  getMessageToolCalls,
} from "@/lib/message-blocks";
import { getReadinessSummary, type ReadinessState } from "@/lib/session-status";
import { useApp } from "@/lib/store";
import type { AccessScope, Message } from "@/lib/types";
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

    const retrievals = getMessageRetrievals(message);
    if (retrievals.length) {
      lines.push("");
      lines.push("Retrieved sources:");
      retrievals.forEach((result) => {
        lines.push(`- ${result.source} (score ${result.score.toFixed(3)})`);
      });
    }

    const toolCalls = getMessageToolCalls(message);
    if (toolCalls.length) {
      lines.push("");
      lines.push("Tool calls:");
      toolCalls.forEach((call) => {
        lines.push(`- ${call.tool}`);
      });
    }

    lines.push("");
  });

  return lines.join("\n").trim() + "\n";
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
}: {
  label: string;
  leading?: ReactNode;
  tone?: StatusTone;
  title?: string;
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
        toneClass
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
  if (state === "warning") return "warning";
  if (state === "ready") return "accent";
  return "neutral";
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
    isStreaming,
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
  const readinessSummary = getReadinessSummary(messages, { isStreaming });
  const title = activeSession?.title ?? "BioAPEX Chat";
  const accessSummary = getOverallAccessSummary(accessByScope);

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
              Chat Engine
            </p>
            <div className="mt-0.5 min-w-0">
              <span className="truncate text-[15px] font-semibold tracking-tight text-slate-800 sm:text-base">
                {title}
              </span>
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

          <StatusPill
            label={readinessSummary.label}
            tone={readinessTone(readinessSummary.state)}
            title={readinessSummary.detail ?? "No active readiness warnings."}
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
                              "rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em]",
                              state.status === "granted"
                                ? "bg-[rgba(35,130,83,0.12)] text-[var(--apex-accent-strong)]"
                                : state.status === "checking"
                                  ? "bg-[rgba(59,130,246,0.12)] text-sky-700"
                                  : "bg-[rgba(189,72,72,0.12)] text-[rgb(149,49,49)]"
                            )}
                          >
                            {accessStatusBadgeLabel(state)}
                          </span>
                        </div>

                        <label className="mt-3 block">
                          <span className="text-[11px] font-medium text-slate-600">
                            Bearer token
                          </span>
                          <input
                            type="password"
                            value={accessDrafts[scope]}
                            onChange={(event) =>
                              handleAccessDraftChange(scope, event.target.value)
                            }
                            placeholder={`Optional ${scope} token`}
                            className="mt-1.5 w-full rounded-[12px] border border-[var(--shell-border)] bg-white px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:border-[var(--apex-accent)]"
                          />
                        </label>

                        <p className="mt-2 text-[11px] leading-5 text-slate-500">
                          {state.detail}
                        </p>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-4 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={clearAccessTokens}
                    className="rounded-full border border-[var(--shell-border)] bg-white px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800"
                  >
                    Clear
                  </button>
                  <button
                    type="button"
                    onClick={handleApplyAccessTokens}
                    className="rounded-full bg-[var(--apex-accent)] px-3 py-1.5 text-[11px] font-semibold text-white transition-colors hover:bg-[var(--apex-accent-strong)]"
                  >
                    Apply Tokens
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <button
            type="button"
            onClick={handleExport}
            disabled={messages.length === 0}
            className="inline-flex items-center gap-1.5 rounded-full border border-[var(--shell-border)] bg-white/92 px-2.5 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            title={
              messages.length > 0
                ? "Export the current chat session as Markdown"
                : "Start a conversation to enable export"
            }
          >
            <Download size={12} />
            <span className="hidden sm:inline">Export</span>
          </button>
        </div>
      </div>
    </header>
  );
}
