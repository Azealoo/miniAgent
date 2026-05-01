import {
  createGrantedAccessState,
  EMPTY_API_AUTH_STATE,
} from "@/lib/access-control";
import type { useApp } from "@/lib/store";

type AppContextValue = ReturnType<typeof useApp>;

const accessGranted = (scope: "inspection" | "execution" | "admin") =>
  createGrantedAccessState(scope, "loopback", false);

export function makeMockAppValue(
  overrides: Partial<AppContextValue> = {}
): AppContextValue {
  const base: AppContextValue = {
    apiAuthState: { ...EMPTY_API_AUTH_STATE },
    accessByScope: {
      inspection: accessGranted("inspection"),
      execution: accessGranted("execution"),
      admin: accessGranted("admin"),
    },
    hasInspectionAccess: true,
    hasExecutionAccess: true,
    hasAdminAccess: true,
    sessions: [],
    currentSessionId: null,
    messages: [],
    isStreaming: false,
    isSessionLoading: false,
    sessionListStatus: "ready",
    sessionListError: null,
    sessionHistoryStatus: "ready",
    sessionHistoryError: null,
    sessionContinuitySummaries: [],
    lastFailedTurn: null,
    parseErrorCount: 0,
    requestIdMismatchCount: 0,
    draftMessage: "",
    draftRevision: 0,
    inspectorTab: "files",
    inspectorPreviewPath: null,
    refreshSessions: async () => {},
    reloadCurrentSession: async () => {},
    refreshAccessState: async () => {},
    createSession: async () => {},
    selectSession: async () => {},
    deleteSession: async () => {},
    renameSession: async () => {},
    sendMessage: async () => {},
    submitApprovalDecision: async () => {},
    stopStreaming: () => {},
    clearLastFailedTurn: () => {},
    primeDraftMessage: () => {},
    clearDraftMessage: () => {},
    setAccessToken: () => {},
    clearAccessTokens: () => {},
    setInspectorTab: () => {},
    openInspectorPath: () => {},
    clearInspectorPath: () => {},
  };

  return { ...base, ...overrides };
}
