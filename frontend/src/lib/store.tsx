"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import * as api from "./api";
import { uid } from "./utils";
import type { Message, RetrievalResult, Session, ToolCall } from "./types";

// ────────────────────────────────────────────────────────────────
// Context shape
// ────────────────────────────────────────────────────────────────

interface AppContextValue {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  ragMode: boolean;

  // Actions
  refreshSessions: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
  setRagMode: (enabled: boolean) => Promise<void>;
  compressSession: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}

// ────────────────────────────────────────────────────────────────
// Provider
// ────────────────────────────────────────────────────────────────

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [ragMode, setRagModeState] = useState(false);

  // Ref to current streaming message ID (avoids stale closure issues)
  const streamingIdRef = useRef<string | null>(null);

  // ── Bootstrap ────────────────────────────────────────────────

  useEffect(() => {
    (async () => {
      try {
        const [sessionList, ragCfg] = await Promise.all([
          api.listSessions(),
          api.getRagMode(),
        ]);
        setSessions(sessionList);
        setRagModeState(ragCfg.rag_mode);
        if (sessionList.length > 0) {
          await _loadSession(sessionList[0].id, setMessages, setCurrentSessionId);
        }
      } catch {
        // Backend not ready yet — that's fine
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Session helpers ──────────────────────────────────────────

  const refreshSessions = useCallback(async () => {
    const list = await api.listSessions();
    setSessions(list);
  }, []);

  const createSession = useCallback(async () => {
    const session = await api.createSession();
    setSessions((prev) => [session, ...prev]);
    setCurrentSessionId(session.id);
    setMessages([]);
  }, []);

  const selectSession = useCallback(async (id: string) => {
    if (id === currentSessionId) return;
    await _loadSession(id, setMessages, setCurrentSessionId);
  }, [currentSessionId]);

  const deleteSession = useCallback(
    async (id: string) => {
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === currentSessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
    },
    [currentSessionId]
  );

  const renameSession = useCallback(async (id: string, title: string) => {
    await api.renameSession(id, title);
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title } : s))
    );
  }, []);

  // ── RAG mode ─────────────────────────────────────────────────

  const setRagMode = useCallback(async (enabled: boolean) => {
    await api.setRagMode(enabled);
    setRagModeState(enabled);
  }, []);

  // ── Compression ──────────────────────────────────────────────

  const compressSession = useCallback(async () => {
    if (!currentSessionId) return;
    await api.compressSession(currentSessionId);
    // Reload messages after compression
    const history = await api.getHistory(currentSessionId);
    const msgs = _historyToMessages(history as RawMessage[]);
    setMessages(msgs);
    await refreshSessions();
  }, [currentSessionId, refreshSessions]);

  // ── Send message ─────────────────────────────────────────────

  const sendMessage = useCallback(
    async (content: string) => {
      if (isStreaming) return;

      // Auto-create session if none is selected
      let sessionId = currentSessionId;
      if (!sessionId) {
        const session = await api.createSession();
        setSessions((prev) => [session, ...prev]);
        setCurrentSessionId(session.id);
        sessionId = session.id;
      }

      // Add user message + streaming placeholder
      const userMsg: Message = { id: uid(), role: "user", content };
      const assistantMsg: Message = {
        id: uid(),
        role: "assistant",
        content: "",
        isStreaming: true,
        tool_calls: [],
      };
      streamingIdRef.current = assistantMsg.id;

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      await api.streamChat(content, sessionId, {
        onRetrieval: (query, results) => {
          const id = streamingIdRef.current;
          if (!id) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? { ...m, retrievals: results as RetrievalResult[] }
                : m
            )
          );
        },

        onToken: (token) => {
          const id = streamingIdRef.current;
          if (!id) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id ? { ...m, content: m.content + token } : m
            )
          );
        },

        onToolStart: (tool, input, runId) => {
          const id = streamingIdRef.current;
          if (!id) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? { ...m, pendingTool: { tool, input, runId } }
                : m
            )
          );
        },

        onToolEnd: (tool, output, runId) => {
          const id = streamingIdRef.current;
          if (!id) return;
          const call: ToolCall = {
            tool,
            input: "",   // filled in below from pendingTool
            output,
          };
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== id) return m;
              const pending = m.pendingTool?.runId === runId ? m.pendingTool : null;
              const tc: ToolCall = {
                tool: pending?.tool ?? tool,
                input: pending?.input ?? "",
                output,
              };
              return {
                ...m,
                tool_calls: [...(m.tool_calls ?? []), tc],
                pendingTool: undefined,
              };
            })
          );
        },

        onNewResponse: () => {
          // Capture old ID before updating ref so the map can still find it
          const oldId = streamingIdRef.current;
          const newMsg: Message = {
            id: uid(),
            role: "assistant",
            content: "",
            isStreaming: true,
            tool_calls: [],
          };
          // Update ref synchronously so subsequent onToken calls use the new ID
          streamingIdRef.current = newMsg.id;
          setMessages((prev) => [
            ...prev.map((m) =>
              m.id === oldId ? { ...m, isStreaming: false } : m
            ),
            newMsg,
          ]);
        },

        onDone: () => {
          const id = streamingIdRef.current;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id ? { ...m, isStreaming: false } : m
            )
          );
          streamingIdRef.current = null;
          setIsStreaming(false);
          refreshSessions();
        },

        onTitle: (title) => {
          setSessions((prev) =>
            prev.map((s) =>
              s.id === sessionId ? { ...s, title } : s
            )
          );
        },

        onError: (error) => {
          const id = streamingIdRef.current;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? {
                    ...m,
                    content:
                      (m.content ? m.content + "\n\n" : "") +
                      `⚠️ Error: ${error}`,
                    isStreaming: false,
                  }
                : m
            )
          );
          streamingIdRef.current = null;
          setIsStreaming(false);
        },
      });
    },
    [currentSessionId, isStreaming, refreshSessions]
  );

  return (
    <AppContext.Provider
      value={{
        sessions,
        currentSessionId,
        messages,
        isStreaming,
        ragMode,
        refreshSessions,
        createSession,
        selectSession,
        deleteSession,
        renameSession,
        sendMessage,
        setRagMode,
        compressSession,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

// ────────────────────────────────────────────────────────────────
// Internal helpers
// ────────────────────────────────────────────────────────────────

interface RawMessage {
  role: string;
  content: string;
  tool_calls?: ToolCall[];
}

function _historyToMessages(raw: RawMessage[]): Message[] {
  return raw
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: uid(),
      role: m.role as "user" | "assistant",
      content: m.content ?? "",
      tool_calls: m.tool_calls ?? [],
    }));
}

async function _loadSession(
  id: string,
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>
) {
  setCurrentSessionId(id);
  try {
    const history = await api.getHistory(id);
    setMessages(_historyToMessages(history as RawMessage[]));
  } catch {
    setMessages([]);
  }
}
