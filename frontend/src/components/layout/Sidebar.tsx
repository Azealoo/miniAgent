"use client";

import { useState } from "react";
import {
  MessageSquare,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  Wrench,
  Zap,
  ZapOff,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { cn, formatTime } from "@/lib/utils";

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
    if (editTitle.trim()) await renameSession(id, editTitle.trim());
    setEditingId(null);
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm("Delete this session?")) await deleteSession(id);
  };

  const handleCompress = async () => {
    if (!currentSessionId || compressing) return;
    if (!confirm("Compress the oldest 50% of messages? This will archive them and generate a summary.")) return;
    setCompressing(true);
    try {
      await compressSession();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Compression failed");
    } finally {
      setCompressing(false);
    }
  };

  const handleRagToggle = async () => {
    await setRagMode(!ragMode);
  };

  return (
    <div className="flex flex-col h-full bg-white border-r border-gray-200">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-100">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Sessions
        </span>
        <button
          onClick={handleCreate}
          className="p-1 rounded-md hover:bg-gray-100 text-gray-500 hover:text-[#002FA7] transition-colors"
          title="New chat"
        >
          <Plus size={15} />
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-1">
        {sessions.length === 0 && (
          <p className="text-xs text-gray-400 text-center mt-6 px-4">
            No sessions yet.
            <br />
            Click + to start.
          </p>
        )}
        {sessions.map((s) => (
          <div
            key={s.id}
            onClick={() => handleSelect(s.id)}
            className={cn(
              "group flex items-center gap-2 px-3 py-2 cursor-pointer rounded-md mx-1 my-0.5 transition-colors",
              s.id === currentSessionId
                ? "bg-[#002FA7]/10 text-[#002FA7]"
                : "hover:bg-gray-100 text-gray-700"
            )}
          >
            <MessageSquare size={13} className="flex-shrink-0 opacity-60" />

            {editingId === s.id ? (
              <div
                className="flex-1 flex items-center gap-1"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  autoFocus
                  className="flex-1 text-xs border border-gray-300 rounded px-1.5 py-0.5 outline-none focus:border-[#002FA7]"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") confirmEdit(s.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
                <button
                  onClick={() => confirmEdit(s.id)}
                  className="text-green-600 hover:text-green-700"
                >
                  <Check size={12} />
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <X size={12} />
                </button>
              </div>
            ) : (
              <>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{s.title}</p>
                  <p className="text-[10px] text-gray-400">
                    {formatTime(s.updated_at)}
                  </p>
                </div>
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => startEdit(s.id, s.title, e)}
                    className="p-0.5 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600"
                  >
                    <Edit2 size={11} />
                  </button>
                  <button
                    onClick={(e) => handleDelete(s.id, e)}
                    className="p-0.5 rounded hover:bg-red-100 text-gray-400 hover:text-red-500"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Footer actions */}
      <div className="border-t border-gray-100 px-3 py-2 space-y-2">
        {/* RAG toggle */}
        <button
          onClick={handleRagToggle}
          className={cn(
            "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors",
            ragMode
              ? "bg-purple-100 text-purple-700 hover:bg-purple-200"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          )}
          title={ragMode ? "RAG mode on — click to disable" : "RAG mode off — click to enable"}
        >
          {ragMode ? <Zap size={13} /> : <ZapOff size={13} />}
          RAG {ragMode ? "On" : "Off"}
        </button>

        {/* Compress */}
        {currentSessionId && (
          <button
            onClick={handleCompress}
            disabled={compressing || isStreaming}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title="Compress oldest 50% of messages"
          >
            <Wrench size={13} />
            {compressing ? "Compressing…" : "Compress history"}
          </button>
        )}
      </div>
    </div>
  );
}
