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
import {
  DEFAULT_ACCESS_PROBE_POLL_INTERVAL_MS,
  useAccessProbe,
} from "../hooks/useAccessProbe";
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
  hasLoadedApiAuthState: boolean,
  pollIntervalMs: number = DEFAULT_ACCESS_PROBE_POLL_INTERVAL_MS
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

  // Re-probe access after outages or server restarts without flashing the UI
  // back into a blocking "checking" state. `runAccessProbe` is stable (auth
  // state reads go through a ref), so the listener wiring is not reinstalled
  // on every render.
  const backgroundProbe = useCallback(() => {
    void runAccessProbe(false);
  }, [runAccessProbe]);

  useAccessProbe({
    probe: backgroundProbe,
    enabled: hasLoadedApiAuthState,
    shouldPoll: shouldPollAccessRecovery,
    pollIntervalMs,
  });

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
