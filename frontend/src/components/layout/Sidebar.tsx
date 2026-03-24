"use client";

import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import {
  Check,
  Clock3,
  Edit2,
  Plus,
  RefreshCw,
  Search,
  SearchX,
  Trash2,
  X,
} from "lucide-react";
import SurfaceState from "@/components/layout/SurfaceState";
import { getOverallAccessSummary } from "@/lib/access-control";
import { isWorkflowSelectionPending } from "@/lib/session-status";
import { useApp } from "@/lib/store";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  getWorkflowSurfaceItems,
  matchesQuery,
  opsWorkspaceSections,
  primaryNavItems,
  type QuickStartItem,
  quickStartItems,
  recentFiles,
  type SurfaceItem,
  workspaceDocs,
} from "./workspace-data";

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

export default function Sidebar() {
  const {
    accessByScope,
    hasExecutionAccess,
    hasInspectionAccess,
    sessions,
    currentSessionId,
    messages,
    refreshSessions,
    createSession,
    selectSession,
    deleteSession,
    renameSession,
    isStreaming,
    isReferenceUploading,
    sessionListStatus,
    sessionListError,
    ragMode,
    canManageRagMode,
    workspaceMode,
    selectedWorkflow,
    draftMessage,
    inspectorTab,
    inspectorPreviewPath,
    setWorkspaceMode,
    selectWorkflow,
    primeDraftMessage,
    clearDraftMessage,
    openInspectorPath,
  } = useApp();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const accessSummary = getOverallAccessSummary(accessByScope);
  const sessionMutationLocked =
    isStreaming || isReferenceUploading || !hasExecutionAccess;
  const sessionMutationLockTitle = !hasExecutionAccess
    ? accessByScope.execution.detail
    : isStreaming
    ? "Wait for streaming to finish before editing sessions"
    : "Wait for the current reference upload to finish before editing sessions";
  const sessionSelectionLocked = isReferenceUploading || !hasInspectionAccess;
  const sessionSelectionLockTitle = !hasInspectionAccess
    ? accessByScope.inspection.detail
    : "Inspection access is required to switch between saved sessions.";

  const filteredQuickStartItems = quickStartItems.filter((item) =>
    matchesQuery(query, item.label, item.description, item.kind)
  );
  const filteredSessions = sessions.filter((session) =>
    matchesQuery(query, session.title)
  );
  const filteredDocs = workspaceDocs.filter((item) =>
    matchesQuery(query, item.label, item.description, item.meta)
  );
  const filteredOpsItems = opsWorkspaceSections.filter((item) =>
    matchesQuery(query, item.label, item.description, item.meta)
  );
  const pendingWorkflowSelection = isWorkflowSelectionPending(
    messages,
    selectedWorkflow
  );
  const filteredWorkflowItems = getWorkflowSurfaceItems(
    messages,
    selectedWorkflow,
    pendingWorkflowSelection
  ).filter((item) => matchesQuery(query, item.label, item.description, item.meta));
  const filteredFileItems = recentFiles(messages).filter((item) =>
    matchesQuery(query, item.label, item.description, item.meta)
  );
  const sessionSectionLabel = "Recent";
  const sessionEmptyMessage =
    !hasInspectionAccess
      ? "Inspection access is required to browse saved sessions."
      : sessions.length === 0
      ? "No sessions yet. Start a new workspace to see it here."
      : trimmedQuery
        ? `No sessions match "${trimmedQuery}".`
        : "No recent sessions yet.";

  useEffect(() => {
    if (!sessionMutationLocked) return;
    setEditingId(null);
    setEditTitle("");
  }, [sessionMutationLocked]);

  const handleCreate = async () => {
    if (sessionMutationLocked) return;
    setWorkspaceMode("sessions");
    setEditingId(null);
    await createSession();
  };

  const handleSelect = async (id: string) => {
    if (sessionSelectionLocked) return;
    setWorkspaceMode("sessions");
    await selectSession(id);
    setEditingId(null);
  };

  const startEdit = (id: string, title: string, e: MouseEvent<HTMLButtonElement>) => {
    if (sessionMutationLocked) return;
    e.stopPropagation();
    setEditingId(id);
    setEditTitle(title);
  };

  const confirmEdit = async (id: string) => {
    if (sessionMutationLocked) return;
    if (editTitle.trim()) {
      await renameSession(id, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleDelete = async (id: string, e: MouseEvent<HTMLButtonElement>) => {
    if (sessionMutationLocked) return;
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
    if (sessionMutationLocked) return;

    if (isQuickStartActive(item)) {
      selectWorkflow(null);
      clearDraftMessage();
      setWorkspaceMode("sessions");
      return;
    }

    selectWorkflow(item.workflowId ?? null);
    primeDraftMessage(item.draftMessage);
    setWorkspaceMode("sessions");
    setEditingId(null);
  };

  const focusTitle =
    workspaceMode === "flows"
      ? "Flow Focus"
      : workspaceMode === "docs"
        ? "Working Docs"
        : workspaceMode === "files"
          ? "Generated"
          : workspaceMode === "ops"
            ? "Inspection"
          : null;
  const focusItems =
    workspaceMode === "flows"
      ? filteredWorkflowItems
      : workspaceMode === "docs"
        ? filteredDocs
        : workspaceMode === "files"
          ? filteredFileItems
          : workspaceMode === "ops"
            ? filteredOpsItems
          : [];

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] px-2.5 py-3">
        <button
          onClick={handleCreate}
          disabled={sessionMutationLocked}
          title={
            !hasExecutionAccess
              ? accessByScope.execution.detail
              : undefined
          }
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
        <div className="grid grid-cols-6 gap-0.5">
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            const active = workspaceMode === item.id;

            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setWorkspaceMode(item.id)}
                aria-label={`Open ${item.label} workspace`}
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
                disabled={sessionMutationLocked}
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
                {workspaceMode === "flows"
                  ? trimmedQuery
                    ? `No workflow entries match "${trimmedQuery}".`
                    : "No selected or recent workflow runs are available yet."
                  : workspaceMode === "docs"
                    ? trimmedQuery
                      ? `No working docs match "${trimmedQuery}".`
                      : "No working docs are loaded for this workspace yet."
                    : workspaceMode === "files"
                      ? trimmedQuery
                        ? `No generated files match "${trimmedQuery}".`
                        : "No generated files are visible in this session yet."
                      : trimmedQuery
                        ? `No inspection views match "${trimmedQuery}".`
                        : "Choose an Ops view to inspect runtime health, traces, or connectors."}
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

          {sessionMutationLocked || sessionSelectionLocked ? (
            <div className="mt-2 rounded-[12px] border border-[rgba(226,232,240,0.95)] bg-white/70 px-3 py-2 text-[11px] leading-5 text-slate-500">
              {!hasInspectionAccess
                ? accessByScope.inspection.detail
                : !hasExecutionAccess
                  ? accessByScope.execution.detail
                  : "Session switching is locked while the current response or reference upload is in progress."}
            </div>
          ) : null}

          <div className="mt-2">
            {accessByScope.inspection.status === "checking" ||
            (sessionListStatus === "loading" && sessions.length === 0) ? (
              <SurfaceState
                compact
                tone="accent"
                eyebrow="Session Sync"
                title="Loading saved sessions"
                description="BioAPEX is checking inspection access and syncing the recent session rail."
                icon={Clock3}
              />
            ) : sessionListStatus === "error" && filteredSessions.length === 0 ? (
              <SurfaceState
                compact
                tone="error"
                eyebrow="Session Rail"
                title="Saved sessions are unavailable"
                description={
                  sessionListError ??
                  "The sidebar could not load the saved session list right now."
                }
                actions={
                  <RailActionButton onClick={() => void refreshSessions()}>
                    <RefreshCw size={12} />
                    Retry
                  </RailActionButton>
                }
              />
            ) : filteredSessions.length === 0 ? (
              <EmptyRailState>{sessionEmptyMessage}</EmptyRailState>
            ) : (
              <div className="space-y-2">
                {sessionListStatus === "loading" ? (
                  <div className="rounded-[12px] border border-[rgba(211,219,210,0.88)] bg-white/78 px-3 py-2 text-[11px] leading-5 text-slate-500">
                    Refreshing the recent session rail in the background.
                  </div>
                ) : null}

                {sessionListStatus === "error" ? (
                  <SurfaceState
                    compact
                    tone="error"
                    eyebrow="Session Sync"
                    title="Recent sessions may be stale"
                    description={
                      sessionListError ??
                      "The latest session refresh failed, so the rail is showing the last successful snapshot."
                    }
                    actions={
                      <RailActionButton onClick={() => void refreshSessions()}>
                        <RefreshCw size={12} />
                        Retry
                      </RailActionButton>
                    }
                  />
                ) : null}

                {filteredSessions.map((session) => (
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
                          disabled={sessionMutationLocked}
                          className="rounded-full p-1.5 text-[var(--apex-accent)] hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <Check size={12} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          disabled={sessionMutationLocked}
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
                          disabled={sessionSelectionLocked}
                          className="min-w-0 flex flex-1 items-start gap-2.5 text-left disabled:cursor-not-allowed disabled:opacity-60"
                          title={
                            sessionSelectionLocked
                              ? sessionSelectionLockTitle
                              : undefined
                          }
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
                            disabled={sessionMutationLocked}
                            className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
                            title={
                              sessionMutationLocked
                                ? sessionMutationLockTitle
                                : "Rename session"
                            }
                          >
                            <Edit2 size={11} />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleDelete(session.id, e)}
                            disabled={sessionMutationLocked}
                            className="rounded-full p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                            title={
                              sessionMutationLocked
                                ? sessionMutationLockTitle
                                : "Delete session"
                            }
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="border-t border-[var(--shell-border)] px-2.5 py-3">
        <div
          className="flex items-center justify-between text-[10px] font-medium text-slate-400"
          title={accessSummary.detail}
        >
          <span>
            {accessSummary.label}
          </span>
          <span>
            {canManageRagMode
              ? ragMode
                ? "RAG On"
                : "RAG Off"
              : accessStatusLabel(accessByScope.admin.status)}
          </span>
        </div>
      </div>
    </aside>
  );
}

function RailActionButton({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-full border border-[var(--shell-border)] bg-white/92 px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800"
    >
      {children}
    </button>
  );
}

function accessStatusLabel(status: "checking" | "granted" | "token_required" | "server_misconfigured" | "forbidden" | "unavailable"): string {
  if (status === "granted") {
    return "Admin Ready";
  }
  if (status === "checking") {
    return "Checking";
  }
  if (status === "token_required") {
    return "Token needed";
  }
  if (status === "server_misconfigured") {
    return "Token empty";
  }
  if (status === "forbidden") {
    return "Remote blocked";
  }
  return "Unavailable";
}
