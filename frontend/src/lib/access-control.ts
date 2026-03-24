import type { ApiAuthState } from "./api";
import { getApiErrorStatus } from "./api";
import type {
  AccessAuthorizationMode,
  AccessScope,
  AccessScopeState,
} from "./types";

export const ACCESS_SCOPES: AccessScope[] = [
  "inspection",
  "execution",
  "admin",
];

export const EMPTY_API_AUTH_STATE: ApiAuthState = {
  inspectionBearerToken: null,
  executionBearerToken: null,
  adminBearerToken: null,
};

export interface AccessSummary {
  detail: string;
  label: string;
  tone: "neutral" | "accent" | "warning" | "danger";
}

function scopeLabel(scope: AccessScope): string {
  if (scope === "inspection") {
    return "Inspection";
  }
  if (scope === "execution") {
    return "Execution";
  }
  return "Admin";
}

export function scopeRequirement(scope: AccessScope): string {
  if (scope === "inspection") {
    return "Required for session history, files, Ops reads, and registry inspection.";
  }
  if (scope === "execution") {
    return "Required for chat, session mutations, file writes, and reference uploads.";
  }
  return "Required for config changes, RAG control, and admin-only mutations.";
}

function authStateKey(scope: AccessScope): keyof ApiAuthState {
  if (scope === "inspection") {
    return "inspectionBearerToken";
  }
  if (scope === "execution") {
    return "executionBearerToken";
  }
  return "adminBearerToken";
}

export function getScopeBearerToken(
  authState: ApiAuthState,
  scope: AccessScope
): string | null {
  return authState[authStateKey(scope)]?.trim() || null;
}

export function hasScopeBearerToken(
  authState: ApiAuthState,
  scope: AccessScope
): boolean {
  return Boolean(getScopeBearerToken(authState, scope));
}

export function withScopeBearerToken(
  authState: ApiAuthState,
  scope: AccessScope,
  token: string
): ApiAuthState {
  const cleaned = token.trim();
  return {
    ...authState,
    [authStateKey(scope)]: cleaned ? cleaned : null,
  };
}

export function clearAllBearerTokens(): ApiAuthState {
  return { ...EMPTY_API_AUTH_STATE };
}

export function createCheckingAccessState(
  scope: AccessScope,
  hasToken: boolean
): AccessScopeState {
  return {
    scope,
    status: "checking",
    authorizationMode: null,
    hasToken,
    detail: `Checking ${scopeLabel(scope).toLowerCase()} access…`,
  };
}

export function createGrantedAccessState(
  scope: AccessScope,
  authorizationMode: AccessAuthorizationMode | null,
  hasToken: boolean
): AccessScopeState {
  const accessMode = authorizationMode ?? "bearer";
  return {
    scope,
    status: "granted",
    authorizationMode: accessMode,
    hasToken,
    detail:
      accessMode === "loopback"
        ? `${scopeLabel(scope)} access is available from this local client without a bearer token.`
        : `${scopeLabel(scope)} access is authenticated with the current bearer token.`,
  };
}

export function classifyAccessError(
  scope: AccessScope,
  error: unknown,
  hasToken: boolean
): AccessScopeState {
  const status = getApiErrorStatus(error);
  const label = scopeLabel(scope);

  if (status === 401) {
    return {
      scope,
      status: "token_required",
      authorizationMode: null,
      hasToken,
      detail: hasToken
        ? `${label} access rejected the current bearer token. Update the token or use a loopback client.`
        : `${label} access requires a bearer token for this client.`,
    };
  }

  if (status === 403) {
    return {
      scope,
      status: "forbidden",
      authorizationMode: null,
      hasToken,
      detail: `${label} access is unavailable from this client unless loopback access is allowed or the server is configured for bearer-token access.`,
    };
  }

  if (status === 503) {
    return {
      scope,
      status: "server_misconfigured",
      authorizationMode: null,
      hasToken,
      detail: `${label} access is configured on the server, but the corresponding bearer-token environment variable is empty.`,
    };
  }

  return {
    scope,
    status: "unavailable",
    authorizationMode: null,
    hasToken,
    detail: `${label} access could not be checked because the backend is unavailable or returned an unexpected response.`,
  };
}

export function isAccessGranted(state: AccessScopeState | null | undefined): boolean {
  return state?.status === "granted";
}

export function accessStatusBadgeLabel(state: AccessScopeState): string {
  if (state.status === "granted") {
    return state.authorizationMode === "loopback" ? "Local" : "Token";
  }
  if (state.status === "checking") {
    return "Checking";
  }
  if (state.status === "token_required") {
    return state.hasToken ? "Token rejected" : "Token needed";
  }
  if (state.status === "server_misconfigured") {
    return "Server token empty";
  }
  if (state.status === "forbidden") {
    return "Not available";
  }
  return "Unavailable";
}

export function getOverallAccessSummary(
  accessByScope: Record<AccessScope, AccessScopeState>
): AccessSummary {
  const states = ACCESS_SCOPES.map((scope) => accessByScope[scope]);
  if (states.some((state) => state.status === "checking")) {
    return {
      label: "Checking Access",
      detail: "Inspecting inspection, execution, and admin capabilities for this client.",
      tone: "neutral",
    };
  }

  const grantedCount = states.filter((state) => state.status === "granted").length;
  if (grantedCount === states.length) {
    return {
      label: "Access Ready",
      detail: states
        .map((state) => `${scopeLabel(state.scope)}: ${accessStatusBadgeLabel(state)}`)
        .join(" • "),
      tone: "accent",
    };
  }

  if (grantedCount > 0) {
    return {
      label: "Partial Access",
      detail: states
        .map((state) => `${scopeLabel(state.scope)}: ${accessStatusBadgeLabel(state)}`)
        .join(" • "),
      tone: "warning",
    };
  }

  return {
    label: "Access Restricted",
    detail: states
      .map((state) => `${scopeLabel(state.scope)}: ${accessStatusBadgeLabel(state)}`)
      .join(" • "),
    tone: "danger",
  };
}

export function getScopeRestrictionMessage(
  scope: AccessScope,
  accessByScope: Record<AccessScope, AccessScopeState>,
  fallback: string
): string {
  const state = accessByScope[scope];
  if (!state || state.status === "granted") {
    return fallback;
  }
  return state.detail;
}
