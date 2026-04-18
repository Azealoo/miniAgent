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
import {
  normalizeMessageContent,
  normalizeTurnMessages,
} from "./message-blocks";
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

const DEFAULT_SESSION_TITLE = "New Chat";

export interface ApprovalDecisionInput {
  sessionId: string;
  runId: string;
  toolName: string;
  decision: "approve" | "deny";
  rationale?: string | null;
  actor?: string;
  resumeMessage?: string;
}

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
  isSessionLoading: boolean;
  sessionListStatus: "idle" | "loading" | "ready" | "error";
  sessionListError: string | null;
  sessionHistoryStatus: "idle" | "loading" | "ready" | "error";
  sessionHistoryError: string | null;
  sessionContinuitySummaries: SessionContinuitySummary[];
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
  sendMessage: (content: string) => Promise<void>;
  stopStreaming: () => void;
  primeDraftMessage: (text: string) => void;
  clearDraftMessage: () => void;
  submitApprovalDecision: (input: ApprovalDecisionInput) => Promise<void>;
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

/**
 * Non-throwing variant for components rendered by unit tests that don't wrap
 * the tree in an AppProvider (e.g., ChatMessage snapshot tests). Callers that
 * need the context must handle the null case explicitly.
 */
export function useAppOptional(): AppContextValue | null {
  return useContext(AppContext);
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
  const [draftMessage, setDraftMessage] = useState("");
  const [draftRevision, setDraftRevision] = useState(0);
  const [inspectorTab, setInspectorTabState] = useState<InspectorTab>("files");
  const [inspectorPreviewPath, setInspectorPreviewPath] = useState<string | null>(null);

  // Ref to current streaming message ID (avoids stale closure issues)
  const streamingIdRef = useRef<string | null>(null);
  const streamAbortControllerRef = useRef<AbortController | null>(null);
  const userStoppedStreamRef = useRef(false);
  const currentSessionIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const sessionContinuitySummariesRef = useRef<SessionContinuitySummary[]>([]);
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
    if (!hasExecutionAccess) return;
    const session = await api.createSession();
    setSessions((prev) => [session, ...prev]);
    setSessionListStatus("ready");
    setSessionListError(null);
    setCurrentSessionId(session.id);
    setMessages([]);
    setSessionHistoryStatus("ready");
    setSessionHistoryError(null);
    setSessionContinuitySummaries([]);
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
    setInspectorPreviewPath(null);
    setInspectorTabState("files");
  }, [hasExecutionAccess]);

  const selectSession = useCallback(async (id: string) => {
    if (!hasInspectionAccess) return;
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
    promoteInspectionScopeError,
  ]);

  const deleteSession = useCallback(
    async (id: string) => {
      if (!hasExecutionAccess) return;
      await api.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === currentSessionId) {
        setCurrentSessionId(null);
        setMessages([]);
        setSessionHistoryStatus("idle");
        setSessionHistoryError(null);
        setSessionContinuitySummaries([]);
        setDraftMessage("");
        setDraftRevision((prev) => prev + 1);
        setInspectorPreviewPath(null);
        setInspectorTabState("files");
      }
    },
    [currentSessionId, hasExecutionAccess]
  );

  const applySessionTitle = useCallback((id: string, title: string) => {
    setSessions((prev) =>
      prev.map((session) =>
        session.id === id ? { ...session, title } : session
      )
    );
  }, []);

  const renameSession = useCallback(async (id: string, title: string) => {
    if (!hasExecutionAccess) {
      return;
    }
    await api.renameSession(id, title);
    applySessionTitle(id, title);
  }, [applySessionTitle, hasExecutionAccess]);

  const syncCompletedSessionHistory = useCallback(
    async (sessionId: string, expectedMessageCount: number) => {
      if (!hasInspectionAccess) {
        return;
      }

      try {
        const history = await api.getHistory(sessionId);

        if (
          currentSessionIdRef.current !== sessionId ||
          streamingIdRef.current !== null ||
          messagesRef.current.length !== expectedMessageCount
        ) {
          return;
        }

        const syncedMessages = _historyToMessages(history);
        messagesRef.current = syncedMessages;
        setMessages(syncedMessages);
        setSessionHistoryStatus("ready");
        setSessionHistoryError(null);
      } catch {
        // Keep the finished local transcript visible if background reconciliation fails.
      }
    },
    [hasInspectionAccess]
  );

  const finalizeCompletedSession = useCallback(
    async (
      sessionId: string,
      shouldAutoGenerateTitle: boolean,
      expectedMessageCount: number
    ) => {
      if (shouldAutoGenerateTitle) {
        try {
          const generated = await api.generateSessionTitle(sessionId);
          applySessionTitle(sessionId, generated.title);
        } catch {
          // Keep the completed turn visible even if background title generation fails.
        }
      }

      await Promise.all([
        refreshSessions(),
        syncCompletedSessionHistory(sessionId, expectedMessageCount),
      ]);
    },
    [applySessionTitle, refreshSessions, syncCompletedSessionHistory]
  );

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

  const stopStreaming = useCallback(() => {
    if (!streamAbortControllerRef.current || !streamingIdRef.current) {
      return;
    }

    userStoppedStreamRef.current = true;
    streamAbortControllerRef.current.abort();
  }, []);

  // Ref indirection breaks the sendMessage <-> submitApprovalDecision callback
  // cycle — otherwise declaring either first would reference the other before
  // it is initialized.
  const sendMessageRef = useRef<((content: string) => Promise<void>) | null>(null);

  const submitApprovalDecisionAction = useCallback(
    async (input: ApprovalDecisionInput) => {
      if (!hasExecutionAccess) return;
      await api.submitApprovalDecision({
        session_id: input.sessionId,
        run_id: input.runId,
        tool_name: input.toolName,
        decision: input.decision,
        rationale: input.rationale ?? null,
        actor: input.actor ?? "ui-user",
      });
      // Reload the session so the approval_gate block reflects the persisted
      // decision (the backend records it on disk, not in the live message tree).
      await reloadCurrentSession();

      // On approve, auto-resume the turn with the reviewer-supplied message (or
      // a minimal "continue" nudge so the agent picks up the newly approved
      // tool). On deny we leave the turn paused — the reviewer can author a
      // follow-up message or cancel.
      if (input.decision === "approve" && !isStreaming) {
        const resume = (input.resumeMessage ?? "continue").trim() || "continue";
        await sendMessageRef.current?.(resume);
      }
    },
    [hasExecutionAccess, isStreaming, reloadCurrentSession]
  );

  // ── Send message ─────────────────────────────────────────────

  const sendMessage = useCallback(
    async (content: string) => {
      if (isStreaming || !hasExecutionAccess) return;

      // Auto-create session if none is selected
      let sessionId = currentSessionId;
      const hadNoMessages = messagesRef.current.length === 0;
      let shouldAutoGenerateTitle = false;
      if (!sessionId) {
        const session = await api.createSession();
        setSessions((prev) => [session, ...prev]);
        setSessionListStatus("ready");
        setSessionListError(null);
        setCurrentSessionId(session.id);
        setSessionHistoryStatus("ready");
        setSessionHistoryError(null);
        sessionId = session.id;
        shouldAutoGenerateTitle = session.title === DEFAULT_SESSION_TITLE;
      } else {
        const activeSession =
          sessions.find((session) => session.id === sessionId) ?? null;
        shouldAutoGenerateTitle =
          hadNoMessages &&
          (activeSession?.title ?? DEFAULT_SESSION_TITLE) ===
            DEFAULT_SESSION_TITLE;
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
      setDraftMessage("");
      setDraftRevision((prev) => prev + 1);
      const abortController = new AbortController();
      streamAbortControllerRef.current = abortController;
      userStoppedStreamRef.current = false;

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
            void finalizeCompletedSession(
              sessionId,
              hadNoMessages && shouldAutoGenerateTitle,
              reduced.messages.length
            );
          }
        }
      };

      try {
        await api.streamChat(content, sessionId, {
          signal: abortController.signal,
          onEvent: (event) => {
            applyAndCommitEvent(event);
          },
        });
      } catch (error) {
        if (api.isAbortError(error) && userStoppedStreamRef.current) {
          applyAndCommitEvent({
            type: "done",
            content: "Response stopped.",
          });
        } else {
          applyAndCommitEvent({
            type: "error",
            error:
              error instanceof Error
                ? error.message
                : "The response stream failed before completion.",
          });
        }
      } finally {
        streamAbortControllerRef.current = null;
        userStoppedStreamRef.current = false;
      }
    },
    [
      currentSessionId,
      finalizeCompletedSession,
      hasExecutionAccess,
      isStreaming,
      sessions,
    ]
  );

  useEffect(() => {
    sendMessageRef.current = sendMessage;
    return () => {
      sendMessageRef.current = null;
    };
  }, [sendMessage]);

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
        isSessionLoading,
        sessionListStatus,
        sessionListError,
        sessionHistoryStatus,
        sessionHistoryError,
        sessionContinuitySummaries,
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
        stopStreaming,
        primeDraftMessage,
        clearDraftMessage,
        submitApprovalDecision: submitApprovalDecisionAction,
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

// ────────────────────────────────────────────────────────────────
// Internal helpers
// ────────────────────────────────────────────────────────────────

function groupHistoryMessagesIntoTurns<T extends { role: string }>(
  messages: T[]
): T[][] {
  const turns: T[][] = [];
  let currentTurn: T[] = [];

  for (const message of messages) {
    if (message.role === "user") {
      if (currentTurn.length > 0) {
        turns.push(currentTurn);
      }
      currentTurn = [message];
      continue;
    }

    if (currentTurn.length === 0) {
      currentTurn = [message];
      continue;
    }

    currentTurn.push(message);
  }

  if (currentTurn.length > 0) {
    turns.push(currentTurn);
  }

  return turns;
}

function _historyToMessages(raw: SessionHistoryMessage[]): Message[] {
  const filtered = raw.filter((m) => m.role === "user" || m.role === "assistant");
  const normalizedHistory = groupHistoryMessagesIntoTurns(filtered).flatMap((turn) =>
    normalizeTurnMessages(turn)
  );

  return normalizedHistory
    .map((m) => {
      const normalized = normalizeMessageContent(m);
      return {
        id: uid(),
        role: m.role as "user" | "assistant",
        content: normalized.content,
        request_id: m.request_id,
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
