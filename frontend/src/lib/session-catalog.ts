import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isAccessGranted } from "./access-control";
import * as api from "./api";
import { runChatTurn, stopChatTurn } from "./chat-turn-runner";
import {
  historyToMessages,
  loadSession,
  type SessionHistoryStatus,
  type SessionLoadSetters,
} from "./session-history-loader";
import type {
  AccessScope,
  AccessScopeState,
  Message,
  Session,
  SessionContinuitySummary,
} from "./types";

const DEFAULT_SESSION_TITLE = "New Chat";

export type SessionListStatus = "idle" | "loading" | "ready" | "error";

export type ContinuitySummariesLoadingStatus =
  | "idle"
  | "loading"
  | "ready"
  | "error";

export interface UseSessionCatalogParams {
  hasLoadedApiAuthState: boolean;
  accessByScope: Record<AccessScope, AccessScopeState>;
  hasInspectionAccess: boolean;
  hasExecutionAccess: boolean;
  promoteInspectionScopeError: (error: unknown) => void;
  getSessionListErrorMessage: (error: unknown) => string;
  getSessionHistoryErrorMessage: (error: unknown) => string;
  resetDraftAndInspector: () => void;
}

export interface SendMessageOptions {
  /**
   * Optional client-side correlation id. When a turn fails mid-stream the UI
   * captures the original turn's request_id so a "retry" dispatches a new
   * attempt tagged with the same id.
   */
  requestId?: string;
}

export interface FailedTurnState {
  content: string;
  requestId?: string;
}

export interface UseSessionCatalogResult {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  sessionListStatus: SessionListStatus;
  sessionListError: string | null;
  sessionHistoryStatus: SessionHistoryStatus;
  sessionHistoryError: string | null;
  sessionContinuitySummaries: SessionContinuitySummary[];
  /**
   * Lifecycle of the most recent `getSessionContinuity` fetch for the active
   * session. Lets the UI distinguish "no archived summaries yet" from "still
   * fetching" so the empty-state branch can render a loading affordance.
   */
  continuitySummariesLoadingStatus: ContinuitySummariesLoadingStatus;
  lastFailedTurn: FailedTurnState | null;
  /**
   * Number of malformed SSE payloads the parser has surfaced for the active
   * session. Resets when the user switches sessions; otherwise persists across
   * turns so UsagePanel can show cumulative drop telemetry.
   */
  parseErrorCount: number;
  /**
   * Number of stream events the dispatcher dropped because their
   * `request_id` didn't match the in-flight turn. Resets on session
   * switch; parallels `parseErrorCount` in UsagePanel.
   */
  requestIdMismatchCount: number;
  refreshSessions: () => Promise<void>;
  reloadCurrentSession: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string, options?: SendMessageOptions) => Promise<void>;
  stopStreaming: () => void;
  clearLastFailedTurn: () => void;
}

