"use client";

import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import {
  BookOpen,
  Check,
  Edit2,
  Files,
  FlaskConical,
  MessageSquare,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import {
  getWorkflowSummary,
  isWorkflowSelectionPending,
} from "@/lib/session-status";
import { useApp } from "@/lib/store";
import type { Message } from "@/lib/types";
import { cn, formatRelativeTime } from "@/lib/utils";

type RailView = "sessions" | "flows" | "docs" | "files";

interface QuickStartItem {
  id: string;
  label: string;
  description: string;
  kind: string;
  icon: typeof FlaskConical;
  workflowId?: string | null;
  draftMessage: string;
}

interface SurfaceItem {
  id: string;
  label: string;
  description: string;
  meta?: string;
  icon: typeof FlaskConical;
  path?: string;
}

const primaryNavItems: Array<{
  id: RailView;
  label: string;
  icon: typeof FlaskConical;
}> = [
  { id: "sessions", label: "Sessions", icon: MessageSquare },
  { id: "flows", label: "Flows", icon: FlaskConical },
  { id: "docs", label: "Docs", icon: BookOpen },
  { id: "files", label: "Files", icon: Files },
];

const quickStartItems: QuickStartItem[] = [
  {
    id: "rnaseq-de",
    label: "RNA-seq DE",
    description: "Prime the RNA-seq differential expression workflow.",
    kind: "Workflow",
    icon: FlaskConical,
    workflowId: "rnaseq_qc_de",
    draftMessage:
      "Run the RNA-seq differential expression workflow on the attached dataset manifest with condition_field=condition baseline_condition=control comparison_condition=treated. Use the standard QC and report outputs unless I provide different parameters.",
  },
  {
    id: "evidence-review",
    label: "Evidence Review",
    description: "Draft a source-grounded evidence review request.",
    kind: "Review",
    icon: BookOpen,
    draftMessage:
      "Review the evidence for this biology question, separate source facts from conclusions, and cite the strongest supporting artifacts.",
  },
  {
    id: "compliance",
    label: "Compliance",
    description: "Prepare a compliance and readiness check request.",
    kind: "Safety",
    icon: ShieldCheck,
    draftMessage:
      "Run a compliance and readiness check on this request, summarize any warnings or approvals required, and note what information is missing.",
  },
];

const workspaceDocs: SurfaceItem[] = [
  {
    id: "current-feature",
    label: "Current Feature",
    description: "Active implementation contract for this pass.",
    meta: "context/current-feature.md",
    icon: BookOpen,
    path: "context/current-feature.md",
  },
  {
    id: "project-overview",
    label: "Project Overview",
    description: "Mission, architecture, and product direction.",
    meta: "context/project-overview.md",
    icon: BookOpen,
    path: "context/project-overview.md",
  },
  {
    id: "coding-standards",
    label: "Coding Standards",
    description: "Frontend and backend implementation guardrails.",
    meta: "context/coding-standards.md",
    icon: BookOpen,
    path: "context/coding-standards.md",
  },
  {
    id: "ai-interaction",
    label: "AI Interaction",
    description: "Feature workflow and review expectations.",
    meta: "context/ai-interaction.md",
    icon: BookOpen,
    path: "context/ai-interaction.md",
  },
];

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-400">
      {children}
    </p>
  );
}

function EmptyRailState({ children }: { children: ReactNode }) {
  return (
    <div className="px-1 py-2 text-sm leading-6 text-slate-500">
      {children}
    </div>
  );
}

function SurfaceRow({
  item,
  active = false,
  onClick,
}: {
  item: SurfaceItem;
  active?: boolean;
  onClick?: () => void;
}) {
  const Icon = item.icon;
  const containerClass = cn(
    "group w-full border-b border-[rgba(211,219,210,0.8)] border-l-2 px-1 py-3 transition-colors last:border-b-0",
    active
      ? "border-l-[var(--apex-accent)] bg-transparent"
      : "border-l-transparent bg-transparent hover:bg-white/35",
    onClick && "cursor-pointer text-left"
  );
  const content = (
    <div className="flex items-start gap-2.5">
      <div
        className={cn(
          "mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-[8px]",
          active
            ? "bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
            : "bg-transparent text-slate-400"
        )}
      >
        <Icon size={14} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p
            className={cn(
              "truncate text-sm font-medium",
              active ? "text-slate-800" : "text-slate-700"
            )}
          >
            {item.label}
          </p>
        </div>
        {item.meta ? (
          <p className="mt-0.5 truncate text-[10px] text-slate-400">{item.meta}</p>
        ) : null}
        <p className="mt-1 text-[11px] leading-5 text-slate-500">{item.description}</p>
      </div>
    </div>
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={containerClass}>
        {content}
      </button>
    );
  }

  return (
    <div className={containerClass}>
      {content}
    </div>
  );
}

