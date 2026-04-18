"use client";

import { useEffect, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import {
  Check,
  Clock3,
  Edit2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import SurfaceState from "@/components/layout/SurfaceState";
import { useApp } from "@/lib/store";
import { cn, formatRelativeTime } from "@/lib/utils";
import { matchesQuery } from "./workspace-data";

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-400">
      {children}
    </p>
  );
}

function EmptyRailState({ children }: { children: ReactNode }) {
  return <div className="px-1 py-2 text-sm leading-6 text-slate-500">{children}</div>;
}

function RailActionButton({
  children,
  onClick,
}: {
  children: React.ReactNode;
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

export default function Sidebar() {
  const {
    accessByScope,
    hasExecutionAccess,
    hasInspectionAccess,
    sessions,
    currentSessionId,
    refreshSessions,
    createSession,
    selectSession,
    deleteSession,
    renameSession,
    isStreaming,
    sessionListStatus,
    sessionListError,
  } = useApp();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [query, setQuery] = useState("");
  const trimmedQuery = query.trim();
  const sessionMutationLocked = isStreaming || !hasExecutionAccess;
  const sessionSelectionLocked = !hasInspectionAccess;

  const filteredSessions = sessions.filter((session) =>
    matchesQuery(query, session.title)
  );
  const sessionEmptyMessage =
    !hasInspectionAccess
      ? "Inspection access is required to browse saved sessions."
      : sessions.length === 0
        ? "No sessions yet. Start a new chat session to see it here."
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
    setEditingId(null);
    await createSession();
  };

  const handleSelect = async (id: string) => {
    if (sessionSelectionLocked) return;
    await selectSession(id);
    setEditingId(null);
  };

  const startEdit = (id: string, title: string, event: MouseEvent<HTMLButtonElement>) => {
    if (sessionMutationLocked) return;
    event.stopPropagation();
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

  const handleDelete = async (id: string, event: MouseEvent<HTMLButtonElement>) => {
    if (sessionMutationLocked) return;
    event.stopPropagation();
    if (confirm("Delete this session?")) {
      await deleteSession(id);
    }
  };

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] px-2.5 py-3">
        <button
          type="button"
          onClick={handleCreate}
          disabled={sessionMutationLocked}
          title={!hasExecutionAccess ? accessByScope.execution.detail : undefined}
          className="flex w-full items-center justify-center gap-2 rounded-[12px] bg-[var(--apex-accent)] px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--apex-accent-strong)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Plus size={15} />
          New Chat
        </button>

        <div className="relative mt-2.5">
          <Search
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sessions"
            className="w-full rounded-[11px] border border-[var(--shell-border)] bg-white px-8 py-1.5 text-[13px] text-slate-700 outline-none placeholder:text-slate-400 focus:border-[var(--apex-accent)]"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3 pt-3">
        <div className="flex items-center justify-between">
          <SectionLabel>Recent Sessions</SectionLabel>
          <span className="text-[10px] text-slate-400">
            {filteredSessions.length === 0 ? "Empty" : `${filteredSessions.length} items`}
          </span>
        </div>

        <div className="mt-2">
          {sessionMutationLocked || sessionSelectionLocked ? (
            <div className="mt-2 rounded-[12px] border border-[rgba(226,232,240,0.95)] bg-white/70 px-3 py-2 text-[11px] leading-5 text-slate-500">
              {!hasInspectionAccess
                ? accessByScope.inspection.detail
                : !hasExecutionAccess
                  ? accessByScope.execution.detail
                  : "Session switching is locked while the current response is in progress."}
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
              <div className="space-y-1">
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
                      "group border-b border-[rgba(211,219,210,0.8)] border-l-2 px-1 py-2 transition-colors last:border-b-0",
                      session.id === currentSessionId
                        ? "border-l-[var(--apex-accent)] bg-transparent"
                        : "border-l-transparent bg-transparent hover:bg-white/35"
                    )}
                  >
                    {editingId === session.id ? (
                      <div
                        className="flex items-center gap-2"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          value={editTitle}
                          onChange={(event) => setEditTitle(event.target.value)}
                          autoFocus
                          className="flex-1 rounded-[10px] border border-[var(--shell-border)] bg-white px-2 py-1 text-sm outline-none focus:border-[var(--apex-accent)]"
                        />
                        <button
                          type="button"
                          onClick={() => void confirmEdit(session.id)}
                          className="rounded-[10px] p-1 text-[var(--apex-accent-strong)] hover:bg-[var(--apex-accent-soft)]"
                        >
                          <Check size={15} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          className="rounded-[10px] p-1 text-slate-400 hover:bg-white"
                        >
                          <X size={15} />
                        </button>
                      </div>
                    ) : (
                      <div
                        role="button"
                        tabIndex={sessionSelectionLocked ? -1 : 0}
                        aria-disabled={sessionSelectionLocked}
                        onClick={() => void handleSelect(session.id)}
                        onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
                          if (sessionSelectionLocked) {
                            return;
                          }
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            void handleSelect(session.id);
                          }
                        }}
                        className="w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--apex-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-transparent aria-disabled:cursor-not-allowed aria-disabled:opacity-60"
                      >
                        <div className="flex items-start justify-between gap-1.5">
                          <div className="min-w-0">
                            <p className="truncate text-[13px] font-medium leading-5 text-slate-700">
                              {session.title}
                            </p>
                            <p className="mt-0.5 text-[10px] leading-4 text-slate-400">
                              {formatRelativeTime(session.updated_at)}
                            </p>
                          </div>

                          <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                            <button
                              type="button"
                              onClick={(event) => startEdit(session.id, session.title, event)}
                              disabled={sessionMutationLocked}
                              className="rounded-[8px] p-0.5 text-slate-400 hover:bg-white hover:text-slate-700 disabled:cursor-not-allowed"
                            >
                              <Edit2 size={12} />
                            </button>
                            <button
                              type="button"
                              onClick={(event) => void handleDelete(session.id, event)}
                              disabled={sessionMutationLocked}
                              className="rounded-[8px] p-0.5 text-slate-400 hover:bg-white hover:text-rose-600 disabled:cursor-not-allowed"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
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
    </aside>
  );
}