export function useSessionCatalog(
  params: UseSessionCatalogParams
): UseSessionCatalogResult {
  const {
    hasLoadedApiAuthState,
    accessByScope,
    hasInspectionAccess,
    hasExecutionAccess,
    promoteInspectionScopeError,
    getSessionListErrorMessage,
    getSessionHistoryErrorMessage,
    resetDraftAndInspector,
  } = params;

  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionListStatus, setSessionListStatus] =
    useState<SessionListStatus>("loading");
  const [sessionListError, setSessionListError] = useState<string | null>(null);
  const [sessionHistoryStatus, setSessionHistoryStatus] =
    useState<SessionHistoryStatus>("idle");
  const [sessionHistoryError, setSessionHistoryError] = useState<string | null>(
    null
  );
  const [sessionContinuitySummaries, setSessionContinuitySummaries] = useState<
    SessionContinuitySummary[]
  >([]);
  const [
    continuitySummariesLoadingStatus,
    setContinuitySummariesLoadingStatus,
  ] = useState<ContinuitySummariesLoadingStatus>("idle");
  const [lastFailedTurn, setLastFailedTurn] = useState<FailedTurnState | null>(
    null
  );
  const [parseErrorCount, setParseErrorCount] = useState(0);
  const [requestIdMismatchCount, setRequestIdMismatchCount] = useState(0);

  const streamingIdRef = useRef<string | null>(null);
  const streamAbortControllerRef = useRef<AbortController | null>(null);
  const userStoppedStreamRef = useRef(false);
  const currentSessionIdRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const sessionContinuitySummariesRef = useRef<SessionContinuitySummary[]>([]);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    sessionContinuitySummariesRef.current = sessionContinuitySummaries;
  }, [sessionContinuitySummaries]);

  // React's useState setters are stable, so this object only needs to be built
  // once — cache it so dependent useCallback deps don't thrash on every render.
  const loadSessionSetters: SessionLoadSetters = useMemo(
    () => ({
      setMessages,
      setCurrentSessionId,
      setSessionHistoryStatus,
      setSessionHistoryError,
      setSessionContinuitySummaries,
      setSessionContinuitySummariesLoadingStatus:
        setContinuitySummariesLoadingStatus,
    }),
    []
  );

  // Reset session state when inspection access is lost.
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
    setContinuitySummariesLoadingStatus("idle");
    setParseErrorCount(0);
    setRequestIdMismatchCount(0);
  }, [accessByScope.inspection.status, hasLoadedApiAuthState]);

  // Load session list and rehydrate current session once inspection access arrives.
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
      setContinuitySummariesLoadingStatus("idle");
      return;
    }

    let cancelled = false;

    const run = async () => {
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
            : (sessionList[0]?.id ?? null);

        if (!nextSessionId) {
          setCurrentSessionId(null);
          setMessages([]);
          setSessionHistoryStatus("idle");
          setSessionHistoryError(null);
          setSessionContinuitySummaries([]);
          setContinuitySummariesLoadingStatus("idle");
          return;
        }

        try {
          await loadSession(
            nextSessionId,
            {
              currentSessionId: currentSessionIdRef.current,
              messages: messagesRef.current,
              continuitySummaries: sessionContinuitySummariesRef.current,
            },
            loadSessionSetters,
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
          if (
            currentSessionIdRef.current === null &&
            messagesRef.current.length === 0
          ) {
            setSessionHistoryStatus("idle");
            setSessionHistoryError(null);
            setSessionContinuitySummaries([]);
            setContinuitySummariesLoadingStatus("idle");
          }
          promoteInspectionScopeError(error);
        }
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, [
    accessByScope.inspection.status,
    getSessionHistoryErrorMessage,
    getSessionListErrorMessage,
    hasInspectionAccess,
    hasLoadedApiAuthState,
    loadSessionSetters,
    promoteInspectionScopeError,
  ]);

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
  }, [
    accessByScope.inspection,
    getSessionListErrorMessage,
    promoteInspectionScopeError,
  ]);

  const reloadCurrentSession = useCallback(async () => {
    if (!currentSessionId || !hasInspectionAccess) {
      return;
    }

    try {
      await loadSession(
        currentSessionId,
        {
          currentSessionId,
          messages: messagesRef.current,
          continuitySummaries: sessionContinuitySummariesRef.current,
        },
        loadSessionSetters,
        getSessionHistoryErrorMessage
      );
    } catch (error) {
      promoteInspectionScopeError(error);
    }
  }, [
    currentSessionId,
    getSessionHistoryErrorMessage,
    hasInspectionAccess,
    loadSessionSetters,
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
    setContinuitySummariesLoadingStatus("idle");
    setParseErrorCount(0);
    setRequestIdMismatchCount(0);
    resetDraftAndInspector();
  }, [hasExecutionAccess, resetDraftAndInspector]);

  const selectSession = useCallback(
    async (id: string) => {
      if (!hasInspectionAccess) return;
      if (id === currentSessionId) return;
      try {
        await loadSession(
          id,
          {
            currentSessionId,
            messages: messagesRef.current,
            continuitySummaries: sessionContinuitySummariesRef.current,
          },
          loadSessionSetters,
          getSessionHistoryErrorMessage
        );
        setParseErrorCount(0);
        setRequestIdMismatchCount(0);
        resetDraftAndInspector();
      } catch (error) {
        promoteInspectionScopeError(error);
      }
    },
    [
      currentSessionId,
      getSessionHistoryErrorMessage,
      hasInspectionAccess,
      loadSessionSetters,
      promoteInspectionScopeError,
      resetDraftAndInspector,
    ]
  );

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
        setContinuitySummariesLoadingStatus("idle");
        setParseErrorCount(0);
        setRequestIdMismatchCount(0);
        resetDraftAndInspector();
      }
    },
    [currentSessionId, hasExecutionAccess, resetDraftAndInspector]
  );

  const applySessionTitle = useCallback((id: string, title: string) => {
    setSessions((prev) =>
      prev.map((session) =>
        session.id === id ? { ...session, title } : session
      )
    );
  }, []);

  const renameSession = useCallback(
    async (id: string, title: string) => {
      if (!hasExecutionAccess) {
        return;
      }
      await api.renameSession(id, title);
      applySessionTitle(id, title);
    },
    [applySessionTitle, hasExecutionAccess]
  );

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

        const syncedMessages = historyToMessages(history);
        messagesRef.current = syncedMessages;
        setMessages(syncedMessages);
        setSessionHistoryStatus("ready");
        setSessionHistoryError(null);
      } catch {
        // Keep finished local transcript visible if reconciliation fails.
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
          // Keep completed turn visible even if title generation fails.
        }
      }

      await Promise.all([
        refreshSessions(),
        syncCompletedSessionHistory(sessionId, expectedMessageCount),
      ]);
    },
    [applySessionTitle, refreshSessions, syncCompletedSessionHistory]
  );

  const sendMessage = useCallback(
    async (content: string, options?: SendMessageOptions) => {
      if (isStreaming || !hasExecutionAccess) return;

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

      resetDraftAndInspector();
      setLastFailedTurn(null);

      await runChatTurn({
        content,
        sessionId,
        requestId: options?.requestId,
        refs: {
          messagesRef,
          streamingIdRef,
          streamAbortControllerRef,
          userStoppedStreamRef,
        },
        callbacks: {
          setMessages,
          setIsStreaming,
          onTurnComplete: (messageCount) => {
            void finalizeCompletedSession(
              sessionId,
              hadNoMessages && shouldAutoGenerateTitle,
              messageCount
            );
          },
          onTurnError: (failedRequestId) => {
            setLastFailedTurn({
              content,
              requestId: failedRequestId ?? options?.requestId,
            });
          },
          onParseError: () => {
            setParseErrorCount((count) => count + 1);
          },
          onRequestIdMismatch: () => {
            setRequestIdMismatchCount((count) => count + 1);
          },
        },
      });
    },
    [
      currentSessionId,
      finalizeCompletedSession,
      hasExecutionAccess,
      isStreaming,
      resetDraftAndInspector,
      sessions,
    ]
  );

  const clearLastFailedTurn = useCallback(() => {
    setLastFailedTurn(null);
  }, []);

  const stopStreaming = useCallback(() => {
    stopChatTurn({
      messagesRef,
      streamingIdRef,
      streamAbortControllerRef,
      userStoppedStreamRef,
    });
  }, []);

  return {
    sessions,
    currentSessionId,
    messages,
    isStreaming,
    sessionListStatus,
    sessionListError,
    sessionHistoryStatus,
    sessionHistoryError,
    sessionContinuitySummaries,
    continuitySummariesLoadingStatus,
    lastFailedTurn,
    parseErrorCount,
    requestIdMismatchCount,
    refreshSessions,
    reloadCurrentSession,
    createSession,
    selectSession,
    deleteSession,
    renameSession,
    sendMessage,
    stopStreaming,
    clearLastFailedTurn,
  };
}