function formatWorkflowLabel(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function humanizeToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function shortenPath(path: string): string {
  const segments = path.split("/").filter(Boolean);
  if (segments.length <= 2) return path;
  return segments.slice(-2).join("/");
}

function matchesQuery(
  query: string,
  ...parts: Array<string | null | undefined>
): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  return parts.some((part) => part?.toLowerCase().includes(normalizedQuery));
}

function workflowMeta(
  messages: Message[],
  selectedWorkflow: string | null,
  selectionPending: boolean
): SurfaceItem[] {
  const summary = getWorkflowSummary(messages);
  const items: SurfaceItem[] = [];

  if (selectedWorkflow) {
    items.push({
      id: `selected-${selectedWorkflow}`,
      label:
        !selectionPending &&
        summary.workflowId === selectedWorkflow &&
        summary.workflowName
          ? summary.workflowName
          : formatWorkflowLabel(selectedWorkflow),
      description:
        !selectionPending &&
        summary.workflowId === selectedWorkflow &&
        summary.status !== "idle"
          ? describeWorkflow(summary)
          : "Selected and ready for the next request.",
      meta:
        !selectionPending && summary.workflowId === selectedWorkflow
          ? summarizeWorkflowMeta(summary)
          : "Selected",
      icon: FlaskConical,
    });
  }

  if (summary.workflowId && summary.workflowId !== selectedWorkflow) {
    items.push({
      id: `recent-${summary.workflowId}`,
      label: summary.workflowName ?? formatWorkflowLabel(summary.workflowId),
      description: describeWorkflow(summary),
      meta: summarizeWorkflowMeta(summary),
      icon: FlaskConical,
    });
  }

  return items;
}

function summarizeWorkflowMeta(summary: ReturnType<typeof getWorkflowSummary>): string {
  if (summary.status === "running" || summary.status === "not_started") {
    if (summary.totalSteps !== null) {
      return `${summary.completedSteps}/${summary.totalSteps} steps`;
    }
    if (summary.observedSteps > 0) {
      return `${summary.completedSteps}/${summary.observedSteps} observed`;
    }
    return summary.status === "not_started" ? "Not started" : "Running";
  }

  if (summary.status === "blocked") return "Blocked";
  if (summary.status === "failed") return "Failed";
  if (summary.status === "completed") {
    if (summary.totalSteps !== null) {
      return `${summary.completedSteps}/${summary.totalSteps} steps`;
    }
    return "Completed";
  }

  return "Idle";
}

function describeWorkflow(summary: ReturnType<typeof getWorkflowSummary>): string {
  if (summary.status === "blocked") {
    return summary.blockedReason ?? "Workflow execution is blocked.";
  }

  if (summary.status === "failed") {
    return summary.failureReason ?? "Latest workflow run failed.";
  }

  if (summary.status === "not_started") {
    return summary.totalSteps !== null
      ? `Workflow run is ready to begin with ${summary.totalSteps} step${summary.totalSteps === 1 ? "" : "s"}.`
      : "Workflow run is ready to begin.";
  }

  if (summary.status === "running") {
    if (summary.currentStep) {
      return `${summary.currentStep} is running now.`;
    }
    return "Workflow execution is in progress.";
  }

  if (summary.status === "completed") {
    return "Latest workflow run completed successfully.";
  }

  return "No workflow run has started yet.";
}

