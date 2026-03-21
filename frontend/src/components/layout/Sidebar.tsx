"use client";

import { useState } from "react";
import {
  BookOpen,
  Check,
  Edit2,
  FlaskConical,
  MessageSquare,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  Wrench,
  X,
  Zap,
  ZapOff,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { cn, formatTime } from "@/lib/utils";

const quickStartItems: Array<{
  label: string;
  description: string;
  icon: typeof FlaskConical;
}> = [
  { label: "RNA-seq DE", description: "Differential expression", icon: FlaskConical },
  { label: "Evidence Review", description: "Source synthesis", icon: BookOpen },
  { label: "Compliance", description: "Safety and readiness", icon: ShieldCheck },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
      {children}
    </p>
  );
}

export default function Sidebar() {
  const {
    sessions,
    currentSessionId,
    createSession,
    selectSession,
    deleteSession,
    renameSession,
    compressSession,
    isStreaming,
    ragMode,
    setRagMode,
  } = useApp();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [compressing, setCompressing] = useState(false);
  const [query, setQuery] = useState("");

  const filteredSessions = sessions.filter((session) =>
    session.title.toLowerCase().includes(query.trim().toLowerCase())
  );

  const handleCreate = async () => {
    await createSession();
  };

  const handleSelect = async (id: string) => {
    if (isStreaming) return;
    await selectSession(id);
    setEditingId(null);
  };

  const startEdit = (id: string, title: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(id);
    setEditTitle(title);
  };

  const confirmEdit = async (id: string) => {
    if (editTitle.trim()) {
      await renameSession(id, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm("Delete this session?")) {
      await deleteSession(id);
    }
  };

  const handleCompress = async () => {
    if (!currentSessionId || compressing) return;
    if (
      !confirm(
        "Compress the oldest 50% of messages? This will archive them and generate a summary."
      )
    ) {
      return;
    }

    setCompressing(true);
    try {
      await compressSession();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Compression failed");
    } finally {
      setCompressing(false);
    }
  };

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] p-3">
        <button
          onClick={handleCreate}
          className="flex w-full items-center justify-center gap-2 rounded-[12px] bg-[var(--apex-accent)] px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--apex-accent-strong)]"
        >
          <Plus size={16} />
          New
        </button>

        <div className="relative mt-3">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions"
            className="w-full rounded-[12px] border border-[var(--shell-border)] bg-white px-9 py-2 text-sm text-slate-700 outline-none placeholder:text-slate-400 focus:border-[var(--apex-accent)]"
          />
        </div>
      </div>

      <div className="px-3 pt-3">
        <div className="mb-2">
          <SectionLabel>Quick Start</SectionLabel>
        </div>
        <div className="space-y-1">
          {quickStartItems.map((item) => {
            const Icon = item.icon;

            return (
              <div
                key={item.label}
                className="flex items-center gap-2 rounded-[12px] px-2 py-2 text-left text-sm text-slate-600"
              >
                <Icon size={14} className="text-[var(--apex-accent)]" />
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-700">{item.label}</p>
                  <p className="truncate text-[11px] text-slate-400">{item.description}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 pt-4">
        <div className="flex items-center justify-between">
          <SectionLabel>Recent</SectionLabel>
          <span className="text-[10px] text-slate-400">
            {filteredSessions.length === 0 ? "Empty" : `${filteredSessions.length} items`}
          </span>
        </div>

        {filteredSessions.length === 0 ? (
          <div className="rounded-[14px] border border-dashed border-[var(--shell-border-strong)] bg-white/80 px-3 py-4 text-sm leading-6 text-slate-500">
            No sessions match this view yet.
          </div>
        ) : (
          <div className="space-y-1.5">
            {filteredSessions.map((session) => (
              <div
                key={session.id}
                onClick={() => handleSelect(session.id)}
                className={cn(
                  "group cursor-pointer rounded-[14px] border px-3 py-2.5 transition-colors",
                  session.id === currentSessionId
                    ? "border-[rgba(35,130,83,0.16)] bg-[var(--apex-accent-soft)]"
                    : "border-transparent bg-white/70 hover:border-[var(--shell-border)] hover:bg-white"
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
                      onClick={() => confirmEdit(session.id)}
                      className="rounded-full p-1.5 text-[var(--apex-accent)] hover:bg-emerald-50"
                    >
                      <Check size={12} />
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="rounded-full p-1.5 text-slate-400 hover:text-slate-600"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-start gap-2.5">
                    <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[10px] bg-white text-slate-500">
                      <MessageSquare size={14} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-slate-700">
                            {session.title}
                          </p>
                          <p className="mt-1 text-[11px] text-slate-400">
                            {formatTime(session.updated_at)}
                          </p>
                        </div>

                        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                          <button
                            onClick={(e) => startEdit(session.id, session.title, e)}
                            className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                            title="Rename session"
                          >
                            <Edit2 size={11} />
                          </button>
                          <button
                            onClick={(e) => handleDelete(session.id, e)}
                            className="rounded-full p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500"
                            title="Delete session"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-[var(--shell-border)] px-3 py-3">
        <div className="space-y-2">
          <button
            onClick={() => setRagMode(!ragMode)}
            className={cn(
              "flex w-full items-center gap-2 rounded-[12px] border px-3 py-2 text-sm font-medium transition-colors",
              ragMode
                ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]"
                : "border-[var(--shell-border)] bg-white text-slate-600 hover:bg-[var(--panel-soft)]"
            )}
          >
            {ragMode ? <Zap size={14} /> : <ZapOff size={14} />}
            {ragMode ? "RAG enabled" : "RAG disabled"}
          </button>

          {currentSessionId && (
            <button
              onClick={handleCompress}
              disabled={compressing || isStreaming}
              className="flex w-full items-center gap-2 rounded-[12px] border border-[var(--shell-border)] bg-white px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Wrench size={14} />
              {compressing ? "Compressing…" : "Compress history"}
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
