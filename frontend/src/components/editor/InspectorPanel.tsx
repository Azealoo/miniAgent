"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { Brain, BookOpen, Save, RefreshCw, ChevronRight, FileJson, Wrench, User, Bot } from "lucide-react";
import { cn } from "@/lib/utils";
import { readFile, saveFile, listSkills, getSessionTokens, getHistory } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Skill, TokenStats } from "@/lib/types";

// Monaco editor — SSR disabled (it uses browser APIs)
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-sm text-gray-400">
      Loading editor…
    </div>
  ),
});

type Tab = "memory" | "skills" | "raw";

interface RawToolCall {
  tool: string;
  input: string;
  output: string;
}

interface RawMsg {
  role: string;
  content: string;
  tool_calls?: RawToolCall[];
}

export default function InspectorPanel() {
  const { currentSessionId, messages } = useApp();

  const [tab, setTab] = useState<Tab>("memory");
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tokens, setTokens] = useState<TokenStats | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [rawMessages, setRawMessages] = useState<RawMsg[]>([]);
  const [rawLoading, setRawLoading] = useState(false);

  const isDirty = content !== savedContent;

  // Load memory.md when memory tab is opened
  useEffect(() => {
    if (tab === "memory") {
      loadMemory();
    } else if (tab === "skills") {
      listSkills().then(setSkills).catch(() => {});
    } else if (tab === "raw") {
      loadRawMessages();
    }
  }, [tab]);

  // Refresh raw messages when session or messages change (e.g. after send)
  useEffect(() => {
    if (tab === "raw" && currentSessionId) loadRawMessages();
  }, [currentSessionId, messages]);

  // Load token stats for current session
  useEffect(() => {
    if (!currentSessionId) {
      setTokens(null);
      return;
    }
    getSessionTokens(currentSessionId)
      .then(setTokens)
      .catch(() => setTokens(null));
  }, [currentSessionId]);

  const loadMemory = async () => {
    setLoading(true);
    try {
      const res = await readFile("memory/MEMORY.md");
      setContent(res.content);
      setSavedContent(res.content);
      setOpenPath("memory/MEMORY.md");
    } catch {
      setContent("# Could not load MEMORY.md");
    } finally {
      setLoading(false);
    }
  };

  const loadSkill = async (path: string) => {
    setLoading(true);
    try {
      const res = await readFile(path);
      setContent(res.content);
      setSavedContent(res.content);
      setOpenPath(path);
    } catch {
      setContent("# Could not load skill file");
    } finally {
      setLoading(false);
    }
  };

  const loadRawMessages = async () => {
    if (!currentSessionId) {
      setRawMessages([]);
      return;
    }
    setRawLoading(true);
    try {
      const history = await getHistory(currentSessionId);
      setRawMessages(history as RawMsg[]);
    } catch {
      setRawMessages([]);
    } finally {
      setRawLoading(false);
    }
  };

  const handleSave = async () => {
    if (!openPath || !isDirty) return;
    setSaving(true);
    setSaveMsg("");
    try {
      await saveFile(openPath, content);
      setSavedContent(content);
      setSaveMsg("Saved");
      setTimeout(() => setSaveMsg(""), 2000);
    } catch (e) {
      setSaveMsg("Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white border-l border-gray-200">
      {/* Tab bar */}
      <div className="flex items-center border-b border-gray-200 px-2 pt-1.5 gap-1">
        <TabBtn
          active={tab === "memory"}
          icon={<Brain size={13} />}
          label="Memory"
          onClick={() => setTab("memory")}
        />
        <TabBtn
          active={tab === "skills"}
          icon={<BookOpen size={13} />}
          label="Skills"
          onClick={() => setTab("skills")}
        />
        <TabBtn
          active={tab === "raw"}
          icon={<FileJson size={13} />}
          label="Raw"
          onClick={() => setTab("raw")}
        />
      </div>

      {/* Token stats bar */}
      {tokens && (
        <div className="px-3 py-1.5 bg-gray-50 border-b border-gray-100 flex items-center gap-3">
          <span className="text-[10px] text-gray-400">
            System: <span className="font-medium text-gray-600">{tokens.system_tokens.toLocaleString()}</span>
          </span>
          <span className="text-[10px] text-gray-400">
            Msgs: <span className="font-medium text-gray-600">{tokens.message_tokens.toLocaleString()}</span>
          </span>
          <span className="text-[10px] text-gray-400">
            Total: <span className="font-semibold text-[#002FA7]">{tokens.total_tokens.toLocaleString()}</span>
          </span>
        </div>
      )}

      {/* Skills list (visible when tab=skills and no file open) */}
      {tab === "skills" && (
        <div className="border-b border-gray-100 max-h-40 overflow-y-auto">
          {skills.length === 0 ? (
            <p className="text-xs text-gray-400 p-3">No skills found in skills/</p>
          ) : (
            skills.map((s) => (
              <button
                key={s.path}
                onClick={() => loadSkill(s.path)}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors",
                  openPath === s.path && "bg-[#002FA7]/5 text-[#002FA7]"
                )}
              >
                <BookOpen size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-700 truncate">
                  {s.name}
                </span>
                <ChevronRight size={11} className="ml-auto text-gray-300" />
              </button>
            ))
          )}
        </div>
      )}

      {/* Editor toolbar */}
      {openPath && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-gray-100 bg-gray-50">
          <span className="text-[11px] font-mono text-gray-500 truncate">
            {openPath}
          </span>
          <div className="flex items-center gap-2">
            {saveMsg && (
              <span
                className={cn(
                  "text-[10px]",
                  saveMsg === "Saved" ? "text-green-600" : "text-red-500"
                )}
              >
                {saveMsg}
              </span>
            )}
            <button
              onClick={tab === "memory" ? loadMemory : () => openPath && loadSkill(openPath)}
              className="p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors"
              title="Reload from disk"
            >
              <RefreshCw size={12} />
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || saving}
              className={cn(
                "flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium transition-colors",
                isDirty && !saving
                  ? "bg-[#002FA7] text-white hover:bg-[#001F7A]"
                  : "bg-gray-200 text-gray-400 cursor-not-allowed"
              )}
            >
              <Save size={11} />
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}

      {/* Raw Messages panel */}
      {tab === "raw" && (
        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
          {rawLoading ? (
            <div className="flex items-center justify-center h-full text-sm text-gray-400 pt-10">
              Loading…
            </div>
          ) : !currentSessionId ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-6 pt-10">
              <FileJson size={28} className="text-gray-200 mb-3" />
              <p className="text-xs text-gray-400">No session selected</p>
            </div>
          ) : rawMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-6 pt-10">
              <FileJson size={28} className="text-gray-200 mb-3" />
              <p className="text-xs text-gray-400">No messages yet</p>
            </div>
          ) : (
            rawMessages.map((msg, i) => <RawMessageCard key={i} msg={msg} />)
          )}
        </div>
      )}

      {/* Monaco Editor (memory / skills) */}
      {tab !== "raw" && (
        <div className="flex-1 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center h-full text-sm text-gray-400">
              Loading…
            </div>
          ) : openPath ? (
            <MonacoEditor
              height="100%"
              language="markdown"
              value={content}
              theme="vs"
              onChange={(val) => setContent(val ?? "")}
              options={{
                minimap: { enabled: false },
                wordWrap: "on",
                fontSize: 12,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
                overviewRulerLanes: 0,
                padding: { top: 8, bottom: 8 },
                fontFamily: '"SF Mono", "Fira Code", Consolas, monospace',
              }}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <Brain size={28} className="text-gray-200 mb-3" />
              <p className="text-xs text-gray-400">
                {tab === "memory"
                  ? "Loading MEMORY.md…"
                  : "Select a skill to edit"}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TabBtn({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t-md transition-colors border-b-2",
        active
          ? "text-[#002FA7] border-[#002FA7] bg-[#002FA7]/5"
          : "text-gray-500 border-transparent hover:text-gray-700 hover:bg-gray-100"
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function RawMessageCard({ msg }: { msg: RawMsg }) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  return (
    <div
      className={cn(
        "rounded-lg border text-[11px] font-mono overflow-hidden",
        isUser
          ? "border-blue-200 bg-blue-50"
          : isSystem
            ? "border-amber-200 bg-amber-50"
            : "border-gray-200 bg-gray-50"
      )}
    >
      <div
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1.5 border-b",
          isUser
            ? "border-blue-200 bg-blue-100/60"
            : isSystem
              ? "border-amber-200 bg-amber-100/60"
              : "border-gray-200 bg-gray-100/60"
        )}
      >
        {isUser ? (
          <User size={11} className="text-blue-500 flex-shrink-0" />
        ) : isSystem ? (
          <Brain size={11} className="text-amber-600 flex-shrink-0" />
        ) : (
          <Bot size={11} className="text-gray-500 flex-shrink-0" />
        )}
        <span
          className={cn(
            "font-semibold uppercase tracking-wide text-[10px]",
            isUser ? "text-blue-600" : isSystem ? "text-amber-700" : "text-gray-600"
          )}
        >
          {msg.role}
        </span>
      </div>
      {msg.content && (
        <pre className="px-2.5 py-2 whitespace-pre-wrap break-words text-gray-700 leading-relaxed">
          {msg.content}
        </pre>
      )}
      {msg.tool_calls && msg.tool_calls.length > 0 && (
        <div className="border-t border-gray-200 divide-y divide-gray-100">
          {msg.tool_calls.map((tc, i) => (
            <div key={i} className="px-2.5 py-1.5">
              <button
                type="button"
                className="flex items-center gap-1.5 w-full text-left hover:opacity-75 transition-opacity"
                onClick={() =>
                  setExpanded((prev) => ({ ...prev, [i]: !prev[i] }))
                }
              >
                <Wrench size={10} className="text-orange-500 flex-shrink-0" />
                <span className="text-orange-600 font-semibold">{tc.tool}</span>
                <ChevronRight
                  size={10}
                  className={cn(
                    "ml-auto text-gray-400 transition-transform",
                    expanded[i] && "rotate-90"
                  )}
                />
              </button>
              {expanded[i] && (
                <div className="mt-1.5 space-y-1">
                  <div>
                    <span className="text-[9px] uppercase tracking-widest text-gray-400 font-semibold">
                      Input
                    </span>
                    <pre className="mt-0.5 p-1.5 bg-white border border-gray-200 rounded text-gray-600 whitespace-pre-wrap break-words text-[10px]">
                      {tc.input}
                    </pre>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase tracking-widest text-gray-400 font-semibold">
                      Output
                    </span>
                    <pre className="mt-0.5 p-1.5 bg-white border border-gray-200 rounded text-gray-600 whitespace-pre-wrap break-words text-[10px] max-h-32 overflow-y-auto">
                      {tc.output}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