function recentFiles(messages: Message[]): SurfaceItem[] {
  const items: SurfaceItem[] = [];
  const seenPaths = new Set<string>();

  const pushItem = (
    path: string | null | undefined,
    description: string,
    meta?: string | null
  ) => {
    if (!path || seenPaths.has(path) || items.length >= 6) return;
    seenPaths.add(path);
    items.push({
      id: path,
      label: path.split("/").pop() ?? path,
      description,
      meta: meta ?? shortenPath(path),
      icon: Files,
      path,
    });
  };

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex];

    const workflowEvents = message.workflow_events ?? [];
    for (let eventIndex = workflowEvents.length - 1; eventIndex >= 0; eventIndex -= 1) {
      const event = workflowEvents[eventIndex];
      if (event.type !== "workflow_artifact") continue;
      pushItem(
        event.artifact.path,
        humanizeToken(event.artifact.artifact_type) ?? "Workflow artifact"
      );
    }

    const toolCalls = message.tool_calls ?? [];
    for (let callIndex = toolCalls.length - 1; callIndex >= 0; callIndex -= 1) {
      const artifactRefs = toolCalls[callIndex]?.result?.artifact_refs ?? [];
      for (let refIndex = artifactRefs.length - 1; refIndex >= 0; refIndex -= 1) {
        const ref = artifactRefs[refIndex];
        pushItem(
          ref.path,
          humanizeToken(ref.artifact_type) ?? ref.label ?? "Tool artifact"
        );
      }
    }
  }

  return items;
}

