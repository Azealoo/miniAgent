"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ACCESS_SCOPES,
  clearAllBearerTokens,
  classifyAccessError,
  createCheckingAccessState,
  createGrantedAccessState,
  EMPTY_API_AUTH_STATE,
  hasScopeBearerToken,
  isAccessGranted,
  withScopeBearerToken,
} from "./access-control";
import * as api from "./api";
import { getLatestSelectedWorkflow } from "./session-status";
import { uid } from "./utils";
import type {
  AccessScope,
  AccessScopeState,
  Message,
  Session,
  SessionHistoryMessage,
  ToolCall,
  WorkspaceMode,
} from "./types";

// ────────────────────────────────────────────────────────────────
// Context shape
// ────────────────────────────────────────────────────────────────

interface AppContextValue {
  apiAuthState: api.ApiAuthState;
  accessByScope: Record<AccessScope, AccessScopeState>;
  hasInspectionAccess: boolean;
  hasExecutionAccess: boolean;
  hasAdminAccess: boolean;
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  isReferenceUploading: boolean;
  isSessionLoading: boolean;
  ragMode: boolean;
  canManageRagMode: boolean;
  workspaceMode: WorkspaceMode;
  selectedWorkflow: string | null;
  attachedIdentifiers: string[];
  draftMessage: string;
  draftRevision: number;
  inspectorTab: "files" | "sources" | "memory" | "skills" | "usage";
  inspectorPreviewPath: string | null;

