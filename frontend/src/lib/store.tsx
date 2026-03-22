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
import { getLatestSelectedWorkflow } from "./session-status";
import { uid } from "./utils";
import type {
  Message,
  RetrievalResult,
  Session,
  ToolCall,
  WorkflowStreamEvent,
} from "./types";

// ────────────────────────────────────────────────────────────────
// Context shape
// ────────────────────────────────────────────────────────────────

interface AppContextValue {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  ragMode: boolean;
  selectedWorkflow: string | null;
  draftMessage: string;
  draftRevision: number;
  inspectorTab: "files" | "sources" | "memory" | "skills" | "usage";
  inspectorPreviewPath: string | null;

  // Actions
  refreshSessions: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string, context?: api.ChatRequestContext) => Promise<void>;
  selectWorkflow: (workflowId: string | null) => void;
  primeDraftMessage: (text: string) => void;
  clearDraftMessage: () => void;
  setInspectorTab: (
    tab: "files" | "sources" | "memory" | "skills" | "usage"
  ) => void;
  openInspectorPath: (path: string) => void;
  clearInspectorPath: () => void;
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
  const [selectedWorkflow, setSelectedWorkflow] = useState<string | null>(null);
  const [draftMessage, setDraftMessage] = useState("");
  const [draftRevision, setDraftRevision] = useState(0);
  const [inspectorTab, setInspectorTabState] = useState<
    "files" | "sources" | "memory" | "skills" | "usage"
  >("files");
  const [inspectorPreviewPath, setInspectorPreviewPath] = useState<string | null>(null);

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
          await _loadSession(
            sessionList[0].id,
            setMessages,
            setCurrentSessionId,
            setSelectedWorkflow
          );
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
    setSelectedWorkflow(null);
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
    setInspectorPreviewPath(null);
    setInspectorTabState("files");
  }, []);

  const selectSession = useCallback(async (id: string) => {
    if (id === currentSessionId) return;
    await _loadSession(id, setMessages, setCurrentSessionId, setSelectedWorkflow);
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
    setInspectorPreviewPath(null);
    setInspectorTabState("files");
  }, [currentSessionId]);

  const deleteSession = useCallback(
    async (id: string) => {
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === currentSessionId) {
        setCurrentSessionId(null);
        setMessages([]);
        setSelectedWorkflow(null);
        setDraftMessage("");
        setDraftRevision((prev) => prev + 1);
        setInspectorPreviewPath(null);
        setInspectorTabState("files");
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

  const selectWorkflow = useCallback((workflowId: string | null) => {
    setSelectedWorkflow(workflowId);
  }, []);

  const primeDraftMessage = useCallback((text: string) => {
    setDraftMessage(text);
    setDraftRevision((prev) => prev + 1);
  }, []);

  const clearDraftMessage = useCallback(() => {
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
  }, []);

  const setInspectorTab = useCallback(
    (tab: "files" | "sources" | "memory" | "skills" | "usage") => {
      setInspectorTabState(tab);
    },
    []
  );

  const openInspectorPath = useCallback((path: string) => {
    setInspectorPreviewPath(path);
    setInspectorTabState("files");
  }, []);

  const clearInspectorPath = useCallback(() => {
    setInspectorPreviewPath(null);
  }, []);

  // ── Compression ──────────────────────────────────────────────

  const compressSession = useCallback(async () => {
    if (!currentSessionId) return;
    await api.compressSession(currentSessionId);
    // Reload messages after compression
    const history = await api.getHistory(currentSessionId);
    const msgs = _historyToMessages(history as RawMessage[]);
    setMessages(msgs);
    setSelectedWorkflow(getLatestSelectedWorkflow(msgs));
    await refreshSessions();
  }, [currentSessionId, refreshSessions]);

  // ── Send message ─────────────────────────────────────────────

  const sendMessage = useCallback(
    async (content: string, context?: api.ChatRequestContext) => {
      if (isStreaming) return;
      const requestedWorkflow =
        context && "selectedWorkflow" in context
          ? context.selectedWorkflow ?? null
          : selectedWorkflow;

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
        workflow_events: [],
      };
      streamingIdRef.current = assistantMsg.id;

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      setSelectedWorkflow(requestedWorkflow);
      setDraftMessage("");
      setDraftRevision((prev) => prev + 1);

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

        onToolStart: (tool, input, runId, requestId) => {
          const id = streamingIdRef.current;
          if (!id) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? {
                    ...m,
                    request_id: m.request_id ?? requestId,
                    pendingTool: { tool, input, runId },
                  }
                : m
            )
          );
        },

        onToolEnd: (tool, output, runId, result, requestId) => {
          const id = streamingIdRef.current;
          if (!id) return;
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== id) return m;
              const pending = m.pendingTool?.runId === runId ? m.pendingTool : null;
              const tc: ToolCall = {
                tool: pending?.tool ?? tool,
                input: pending?.input ?? "",
                output,
                run_id: runId,
                result,
              };
              return {
                ...m,
                request_id: m.request_id ?? requestId,
                tool_calls: [...(m.tool_calls ?? []), tc],
                pendingTool: undefined,
              };
            })
          );
        },

        onWorkflowEvent: (event) => {
          const id = streamingIdRef.current;
          if (!id) return;
          if (
            event.type === "workflow_start" ||
            event.type === "workflow_blocked" ||
            event.type === "workflow_done"
          ) {
            setSelectedWorkflow(event.workflow_id);
          }
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? {
                    ...m,
                    request_id: m.request_id ?? event.request_id,
                    workflow_events: [...(m.workflow_events ?? []), event],
                  }
                : m
            )
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
            workflow_events: [],
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

        onDone: (_content, requestId) => {
          const id = streamingIdRef.current;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? { ...m, request_id: m.request_id ?? requestId, isStreaming: false }
                : m
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

        onError: (error, requestId) => {
          const id = streamingIdRef.current;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? {
                    ...m,
                    request_id: m.request_id ?? requestId,
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
      }, {
        attachedIdentifiers: context?.attachedIdentifiers,
        selectedWorkflow: requestedWorkflow,
      });
    },
    [currentSessionId, isStreaming, refreshSessions, selectedWorkflow]
  );

  return (
    <AppContext.Provider
      value={{
        sessions,
        currentSessionId,
        messages,
        isStreaming,
        ragMode,
        selectedWorkflow,
        draftMessage,
        draftRevision,
        inspectorTab,
        inspectorPreviewPath,
        refreshSessions,
        createSession,
        selectSession,
        deleteSession,
        renameSession,
        sendMessage,
        selectWorkflow,
        primeDraftMessage,
        clearDraftMessage,
        setInspectorTab,
        openInspectorPath,
        clearInspectorPath,
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
  request_id?: string;
  tool_calls?: ToolCall[];
  workflow_events?: WorkflowStreamEvent[];
}

function _historyToMessages(raw: RawMessage[]): Message[] {
  return raw
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: uid(),
      role: m.role as "user" | "assistant",
      content: m.content ?? "",
      request_id: m.request_id,
      tool_calls: m.tool_calls ?? [],
      workflow_events: m.workflow_events ?? [],
    }));
}

async function _loadSession(
  id: string,
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>,
  setSelectedWorkflow: React.Dispatch<React.SetStateAction<string | null>>
) {
  setCurrentSessionId(id);
  try {
    const history = await api.getHistory(id);
    const messages = _historyToMessages(history as RawMessage[]);
    setMessages(messages);
    setSelectedWorkflow(getLatestSelectedWorkflow(messages));
  } catch {
    setMessages([]);
    setSelectedWorkflow(null);
  }
}
