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
import {
  applyStreamEvent,
  createOptimisticAssistantMessage,
} from "./chat-stream-reducer";
import { normalizeMessageContent } from "./message-blocks";
import {
  getScopedSurfaceErrorMessage,
  shouldPromoteScopeError,
} from "./surface-errors";
import { uid } from "./utils";
import type {
  AccessScope,
  AccessScopeState,
  InspectorTab,
  Message,
  SessionContinuitySummary,
  Session,
  SessionHistoryMessage,
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
  sessionListStatus: "idle" | "loading" | "ready" | "error";
  sessionListError: string | null;
  sessionHistoryStatus: "idle" | "loading" | "ready" | "error";
  sessionHistoryError: string | null;
  sessionContinuitySummaries: SessionContinuitySummary[];
  attachedIdentifiers: string[];
  draftMessage: string;
  draftRevision: number;
  inspectorTab: InspectorTab;
  inspectorPreviewPath: string | null;

  // Actions
  refreshSessions: () => Promise<void>;
  reloadCurrentSession: () => Promise<void>;
  refreshAccessState: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string, context?: api.ChatRequestContext) => Promise<void>;
  uploadAttachedReference: (file: File) => Promise<void>;
  addAttachedIdentifier: (identifier: string) => void;
  removeAttachedIdentifier: (identifier: string) => void;
  clearAttachedIdentifiers: () => void;
  primeDraftMessage: (text: string) => void;
  clearDraftMessage: () => void;
  setAccessToken: (scope: AccessScope, token: string) => void;
  clearAccessTokens: () => void;
  setInspectorTab: (tab: InspectorTab) => void;
  openInspectorPath: (path: string) => void;
  clearInspectorPath: () => void;
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
  const [sessionListStatus, setSessionListStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("loading");
  const [sessionListError, setSessionListError] = useState<string | null>(null);
  const [sessionHistoryStatus, setSessionHistoryStatus] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [sessionHistoryError, setSessionHistoryError] = useState<string | null>(null);
  const [sessionContinuitySummaries, setSessionContinuitySummaries] = useState<
    SessionContinuitySummary[]
  >([]);
  const [attachedIdentifiers, setAttachedIdentifiers] = useState<string[]>([]);
  const [draftMessage, setDraftMessage] = useState("");
  const [draftRevision, setDraftRevision] = useState(0);
  const [inspectorTab, setInspectorTabState] = useState<InspectorTab>("files");
  const [inspectorPreviewPath, setInspectorPreviewPath] = useState<string | null>(null);

  // Ref to current streaming message ID (avoids stale closure issues)
  const streamingIdRef = useRef<string | null>(null);
  const currentSessionIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const sessionContinuitySummariesRef = useRef<SessionContinuitySummary[]>([]);
  const referenceUploadTokenRef = useRef(0);
  const apiAuthStateRef = useRef(apiAuthState);
  const accessRefreshIdRef = useRef(0);
  const hasInspectionAccess = isAccessGranted(accessByScope.inspection);
  const hasExecutionAccess = isAccessGranted(accessByScope.execution);
  const hasAdminAccess = isAccessGranted(accessByScope.admin);
  const isSessionLoading =
    sessionHistoryStatus === "loading" ||
    (sessionListStatus === "loading" &&
      sessions.length === 0 &&
      currentSessionId === null);

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

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    sessionContinuitySummariesRef.current = sessionContinuitySummaries;
  }, [sessionContinuitySummaries]);

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
    setSessionListStatus("idle");
    setSessionListError(null);
    setSessionHistoryStatus("idle");
    setSessionHistoryError(null);
    setSessionContinuitySummaries([]);
    setInspectorPreviewPath(null);
  }, [accessByScope.inspection.status, hasLoadedApiAuthState]);

  const promoteInspectionScopeError = useCallback((error: unknown) => {
    if (!shouldPromoteScopeError(error)) {
      return;
    }

    setAccessByScope((current) => ({
      ...current,
      inspection: classifyAccessError(
        "inspection",
        error,
        hasScopeBearerToken(apiAuthStateRef.current, "inspection")
      ),
    }));
  }, []);

  const getSessionListErrorMessage = useCallback(
    (error: unknown) =>
      getScopedSurfaceErrorMessage(
        "inspection",
        {
          scope: accessByScope.inspection.scope,
          status: accessByScope.inspection.status,
          authorizationMode: accessByScope.inspection.authorizationMode,
          hasToken: accessByScope.inspection.hasToken,
          detail: accessByScope.inspection.detail,
        },
        error,
        "Could not load the saved session list right now."
      ),
    [
      accessByScope.inspection.authorizationMode,
      accessByScope.inspection.detail,
      accessByScope.inspection.hasToken,
      accessByScope.inspection.scope,
      accessByScope.inspection.status,
    ]
  );

  const getSessionHistoryErrorMessage = useCallback(
    (error: unknown) =>
      getScopedSurfaceErrorMessage(
        "inspection",
        {
          scope: accessByScope.inspection.scope,
          status: accessByScope.inspection.status,
          authorizationMode: accessByScope.inspection.authorizationMode,
          hasToken: accessByScope.inspection.hasToken,
          detail: accessByScope.inspection.detail,
        },
        error,
        "Could not load the selected session history right now."
      ),
    [
      accessByScope.inspection.authorizationMode,
      accessByScope.inspection.detail,
      accessByScope.inspection.hasToken,
      accessByScope.inspection.scope,
      accessByScope.inspection.status,
    ]
  );

  useEffect(() => {
    if (!hasLoadedApiAuthState) {
      return;
    }

    if (accessByScope.inspection.status === "checking") {
      setSessionListStatus("loading");
      setSessionListError(null);
      return;
    }

    if (!hasInspectionAccess) {
      setSessionListStatus("idle");
      setSessionListError(null);
      setSessionHistoryStatus("idle");
      setSessionHistoryError(null);
      setSessionContinuitySummaries([]);
      return;
    }

    let cancelled = false;

    const loadSessions = async () => {
      setSessionListStatus("loading");
      setSessionListError(null);
      try {
        const sessionList = await api.listSessions();
        if (cancelled) {
          return;
        }

        setSessions(sessionList);
        setSessionListStatus("ready");
        const activeId = currentSessionIdRef.current;
        const nextSessionId =
          activeId && sessionList.some((session) => session.id === activeId)
            ? activeId
            : sessionList[0]?.id ?? null;

        if (!nextSessionId) {
          setCurrentSessionId(null);
          setMessages([]);
          setSessionHistoryStatus("idle");
          setSessionHistoryError(null);
          setSessionContinuitySummaries([]);
          return;
        }

        try {
          await _loadSession(
            nextSessionId,
            {
              currentSessionId: currentSessionIdRef.current,
              messages: messagesRef.current,
              continuitySummaries: sessionContinuitySummariesRef.current,
            },
            setMessages,
            setCurrentSessionId,
            setSessionHistoryStatus,
            setSessionHistoryError,
            setSessionContinuitySummaries,
            getSessionHistoryErrorMessage
          );
        } catch (error) {
          if (!cancelled) {
            promoteInspectionScopeError(error);
          }
        }
      } catch (error) {
        if (!cancelled) {
          setSessionListStatus("error");
          setSessionListError(getSessionListErrorMessage(error));
          if (currentSessionIdRef.current === null && messagesRef.current.length === 0) {
            setSessionHistoryStatus("idle");
            setSessionHistoryError(null);
            setSessionContinuitySummaries([]);
          }
          promoteInspectionScopeError(error);
        }
      }
    };

    void loadSessions();

    return () => {
      cancelled = true;
    };
  }, [
    accessByScope.inspection.status,
    getSessionHistoryErrorMessage,
    getSessionListErrorMessage,
    hasInspectionAccess,
    hasLoadedApiAuthState,
    promoteInspectionScopeError,
  ]);

  // ── Session helpers ──────────────────────────────────────────

  const refreshSessions = useCallback(async () => {
    if (!isAccessGranted(accessByScope.inspection)) {
      return;
    }
    setSessionListStatus("loading");
    setSessionListError(null);
    try {
      const list = await api.listSessions();
      setSessions(list);
      setSessionListStatus("ready");
    } catch (error) {
      setSessionListStatus("error");
      setSessionListError(getSessionListErrorMessage(error));
      promoteInspectionScopeError(error);
    }
  }, [accessByScope.inspection, getSessionListErrorMessage, promoteInspectionScopeError]);

  const reloadCurrentSession = useCallback(async () => {
    if (!currentSessionId || !hasInspectionAccess) {
      return;
    }

    try {
      await _loadSession(
        currentSessionId,
        {
          currentSessionId,
          messages: messagesRef.current,
          continuitySummaries: sessionContinuitySummariesRef.current,
        },
        setMessages,
        setCurrentSessionId,
        setSessionHistoryStatus,
        setSessionHistoryError,
        setSessionContinuitySummaries,
        getSessionHistoryErrorMessage
      );
    } catch (error) {
      promoteInspectionScopeError(error);
    }
  }, [
    currentSessionId,
    getSessionHistoryErrorMessage,
    hasInspectionAccess,
    promoteInspectionScopeError,
  ]);

  const createSession = useCallback(async () => {
    if (isReferenceUploading || !hasExecutionAccess) return;
    const session = await api.createSession();
    setSessions((prev) => [session, ...prev]);
    setSessionListStatus("ready");
    setSessionListError(null);
    setCurrentSessionId(session.id);
    setMessages([]);
    setSessionHistoryStatus("ready");
    setSessionHistoryError(null);
    setSessionContinuitySummaries([]);
    setAttachedIdentifiers([]);
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
    setInspectorPreviewPath(null);
    setInspectorTabState("files");
  }, [hasExecutionAccess, isReferenceUploading]);

  const selectSession = useCallback(async (id: string) => {
    if (isReferenceUploading || !hasInspectionAccess) return;
    if (id === currentSessionId) return;
    try {
      await _loadSession(
        id,
        {
          currentSessionId,
          messages: messagesRef.current,
          continuitySummaries: sessionContinuitySummariesRef.current,
        },
        setMessages,
        setCurrentSessionId,
        setSessionHistoryStatus,
        setSessionHistoryError,
        setSessionContinuitySummaries,
        getSessionHistoryErrorMessage
      );
      setAttachedIdentifiers([]);
      setDraftMessage("");
      setDraftRevision((prev) => prev + 1);
      setInspectorPreviewPath(null);
      setInspectorTabState("files");
    } catch (error) {
      promoteInspectionScopeError(error);
    }
  }, [
    currentSessionId,
    getSessionHistoryErrorMessage,
    hasInspectionAccess,
    isReferenceUploading,
    promoteInspectionScopeError,
  ]);

  const deleteSession = useCallback(
    async (id: string) => {
      if (isReferenceUploading || !hasExecutionAccess) return;
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === currentSessionId) {
        setCurrentSessionId(null);
        setMessages([]);
        setSessionHistoryStatus("idle");
        setSessionHistoryError(null);
        setSessionContinuitySummaries([]);
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

  const setInspectorTab = useCallback((tab: InspectorTab) => {
    setInspectorTabState(tab);
  }, []);

  const openInspectorPath = useCallback((path: string) => {
    setInspectorPreviewPath(path);
    setInspectorTabState("files");
  }, []);

  const clearInspectorPath = useCallback(() => {
    setInspectorPreviewPath(null);
  }, []);

  // ── Send message ─────────────────────────────────────────────

  const sendMessage = useCallback(
    async (content: string, context?: api.ChatRequestContext) => {
      if (isStreaming || isReferenceUploading || !hasExecutionAccess) return;
      const requestedAttachments =
        context && "attachedIdentifiers" in context
          ? context.attachedIdentifiers ?? []
          : attachedIdentifiers;

      // Auto-create session if none is selected
      let sessionId = currentSessionId;
      if (!sessionId) {
        const session = await api.createSession();
        setSessions((prev) => [session, ...prev]);
        setSessionListStatus("ready");
        setSessionListError(null);
        setCurrentSessionId(session.id);
        setSessionHistoryStatus("ready");
        setSessionHistoryError(null);
        sessionId = session.id;
      }

      // Add user message + streaming placeholder
      const userMsg: Message = {
        id: uid(),
        role: "user",
        content,
        blocks: [{ type: "text", text: content }],
      };
      const assistantMsg = createOptimisticAssistantMessage(uid(), Date.now());
      streamingIdRef.current = assistantMsg.id;

      const nextMessages = [...messagesRef.current, userMsg, assistantMsg];
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      setIsStreaming(true);
      setAttachedIdentifiers([]);
      setDraftMessage("");
      setDraftRevision((prev) => prev + 1);

      const applyAndCommitEvent = (event: Parameters<typeof applyStreamEvent>[1]) => {
        const reduced = applyStreamEvent(
          {
            messages: messagesRef.current,
            streamingMessageId: streamingIdRef.current,
          },
          event,
          {
            createMessageId: uid,
            now: Date.now(),
          }
        );

        messagesRef.current = reduced.messages;
        streamingIdRef.current = reduced.streamingMessageId;
        setMessages(reduced.messages);

        if (reduced.finished) {
          setIsStreaming(false);
          if (event.type === "done") {
            void refreshSessions();
          }
        }
      };

      try {
        await api.streamChat(content, sessionId, {
          onEvent: (event) => {
            applyAndCommitEvent(event);
          },
        }, {
          attachedIdentifiers: requestedAttachments,
        });
      } catch (error) {
        applyAndCommitEvent({
          type: "error",
          error:
            error instanceof Error
              ? error.message
              : "The response stream failed before completion.",
        });
      }
    },
    [
      attachedIdentifiers,
      currentSessionId,
      hasExecutionAccess,
      isReferenceUploading,
      isStreaming,
      refreshSessions,
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
        sessionListStatus,
        sessionListError,
        sessionHistoryStatus,
        sessionHistoryError,
        sessionContinuitySummaries,
        attachedIdentifiers,
        draftMessage,
        draftRevision,
        inspectorTab,
        inspectorPreviewPath,
        refreshSessions,
        reloadCurrentSession,
        refreshAccessState,
        createSession,
        selectSession,
        deleteSession,
        renameSession,
        sendMessage,
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
    .map((m) => {
      const normalized = normalizeMessageContent(m);
      return {
        id: uid(),
        role: m.role as "user" | "assistant",
        content: normalized.content,
        request_id: m.request_id,
        tool_calls: normalized.toolCalls,
        retrievals: normalized.retrievals,
        blocks: normalized.blocks,
      };
    });
}

interface SessionLoadSnapshot {
  currentSessionId: string | null;
  messages: Message[];
  continuitySummaries: SessionContinuitySummary[];
}

function getPreservedSessionLoadErrorMessage(baseMessage: string): string {
  const trimmed = baseMessage.trim();
  if (!trimmed) {
    return "BioAPEX could not open that saved session, so the previous conversation is still in view.";
  }
  return `BioAPEX could not open that saved session, so the previous conversation is still in view. ${trimmed}`;
}

async function _loadSession(
  id: string,
  snapshot: SessionLoadSnapshot,
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>,
  setSessionHistoryStatus: React.Dispatch<
    React.SetStateAction<"idle" | "loading" | "ready" | "error">
  >,
  setSessionHistoryError: React.Dispatch<React.SetStateAction<string | null>>,
  setSessionContinuitySummaries: React.Dispatch<
    React.SetStateAction<SessionContinuitySummary[]>
  >,
  getErrorMessage: (error: unknown) => string
) {
  const hadPriorContext =
    snapshot.currentSessionId !== null || snapshot.messages.length > 0;

  setSessionHistoryStatus("loading");
  setSessionHistoryError(null);
  setSessionContinuitySummaries([]);
  try {
    const [history, continuity] = await Promise.all([
      api.getHistory(id),
      api.getSessionContinuity(id).catch(() => ({ summaries: [] })),
    ]);
    const messages = _historyToMessages(history);
    setCurrentSessionId(id);
    setMessages(messages);
    setSessionContinuitySummaries(continuity.summaries);
    setSessionHistoryStatus("ready");
    setSessionHistoryError(null);
  } catch (error) {
    const nextErrorMessage =
      hadPriorContext && snapshot.currentSessionId !== id
        ? getPreservedSessionLoadErrorMessage(getErrorMessage(error))
        : getErrorMessage(error);

    if (hadPriorContext) {
      setCurrentSessionId(snapshot.currentSessionId);
      setMessages(snapshot.messages);
      setSessionContinuitySummaries(snapshot.continuitySummaries);
    } else {
      setCurrentSessionId(id);
      setMessages([]);
      setSessionContinuitySummaries([]);
    }
    setSessionHistoryStatus("error");
    setSessionHistoryError(nextErrorMessage);
    throw error;
  }
}
