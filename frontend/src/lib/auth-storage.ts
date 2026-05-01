import { EMPTY_API_AUTH_STATE } from "./access-control";
import type { ApiAuthState } from "./api";

// Versioned prefix so a future shape change can land without colliding with
// previously-stored entries. The key also includes the backend base URL so
// tokens remain isolated when the same browser talks to several backends.
const STORAGE_KEY_PREFIX = "bioapex.apiAuth.v1:";

/**
 * Mirrors getBase() in ./api.ts. Kept local to avoid widening that module's
 * public surface just for storage keying.
 */
export function getStorageBaseUrl(): string {
  if (typeof window === "undefined") return "http://localhost:8002";
  return `http://${window.location.hostname}:8002`;
}

function getStorageKey(baseUrl: string): string {
  return `${STORAGE_KEY_PREFIX}${baseUrl}`;
}

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function sanitizeToken(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeAuthState(value: unknown): ApiAuthState {
  if (!value || typeof value !== "object") {
    return { ...EMPTY_API_AUTH_STATE };
  }
  const record = value as Record<string, unknown>;
  return {
    inspectionBearerToken: sanitizeToken(record.inspectionBearerToken),
    executionBearerToken: sanitizeToken(record.executionBearerToken),
    adminBearerToken: sanitizeToken(record.adminBearerToken),
  };
}

export function loadApiAuthState(
  baseUrl: string = getStorageBaseUrl(),
): ApiAuthState {
  const storage = getStorage();
  if (!storage) return { ...EMPTY_API_AUTH_STATE };
  let raw: string | null;
  try {
    raw = storage.getItem(getStorageKey(baseUrl));
  } catch {
    return { ...EMPTY_API_AUTH_STATE };
  }
  if (!raw) return { ...EMPTY_API_AUTH_STATE };
  try {
    return normalizeAuthState(JSON.parse(raw));
  } catch {
    return { ...EMPTY_API_AUTH_STATE };
  }
}

export function saveApiAuthState(
  authState: ApiAuthState,
  baseUrl: string = getStorageBaseUrl(),
): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(
      getStorageKey(baseUrl),
      JSON.stringify(normalizeAuthState(authState)),
    );
  } catch {
    // Storage may be disabled (private mode) or full — fall back to in-memory
    // state rather than breaking the sign-in flow.
  }
}

export function clearApiAuthState(
  baseUrl: string = getStorageBaseUrl(),
): void {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.removeItem(getStorageKey(baseUrl));
  } catch {
    // See saveApiAuthState.
  }
}