  // Actions
  refreshSessions: () => Promise<void>;
  refreshAccessState: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string, context?: api.ChatRequestContext) => Promise<void>;
  setWorkspaceMode: (mode: WorkspaceMode) => void;
  selectWorkflow: (workflowId: string | null) => void;
  uploadAttachedReference: (file: File) => Promise<void>;
  addAttachedIdentifier: (identifier: string) => void;
  removeAttachedIdentifier: (identifier: string) => void;
  clearAttachedIdentifiers: () => void;
  primeDraftMessage: (text: string) => void;
  clearDraftMessage: () => void;
  setAccessToken: (scope: AccessScope, token: string) => void;
  clearAccessTokens: () => void;
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
  const [apiAuthState, setApiAuthState] = useState<api.ApiAuthState>({
    ...EMPTY_API_AUTH_STATE,
  });
  const [hasLoadedApiAuthState, setHasLoadedApiAuthState] = useState(false);
  const [accessByScope, setAccessByScope] = useState<
    Record<AccessScope, AccessScopeState>
  >(() => buildCheckingAccessStates(EMPTY_API_AUTH_STATE));
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isReferenceUploading, setIsReferenceUploading] = useState(false);
  const [isSessionLoading, setIsSessionLoading] = useState(true);
  const [ragMode, setRagModeState] = useState(false);
  const [canManageRagMode, setCanManageRagMode] = useState(false);
  const [workspaceMode, setWorkspaceModeState] = useState<WorkspaceMode>("sessions");
  const [selectedWorkflow, setSelectedWorkflow] = useState<string | null>(null);
  const [attachedIdentifiers, setAttachedIdentifiers] = useState<string[]>([]);
  const [draftMessage, setDraftMessage] = useState("");
  const [draftRevision, setDraftRevision] = useState(0);
  const [inspectorTab, setInspectorTabState] = useState<
    "files" | "sources" | "memory" | "skills" | "usage"
  >("files");
  const [inspectorPreviewPath, setInspectorPreviewPath] = useState<string | null>(null);

  // Ref to current streaming message ID (avoids stale closure issues)
  const streamingIdRef = useRef<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);
  const referenceUploadTokenRef = useRef(0);
  const apiAuthStateRef = useRef(apiAuthState);
  const accessRefreshIdRef = useRef(0);
  const hasInspectionAccess = isAccessGranted(accessByScope.inspection);
  const hasExecutionAccess = isAccessGranted(accessByScope.execution);
  const hasAdminAccess = isAccessGranted(accessByScope.admin);

  // ── Bootstrap ────────────────────────────────────────────────

  useEffect(() => {
    setHasLoadedApiAuthState(true);
  }, []);

  useEffect(() => {
    apiAuthStateRef.current = apiAuthState;
  }, [apiAuthState]);

  useEffect(() => {
    api.setApiAuthProvider(() => apiAuthStateRef.current);
    return () => {
      api.setApiAuthProvider(null);
    };
  }, []);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  const runAccessProbe = useCallback(async (showChecking: boolean) => {
    const requestId = accessRefreshIdRef.current + 1;
    accessRefreshIdRef.current = requestId;

    const currentAuthState = apiAuthStateRef.current;
    if (showChecking) {
      setAccessByScope(buildCheckingAccessStates(currentAuthState));
    }

    const entries = await Promise.all(
      ACCESS_SCOPES.map(async (scope) => {
        const hasToken = hasScopeBearerToken(currentAuthState, scope);

        try {
          const response = await api.probeAccess(scope);
          return [
            scope,
            createGrantedAccessState(
              scope,
              response.authorization_mode,
              hasToken
            ),
          ] as const;
        } catch (error) {
          return [scope, classifyAccessError(scope, error, hasToken)] as const;
        }
      })
    );

    if (accessRefreshIdRef.current !== requestId) {
      return;
    }

    setAccessByScope(buildAccessStateRecord(entries));
  }, []);

  const refreshAccessState = useCallback(async () => {
    await runAccessProbe(true);
  }, [runAccessProbe]);

  useEffect(() => {
    if (!hasLoadedApiAuthState) {
      return;
    }

    void refreshAccessState();
  }, [apiAuthState, hasLoadedApiAuthState, refreshAccessState]);

  const shouldPollAccessRecovery = ACCESS_SCOPES.some((scope) => {
    const status = accessByScope[scope].status;
    return (
      status === "checking" ||
      status === "unavailable" ||
      status === "server_misconfigured"
    );
  });

  useEffect(() => {
    if (!hasLoadedApiAuthState || typeof window === "undefined") {
      return;
    }

    // Re-probe access after outages or server restarts without flashing the UI
    // back into a blocking "checking" state.
    const handleBackgroundProbe = () => {
      if (!window.navigator.onLine) {
        return;
      }
      void runAccessProbe(false);
    };

    window.addEventListener("focus", handleBackgroundProbe);
    window.addEventListener("online", handleBackgroundProbe);

    const intervalId = shouldPollAccessRecovery
      ? window.setInterval(handleBackgroundProbe, 30_000)
      : null;

    return () => {
      window.removeEventListener("focus", handleBackgroundProbe);
      window.removeEventListener("online", handleBackgroundProbe);
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
    };
  }, [hasLoadedApiAuthState, runAccessProbe, shouldPollAccessRecovery]);

  useEffect(() => {
    if (!hasLoadedApiAuthState) {
      return;
    }

    const inspectionStatus = accessByScope.inspection.status;
    if (
      inspectionStatus === "granted" ||
      inspectionStatus === "checking" ||
      inspectionStatus === "unavailable"
    ) {
      return;
    }

    setSessions([]);
    setCurrentSessionId(null);
    setMessages([]);
    setSelectedWorkflow(null);
    setInspectorPreviewPath(null);
  }, [accessByScope.inspection.status, hasLoadedApiAuthState]);

  useEffect(() => {
    if (!hasLoadedApiAuthState) {
      return;
    }

    if (accessByScope.inspection.status === "checking") {
      setIsSessionLoading(true);
      return;
    }

    if (!hasInspectionAccess) {
      setIsSessionLoading(false);
      return;
    }

    let cancelled = false;

    const loadSessions = async () => {
      setIsSessionLoading(true);
      try {
        const sessionList = await api.listSessions();
        if (cancelled) {
          return;
        }

        setSessions(sessionList);
        const activeId = currentSessionIdRef.current;
        const nextSessionId =
          activeId && sessionList.some((session) => session.id === activeId)
            ? activeId
            : sessionList[0]?.id ?? null;

        if (!nextSessionId) {
          setCurrentSessionId(null);
          setMessages([]);
          setSelectedWorkflow(null);
          return;
        }

        await _loadSession(
          nextSessionId,
          setMessages,
          setCurrentSessionId,
          setSelectedWorkflow
        );
      } catch (error) {
        if (!cancelled) {
          setAccessByScope((current) => ({
            ...current,
            inspection: classifyAccessError(
              "inspection",
              error,
              hasScopeBearerToken(apiAuthStateRef.current, "inspection")
            ),
          }));
        }
      } finally {
        if (!cancelled) {
          setIsSessionLoading(false);
        }
      }
    };

    void loadSessions();

    return () => {
      cancelled = true;
    };
  }, [accessByScope.inspection.status, hasInspectionAccess, hasLoadedApiAuthState]);

  useEffect(() => {
    if (!hasLoadedApiAuthState || accessByScope.admin.status === "checking") {
      return;
    }

    if (!hasAdminAccess) {
      setCanManageRagMode(false);
      return;
    }

    let cancelled = false;

    const loadRagMode = async () => {
      try {
        const ragCfg = await api.getRagMode();
        if (cancelled) {
          return;
        }
        setRagModeState(ragCfg.rag_mode);
        setCanManageRagMode(true);
      } catch (error) {
        if (!cancelled) {
          setCanManageRagMode(false);
          setAccessByScope((current) => ({
            ...current,
            admin: classifyAccessError(
              "admin",
              error,
              hasScopeBearerToken(apiAuthStateRef.current, "admin")
            ),
          }));
        }
      }
    };

    void loadRagMode();

    return () => {
      cancelled = true;
    };
  }, [accessByScope.admin.status, hasAdminAccess, hasLoadedApiAuthState]);

  // ── Session helpers ──────────────────────────────────────────

  const refreshSessions = useCallback(async () => {
    if (!isAccessGranted(accessByScope.inspection)) {
      return;
    }
    try {
      const list = await api.listSessions();
      setSessions(list);
    } catch (error) {
      setAccessByScope((current) => ({
        ...current,
        inspection: classifyAccessError(
          "inspection",
          error,
          hasScopeBearerToken(apiAuthStateRef.current, "inspection")
        ),
      }));
    }
  }, [accessByScope.inspection]);

  const createSession = useCallback(async () => {
    if (isReferenceUploading || !hasExecutionAccess) return;
    const session = await api.createSession();
    setSessions((prev) => [session, ...prev]);
    setCurrentSessionId(session.id);
    setWorkspaceModeState("sessions");
    setMessages([]);
    setSelectedWorkflow(null);
    setAttachedIdentifiers([]);
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
    setInspectorPreviewPath(null);
    setInspectorTabState("files");
  }, [hasExecutionAccess, isReferenceUploading]);

  const selectSession = useCallback(async (id: string) => {
    if (isReferenceUploading || !hasInspectionAccess) return;
    if (id === currentSessionId) return;
    setIsSessionLoading(true);
    try {
      await _loadSession(id, setMessages, setCurrentSessionId, setSelectedWorkflow);
      setWorkspaceModeState("sessions");
      setAttachedIdentifiers([]);
      setDraftMessage("");
      setDraftRevision((prev) => prev + 1);
      setInspectorPreviewPath(null);
      setInspectorTabState("files");
    } finally {
      setIsSessionLoading(false);
    }
  }, [currentSessionId, hasInspectionAccess, isReferenceUploading]);

  const deleteSession = useCallback(
    async (id: string) => {
      if (isReferenceUploading || !hasExecutionAccess) return;
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === currentSessionId) {
        setCurrentSessionId(null);
        setWorkspaceModeState("sessions");
        setMessages([]);
        setSelectedWorkflow(null);
        setAttachedIdentifiers([]);
        setDraftMessage("");
        setDraftRevision((prev) => prev + 1);
        setInspectorPreviewPath(null);
        setInspectorTabState("files");
      }
    },
    [currentSessionId, hasExecutionAccess, isReferenceUploading]
  );

  const renameSession = useCallback(async (id: string, title: string) => {
    if (!hasExecutionAccess) {
      return;
    }
    await api.renameSession(id, title);
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title } : s))
    );
  }, [hasExecutionAccess]);

  // ── RAG mode ─────────────────────────────────────────────────

  const setRagMode = useCallback(async (enabled: boolean) => {
    if (!canManageRagMode || !hasAdminAccess) {
      return;
    }

    try {
      const response = await api.setRagMode(enabled);
      setRagModeState(response.rag_mode);
      setCanManageRagMode(true);
    } catch (error) {
      setCanManageRagMode(false);
      setAccessByScope((current) => ({
        ...current,
        admin: classifyAccessError(
          "admin",
          error,
          hasScopeBearerToken(apiAuthStateRef.current, "admin")
        ),
      }));
    }
  }, [canManageRagMode, hasAdminAccess]);

  const setWorkspaceMode = useCallback((mode: WorkspaceMode) => {
    setWorkspaceModeState(mode);
  }, []);

  const selectWorkflow = useCallback((workflowId: string | null) => {
    setSelectedWorkflow(workflowId);
  }, []);

  const uploadAttachedReference = useCallback(async (file: File) => {
    if (!hasExecutionAccess) {
      throw new Error(accessByScope.execution.detail);
    }

    if (file.size > MAX_REFERENCE_UPLOAD_BYTES) {
      throw new Error("Reference files must be 500 KB or smaller.");
    }

    if (isReferenceUploading) {
      throw new Error("A reference upload is already in progress.");
    }

    const uploadToken = referenceUploadTokenRef.current + 1;
    referenceUploadTokenRef.current = uploadToken;
    const targetSessionId = currentSessionIdRef.current;
    setIsReferenceUploading(true);

    try {
      const content = await readReferenceUpload(file);
      const uploadPath = buildReferenceUploadPath(file.name);
      await api.saveFile(uploadPath, content);

      if (currentSessionIdRef.current !== targetSessionId) {
        throw new Error(
          "Reference upload was canceled because the active session changed. Upload it again in this session."
        );
      }

      setAttachedIdentifiers((prev) =>
        prev.includes(uploadPath) ? prev : [...prev, uploadPath]
      );
    } finally {
      if (referenceUploadTokenRef.current === uploadToken) {
        setIsReferenceUploading(false);
      }
    }
  }, [accessByScope.execution.detail, hasExecutionAccess, isReferenceUploading]);

  const addAttachedIdentifier = useCallback((identifier: string) => {
    const trimmed = identifier.trim();
    if (!trimmed) return;

    setAttachedIdentifiers((prev) =>
      prev.includes(trimmed) ? prev : [...prev, trimmed]
    );
  }, []);

  const removeAttachedIdentifier = useCallback((identifier: string) => {
    setAttachedIdentifiers((prev) => prev.filter((item) => item !== identifier));
  }, []);

  const clearAttachedIdentifiers = useCallback(() => {
    setAttachedIdentifiers([]);
  }, []);

  const primeDraftMessage = useCallback((text: string) => {
    setDraftMessage(text);
    setDraftRevision((prev) => prev + 1);
  }, []);

  const clearDraftMessage = useCallback(() => {
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
  }, []);

  const setAccessToken = useCallback((scope: AccessScope, token: string) => {
    setApiAuthState((current) => withScopeBearerToken(current, scope, token));
  }, []);

  const clearAccessTokens = useCallback(() => {
    setApiAuthState(clearAllBearerTokens());
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
    if (!currentSessionId || !hasExecutionAccess) return;
    await api.compressSession(currentSessionId);
    if (hasInspectionAccess) {
      const history = await api.getHistory(currentSessionId);
      const msgs = _historyToMessages(history);
      setMessages(msgs);
      setSelectedWorkflow(getLatestSelectedWorkflow(msgs));
    }
    await refreshSessions();
  }, [currentSessionId, hasExecutionAccess, hasInspectionAccess, refreshSessions]);

  // ── Send message ─────────────────────────────────────────────

  const sendMessage = useCallback(
    async (content: string, context?: api.ChatRequestContext) => {
      if (isStreaming || isReferenceUploading || !hasExecutionAccess) return;
      const requestedWorkflow =
        context && "selectedWorkflow" in context
          ? context.selectedWorkflow ?? null
          : selectedWorkflow;
      const requestedAttachments =
        context && "attachedIdentifiers" in context
          ? context.attachedIdentifiers ?? []
          : attachedIdentifiers;

      // Auto-create session if none is selected
      let sessionId = currentSessionId;
      if (!sessionId) {
        const session = await api.createSession();
        setSessions((prev) => [session, ...prev]);
        setCurrentSessionId(session.id);
        setWorkspaceModeState("sessions");
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
      setAttachedIdentifiers([]);
      setDraftMessage("");
      setDraftRevision((prev) => prev + 1);

      await api.streamChat(content, sessionId, {
        onRetrieval: (query, results) => {
          const id = streamingIdRef.current;
          if (!id) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id
                ? { ...m, retrievals: results }
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
        attachedIdentifiers: requestedAttachments,
        selectedWorkflow: requestedWorkflow,
      });
    },
    [
      attachedIdentifiers,
      currentSessionId,
      hasExecutionAccess,
      isReferenceUploading,
      isStreaming,
      refreshSessions,
      selectedWorkflow,
    ]
  );

  return (
    <AppContext.Provider
      value={{
        apiAuthState,
        accessByScope,
        hasInspectionAccess,
        hasExecutionAccess,
        hasAdminAccess,
        sessions,
        currentSessionId,
        messages,
        isStreaming,
        isReferenceUploading,
        isSessionLoading,
        ragMode,
        canManageRagMode,
        workspaceMode,
        selectedWorkflow,
        attachedIdentifiers,
        draftMessage,
        draftRevision,
        inspectorTab,
        inspectorPreviewPath,
        refreshSessions,
        refreshAccessState,
        createSession,
        selectSession,
        deleteSession,
        renameSession,
        sendMessage,
        setWorkspaceMode,
        selectWorkflow,
        uploadAttachedReference,
        addAttachedIdentifier,
        removeAttachedIdentifier,
        clearAttachedIdentifiers,
        primeDraftMessage,
        clearDraftMessage,
        setAccessToken,
        clearAccessTokens,
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

const MAX_REFERENCE_UPLOAD_BYTES = 500_000;

function buildCheckingAccessStates(
  authState: api.ApiAuthState
): Record<AccessScope, AccessScopeState> {
  return ACCESS_SCOPES.reduce(
    (result, scope) => {
      result[scope] = createCheckingAccessState(
        scope,
        hasScopeBearerToken(authState, scope)
      );
      return result;
    },
    {} as Record<AccessScope, AccessScopeState>
  );
}

function buildAccessStateRecord(
  entries: ReadonlyArray<readonly [AccessScope, AccessScopeState]>
): Record<AccessScope, AccessScopeState> {
  return entries.reduce(
    (result, [scope, state]) => {
      result[scope] = state;
      return result;
    },
    {} as Record<AccessScope, AccessScopeState>
  );
}

function sanitizeUploadFileName(value: string): string {
  const sanitized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-.]+|[-.]+$/g, "");

  return sanitized || "reference.txt";
}

function buildReferenceUploadPath(fileName: string): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `workspace/uploads/${stamp}__${sanitizeUploadFileName(fileName)}`;
}

async function readReferenceUpload(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());

  for (const byte of bytes) {
    if (byte === 0) {
      throw new Error("Reference uploads must be UTF-8 text files.");
    }
  }

  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

// ────────────────────────────────────────────────────────────────
// Internal helpers
// ────────────────────────────────────────────────────────────────

function _historyToMessages(raw: SessionHistoryMessage[]): Message[] {
  return raw
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: uid(),
      role: m.role as "user" | "assistant",
      content: m.content ?? "",
      request_id: m.request_id,
      tool_calls: m.tool_calls ?? [],
      workflow_events: m.workflow_events ?? [],
      retrievals: m.retrievals ?? [],
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
    const messages = _historyToMessages(history);
    setMessages(messages);
    setSelectedWorkflow(getLatestSelectedWorkflow(messages));
  } catch {
    setMessages([]);
    setSelectedWorkflow(null);
  }
}
