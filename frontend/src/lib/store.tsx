"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  clearAllBearerTokens,
  EMPTY_API_AUTH_STATE,
  withScopeBearerToken,
} from "./access-control";
import * as api from "./api";
import {
  clearApiAuthState,
  loadApiAuthState,
  saveApiAuthState,
} from "./auth-storage";
import { useAccessScopeState } from "./access-scope-state";
import {
  useSessionCatalog,
  type ContinuitySummariesLoadingStatus,
  type FailedTurnState,
  type SendMessageOptions,
} from "./session-catalog";
import type { SessionHistoryStatus } from "./session-history-loader";
import type {
  AccessScope,
  AccessScopeState,
  InspectorTab,
  Message,
  Session,
  SessionContinuitySummary,
} from "./types";

export interface ApprovalDecisionInput {
  sessionId: string;
  runId: string;
  toolName: string;
  decision: "approve" | "deny";
  rationale?: string | null;
  actor?: string;
  resumeMessage?: string;
}

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
  sessionHistoryStatus: SessionHistoryStatus;
  sessionHistoryError: string | null;
  sessionContinuitySummaries: SessionContinuitySummary[];
  /**
   * Lifecycle of the most recent session-continuity fetch. `"loading"` while
   * the parallel `getSessionContinuity` request is in flight, `"ready"` once
   * it lands, `"error"` if the surrounding `loadSession` failed. Drives the
   * loading affordance in the SessionHistorySummary empty-state branch.
   */
  continuitySummariesLoadingStatus: ContinuitySummariesLoadingStatus;
  lastFailedTurn: FailedTurnState | null;
  /**
   * Count of malformed SSE payloads the parser has surfaced for the active
   * session. Drives the parse-error row in UsagePanel so dropped events are
   * observable instead of silently swallowed.
   */
  parseErrorCount: number;
  /**
   * Count of events the dispatcher dropped because their `request_id`
   * didn't match the in-flight turn. Surfaced beside `parseErrorCount` in
   * UsagePanel so stale-response drops are observable.
   */
  requestIdMismatchCount: number;
  draftMessage: string;
  draftRevision: number;
  inspectorTab: InspectorTab;
  inspectorPreviewPath: string | null;

  refreshSessions: () => Promise<void>;
  reloadCurrentSession: () => Promise<void>;
  refreshAccessState: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string, options?: SendMessageOptions) => Promise<void>;
  stopStreaming: () => void;
  clearLastFailedTurn: () => void;
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

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [apiAuthState, setApiAuthState] = useState<api.ApiAuthState>({
    ...EMPTY_API_AUTH_STATE,
  });
  const [hasLoadedApiAuthState, setHasLoadedApiAuthState] = useState(false);
  const [draftMessage, setDraftMessage] = useState("");
  const [draftRevision, setDraftRevision] = useState(0);
  const [inspectorTab, setInspectorTabState] = useState<InspectorTab>("files");
  const [inspectorPreviewPath, setInspectorPreviewPath] = useState<
    string | null
  >(null);

  const apiAuthStateRef = useRef(apiAuthState);

  useEffect(() => {
    // Hydrate persisted bearer tokens keyed by backend base URL so reloads
    // don't force the user back through sign-in. Runs once on mount (client
    // only) — the server-render pass leaves the empty initial state intact.
    setApiAuthState(loadApiAuthState());
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

  const access = useAccessScopeState(
    apiAuthState,
    apiAuthStateRef,
    hasLoadedApiAuthState
  );

  const resetDraftAndInspector = useCallback(() => {
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
    setInspectorPreviewPath(null);
    setInspectorTabState("files");
  }, []);

  const catalog = useSessionCatalog({
    hasLoadedApiAuthState,
    accessByScope: access.accessByScope,
    hasInspectionAccess: access.hasInspectionAccess,
    hasExecutionAccess: access.hasExecutionAccess,
    promoteInspectionScopeError: access.promoteInspectionScopeError,
    getSessionListErrorMessage: access.getSessionListErrorMessage,
    getSessionHistoryErrorMessage: access.getSessionHistoryErrorMessage,
    resetDraftAndInspector,
  });

  // Also clear the inspector preview whenever inspection access is fully revoked.
  useEffect(() => {
    if (!hasLoadedApiAuthState) {
      return;
    }
    const status = access.accessByScope.inspection.status;
    if (
      status === "granted" ||
      status === "checking" ||
      status === "unavailable"
    ) {
      return;
    }
    setInspectorPreviewPath(null);
  }, [access.accessByScope.inspection.status, hasLoadedApiAuthState]);

  const isSessionLoading =
    catalog.sessionHistoryStatus === "loading" ||
    (catalog.sessionListStatus === "loading" &&
      catalog.sessions.length === 0 &&
      catalog.currentSessionId === null);

  const primeDraftMessage = useCallback((text: string) => {
    setDraftMessage(text);
    setDraftRevision((prev) => prev + 1);
  }, []);

  const clearDraftMessage = useCallback(() => {
    setDraftMessage("");
    setDraftRevision((prev) => prev + 1);
  }, []);

  const setAccessToken = useCallback((scope: AccessScope, token: string) => {
    setApiAuthState((current) => {
      const next = withScopeBearerToken(current, scope, token);
      saveApiAuthState(next);
      return next;
    });
  }, []);

  const clearAccessTokens = useCallback(() => {
    clearApiAuthState();
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

  const submitApprovalDecision = useCallback(
    async (input: ApprovalDecisionInput) => {
      if (!access.hasExecutionAccess) return;
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
      await catalog.reloadCurrentSession();

      // On approve, auto-resume the turn with the reviewer-supplied message (or
      // a minimal "continue" nudge so the agent picks up the newly approved
      // tool). On deny we leave the turn paused — the reviewer can author a
      // follow-up message or cancel.
      if (input.decision === "approve" && !catalog.isStreaming) {
        const resume = (input.resumeMessage ?? "continue").trim() || "continue";
        await catalog.sendMessage(resume);
      }
    },
    [access.hasExecutionAccess, catalog]
  );

  // Memoize the context value so consumers that depend on `useApp()` don't
  // re-render on every AppProvider render. Without this, the object literal
  // rebuilds each render and defeats the child-level useCallback/React.memo
  // guards downstream.
  const contextValue = useMemo<AppContextValue>(
    () => ({
      apiAuthState,
      accessByScope: access.accessByScope,
      hasInspectionAccess: access.hasInspectionAccess,
      hasExecutionAccess: access.hasExecutionAccess,
      hasAdminAccess: access.hasAdminAccess,
      sessions: catalog.sessions,
      currentSessionId: catalog.currentSessionId,
      messages: catalog.messages,
      isStreaming: catalog.isStreaming,
      isSessionLoading,
      sessionListStatus: catalog.sessionListStatus,
      sessionListError: catalog.sessionListError,
      sessionHistoryStatus: catalog.sessionHistoryStatus,
      sessionHistoryError: catalog.sessionHistoryError,
      sessionContinuitySummaries: catalog.sessionContinuitySummaries,
      continuitySummariesLoadingStatus:
        catalog.continuitySummariesLoadingStatus,
      lastFailedTurn: catalog.lastFailedTurn,
      parseErrorCount: catalog.parseErrorCount,
      requestIdMismatchCount: catalog.requestIdMismatchCount,
      draftMessage,
      draftRevision,
      inspectorTab,
      inspectorPreviewPath,
      refreshSessions: catalog.refreshSessions,
      reloadCurrentSession: catalog.reloadCurrentSession,
      refreshAccessState: access.refreshAccessState,
      createSession: catalog.createSession,
      selectSession: catalog.selectSession,
      deleteSession: catalog.deleteSession,
      renameSession: catalog.renameSession,
      sendMessage: catalog.sendMessage,
      stopStreaming: catalog.stopStreaming,
      clearLastFailedTurn: catalog.clearLastFailedTurn,
      primeDraftMessage,
      clearDraftMessage,
      submitApprovalDecision,
      setAccessToken,
      clearAccessTokens,
      setInspectorTab,
      openInspectorPath,
      clearInspectorPath,
    }),
    [
      apiAuthState,
      access.accessByScope,
      access.hasInspectionAccess,
      access.hasExecutionAccess,
      access.hasAdminAccess,
      access.refreshAccessState,
      catalog.sessions,
      catalog.currentSessionId,
      catalog.messages,
      catalog.isStreaming,
      catalog.sessionListStatus,
      catalog.sessionListError,
      catalog.sessionHistoryStatus,
      catalog.sessionHistoryError,
      catalog.sessionContinuitySummaries,
      catalog.continuitySummariesLoadingStatus,
      catalog.lastFailedTurn,
      catalog.parseErrorCount,
      catalog.requestIdMismatchCount,
      catalog.refreshSessions,
      catalog.reloadCurrentSession,
      catalog.createSession,
      catalog.selectSession,
      catalog.deleteSession,
      catalog.renameSession,
      catalog.sendMessage,
      catalog.stopStreaming,
      catalog.clearLastFailedTurn,
      isSessionLoading,
      draftMessage,
      draftRevision,
      inspectorTab,
      inspectorPreviewPath,
      primeDraftMessage,
      clearDraftMessage,
      submitApprovalDecision,
      setAccessToken,
      clearAccessTokens,
      setInspectorTab,
      openInspectorPath,
      clearInspectorPath,
    ]
  );

  return <AppContext.Provider value={contextValue}>{children}</AppContext.Provider>;
}
