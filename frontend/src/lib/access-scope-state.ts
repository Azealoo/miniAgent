import { useCallback, useEffect, useRef, useState } from "react";
import {
  ACCESS_SCOPES,
  classifyAccessError,
  createCheckingAccessState,
  createGrantedAccessState,
  EMPTY_API_AUTH_STATE,
  hasScopeBearerToken,
  isAccessGranted,
} from "./access-control";
import * as api from "./api";
import {
  getScopedSurfaceErrorMessage,
  shouldPromoteScopeError,
} from "./surface-errors";
import type { AccessScope, AccessScopeState } from "./types";

export function buildCheckingAccessStates(
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

export interface UseAccessScopeStateResult {
  accessByScope: Record<AccessScope, AccessScopeState>;
  hasInspectionAccess: boolean;
  hasExecutionAccess: boolean;
  hasAdminAccess: boolean;
  refreshAccessState: () => Promise<void>;
  promoteInspectionScopeError: (error: unknown) => void;
  getSessionListErrorMessage: (error: unknown) => string;
  getSessionHistoryErrorMessage: (error: unknown) => string;
}

export function useAccessScopeState(
  apiAuthState: api.ApiAuthState,
  apiAuthStateRef: React.MutableRefObject<api.ApiAuthState>,
  hasLoadedApiAuthState: boolean
): UseAccessScopeStateResult {
  const [accessByScope, setAccessByScope] = useState<
    Record<AccessScope, AccessScopeState>
  >(() => buildCheckingAccessStates(EMPTY_API_AUTH_STATE));
  const accessRefreshIdRef = useRef(0);

  const runAccessProbe = useCallback(
    async (showChecking: boolean) => {
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
    },
    [apiAuthStateRef]
  );

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

  const promoteInspectionScopeError = useCallback(
    (error: unknown) => {
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
    },
    [apiAuthStateRef]
  );

  const getSessionListErrorMessage = useCallback(
    (error: unknown) =>
      getScopedSurfaceErrorMessage(
        "inspection",
        accessByScope.inspection,
        error,
        "Could not load the saved session list right now."
      ),
    [accessByScope.inspection]
  );

  const getSessionHistoryErrorMessage = useCallback(
    (error: unknown) =>
      getScopedSurfaceErrorMessage(
        "inspection",
        accessByScope.inspection,
        error,
        "Could not load the selected session history right now."
      ),
    [accessByScope.inspection]
  );

  return {
    accessByScope,
    hasInspectionAccess: isAccessGranted(accessByScope.inspection),
    hasExecutionAccess: isAccessGranted(accessByScope.execution),
    hasAdminAccess: isAccessGranted(accessByScope.admin),
    refreshAccessState,
    promoteInspectionScopeError,
    getSessionListErrorMessage,
    getSessionHistoryErrorMessage,
  };
}