export default function Sidebar() {
  const {
    sessions,
    currentSessionId,
    messages,
    createSession,
    selectSession,
    deleteSession,
    renameSession,
    isStreaming,
    isReferenceUploading,
    ragMode,
    selectedWorkflow,
    draftMessage,
    inspectorTab,
    inspectorPreviewPath,
    selectWorkflow,
    primeDraftMessage,
    clearDraftMessage,
    openInspectorPath,
  } = useApp();

  const [activeView, setActiveView] = useState<RailView>("sessions");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const sessionActionsLocked = isStreaming || isReferenceUploading;
  const sessionActionLockTitle = isStreaming
    ? "Wait for streaming to finish before editing sessions"
    : "Wait for the current reference upload to finish before editing sessions";

  const filteredQuickStartItems = quickStartItems.filter((item) =>
    matchesQuery(query, item.label, item.description, item.kind)
  );
  const filteredSessions = sessions.filter((session) =>
    matchesQuery(query, session.title)
  );
  const filteredDocs = workspaceDocs.filter((item) =>
    matchesQuery(query, item.label, item.description, item.meta)
  );
  const pendingWorkflowSelection = isWorkflowSelectionPending(
    messages,
    selectedWorkflow
  );
  const filteredWorkflowItems = workflowMeta(
    messages,
    selectedWorkflow,
    pendingWorkflowSelection
  ).filter((item) => matchesQuery(query, item.label, item.description, item.meta));
  const filteredFileItems = recentFiles(messages).filter((item) =>
    matchesQuery(query, item.label, item.description, item.meta)
  );
  const sessionSectionLabel = "Recent";
  const sessionEmptyMessage =
    sessions.length === 0
      ? "No sessions yet. Start a new workspace to see it here."
      : trimmedQuery
        ? `No sessions match "${trimmedQuery}".`
        : "No recent sessions yet.";

  useEffect(() => {
    if (!sessionActionsLocked) return;
    setEditingId(null);
    setEditTitle("");
  }, [sessionActionsLocked]);

  const handleCreate = async () => {
    if (sessionActionsLocked) return;
    setActiveView("sessions");
    setEditingId(null);
    await createSession();
  };

  const handleSelect = async (id: string) => {
    if (sessionActionsLocked) return;
    setActiveView("sessions");
    await selectSession(id);
    setEditingId(null);
  };

  const startEdit = (id: string, title: string, e: MouseEvent<HTMLButtonElement>) => {
    if (sessionActionsLocked) return;
    e.stopPropagation();
    setEditingId(id);
    setEditTitle(title);
  };

  const confirmEdit = async (id: string) => {
    if (sessionActionsLocked) return;
    if (editTitle.trim()) {
      await renameSession(id, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleDelete = async (id: string, e: MouseEvent<HTMLButtonElement>) => {
    if (sessionActionsLocked) return;
    e.stopPropagation();
    if (confirm("Delete this session?")) {
      await deleteSession(id);
    }
  };

  const isQuickStartActive = (item: QuickStartItem): boolean =>
    item.workflowId
      ? selectedWorkflow === item.workflowId
      : !selectedWorkflow && draftMessage === item.draftMessage;

  const handleQuickStart = (item: QuickStartItem) => {
    if (sessionActionsLocked) return;

    if (isQuickStartActive(item)) {
      selectWorkflow(null);
      clearDraftMessage();
      setActiveView("sessions");
      return;
    }

    selectWorkflow(item.workflowId ?? null);
    primeDraftMessage(item.draftMessage);
    setActiveView(item.workflowId ? "flows" : "sessions");
    setEditingId(null);
  };

  const focusTitle =
    activeView === "flows"
      ? "Flow Focus"
      : activeView === "docs"
        ? "Working Docs"
        : activeView === "files"
          ? "Generated"
          : null;
  const focusItems =
    activeView === "flows"
      ? filteredWorkflowItems
      : activeView === "docs"
        ? filteredDocs
        : activeView === "files"
          ? filteredFileItems
          : [];

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] px-2.5 py-3">
        <button
          onClick={handleCreate}
          disabled={sessionActionsLocked}
          className="flex w-full items-center justify-center gap-2 rounded-[12px] bg-[var(--apex-accent)] px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--apex-accent-strong)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Plus size={15} />
          New
        </button>

        <div className="relative mt-2.5">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions and work"
            className="w-full rounded-[11px] border border-[var(--shell-border)] bg-white px-8 py-1.5 text-[13px] text-slate-700 outline-none placeholder:text-slate-400 focus:border-[var(--apex-accent)]"
          />
        </div>
      </div>

      <div className="border-b border-[var(--shell-border)] px-1.5 py-1.5">
        <div className="grid grid-cols-4 gap-0.5">
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            const active = activeView === item.id;

            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveView(item.id)}
                className={cn(
                  "flex flex-col items-center gap-0 rounded-[8px] px-0.5 py-1 text-[9px] leading-tight transition-colors",
                  active
                    ? "bg-white text-[var(--apex-accent-strong)] shadow-[var(--panel-shadow-soft)]"
                    : "text-slate-500 hover:bg-white/75 hover:text-slate-700"
                )}
              >
                <span
                  className={cn(
                    "flex h-[22px] w-[22px] items-center justify-center rounded-[7px]",
                    active ? "bg-[var(--apex-accent-soft)]" : "bg-transparent"
                  )}
                >
                  <Icon size={12} />
                </span>
                <span className="mt-0.5">{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="border-b border-[var(--shell-border)] px-2.5 py-2.5">
        <div className="flex items-center justify-between">
          <SectionLabel>Quick Start</SectionLabel>
          <span className="text-[10px] text-slate-400">
            {filteredQuickStartItems.length === 0 ? "Empty" : `${filteredQuickStartItems.length} items`}
          </span>
        </div>

        <div className="mt-2">
          {filteredQuickStartItems.map((item) => {
            const Icon = item.icon;
            const active = isQuickStartActive(item);

            return (
              <button
                key={item.id}
                type="button"
                onClick={() => handleQuickStart(item)}
                disabled={sessionActionsLocked}
                className={cn(
                  "flex w-full items-center gap-2 border-b border-[rgba(211,219,210,0.8)] border-l-2 px-1 py-1.5 text-left transition-colors last:border-b-0 disabled:cursor-not-allowed disabled:opacity-60",
                  active
                    ? "border-l-[var(--apex-accent)] bg-transparent"
                    : "border-l-transparent bg-transparent hover:bg-white/35"
                )}
              >
                <div
                  className={cn(
                    "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-[7px]",
                    active
                      ? "bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
                      : "bg-transparent text-slate-400"
                  )}
                >
                  <Icon size={12} />
                </div>

                <div className="min-w-0 flex flex-1 items-center justify-between gap-2">
                  <p className="truncate text-[13px] font-medium text-slate-700">
                    {item.label}
                  </p>
                  <span className="text-[9px] uppercase tracking-[0.14em] text-slate-400">
                    {item.kind}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3 pt-3">
        {focusTitle ? (
          <div>
            <div className="flex items-center justify-between">
              <SectionLabel>{focusTitle}</SectionLabel>
              <span className="text-[10px] text-slate-400">
                {focusItems.length === 0 ? "Empty" : `${focusItems.length} items`}
              </span>
            </div>

            <div className="mt-2">
              {focusItems.length === 0 ? (
                <EmptyRailState>
                  {activeView === "flows"
                    ? "No selected or recent workflow runs yet."
                    : activeView === "docs"
                      ? "No working docs match this search."
                      : "No generated files are visible in this session yet."}
                </EmptyRailState>
              ) : (
                focusItems.map((item) => {
                  const previewPath = item.path;

                  return (
                    <SurfaceRow
                      key={item.id}
                      item={item}
                      active={
                        Boolean(previewPath) &&
                        inspectorTab === "files" &&
                        inspectorPreviewPath === previewPath
                      }
                      onClick={
                        previewPath ? () => openInspectorPath(previewPath) : undefined
                      }
                    />
                  );
                })
              )}
            </div>
          </div>
        ) : null}

        <div className={cn(focusTitle && "mt-4")}>
          <div className="flex items-center justify-between">
            <SectionLabel>{sessionSectionLabel}</SectionLabel>
            <span className="text-[10px] text-slate-400">
              {filteredSessions.length === 0 ? "Empty" : `${filteredSessions.length} items`}
            </span>
          </div>

          {sessionActionsLocked ? (
            <div className="mt-2 rounded-[12px] border border-[rgba(226,232,240,0.95)] bg-white/70 px-3 py-2 text-[11px] leading-5 text-slate-500">
              Session switching is locked while the current response or reference upload is in progress.
            </div>
          ) : null}

          <div className="mt-2">
            {filteredSessions.length === 0 ? (
              <EmptyRailState>{sessionEmptyMessage}</EmptyRailState>
            ) : (
              filteredSessions.map((session) => (
                <div
                  key={session.id}
                  className={cn(
                    "group border-b border-[rgba(211,219,210,0.8)] border-l-2 px-1 py-3 transition-colors last:border-b-0",
                    session.id === currentSessionId
                      ? "border-l-[var(--apex-accent)] bg-transparent"
                      : "border-l-transparent bg-transparent hover:bg-white/35"
                  )}
                >
                  {editingId === session.id ? (
                    <div
                      className="flex items-center gap-2"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        autoFocus
                        className="min-w-0 flex-1 rounded-[10px] border border-[var(--shell-border)] bg-white px-3 py-1.5 text-xs text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") confirmEdit(session.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => confirmEdit(session.id)}
                        disabled={sessionActionsLocked}
                        className="rounded-full p-1.5 text-[var(--apex-accent)] hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Check size={12} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        disabled={sessionActionsLocked}
                        className="rounded-full p-1.5 text-slate-400 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-start gap-2.5">
                      <button
                        type="button"
                        onClick={() => handleSelect(session.id)}
                        disabled={sessionActionsLocked}
                        className="min-w-0 flex flex-1 items-start gap-2.5 text-left disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <div
                          className={cn(
                            "mt-1 h-2.5 w-2.5 flex-shrink-0 rounded-full",
                            session.id === currentSessionId
                              ? "bg-[var(--apex-accent)]"
                              : "bg-slate-300"
                          )}
                        />

                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <p className="truncate text-sm font-medium text-slate-700">
                              {session.title}
                            </p>
                            <span className="mt-0.5 flex-shrink-0 text-[10px] text-slate-400">
                              {formatRelativeTime(session.updated_at)}
                            </span>
                          </div>
                        </div>
                      </button>

                      <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                        <button
                          type="button"
                          onClick={(e) => startEdit(session.id, session.title, e)}
                          disabled={sessionActionsLocked}
                          className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                          title={
                            sessionActionsLocked
                              ? sessionActionLockTitle
                              : "Rename session"
                          }
                        >
                          <Edit2 size={11} />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => handleDelete(session.id, e)}
                          disabled={sessionActionsLocked}
                          className="rounded-full p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                          title={
                            sessionActionsLocked
                              ? sessionActionLockTitle
                              : "Delete session"
                          }
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="border-t border-[var(--shell-border)] px-2.5 py-3">
        <div
          className="flex items-center justify-between text-[10px] font-medium text-slate-400"
          title="Use the top bar RAG control to change retrieval mode."
        >
          <span>{ragMode ? "RAG: On" : "RAG: Off"}</span>
          <span>
            {isStreaming
              ? "Streaming"
              : isReferenceUploading
                ? "Uploading ref"
                : "Ready"}
          </span>
        </div>
      </div>
    </aside>
  );
}
