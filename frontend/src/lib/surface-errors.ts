import { classifyAccessError } from "./access-control";
import { ApiError, ApiPayloadError } from "./api";
import { compactText } from "./format";
import type { AccessScope, AccessScopeState } from "./types";

export function shouldPromoteScopeError(error: unknown): boolean {
  if (error instanceof ApiPayloadError) {
    return false;
  }

  if (error instanceof ApiError) {
    return error.status === 401 || error.status === 403 || error.status === 503;
  }

  return error instanceof TypeError;
}

export function getScopedSurfaceErrorMessage(
  scope: AccessScope,
  accessState: AccessScopeState,
  error: unknown,
  fallbackMessage: string,
  maxLength = 200
): string {
  if (error instanceof ApiPayloadError) {
    return error.message;
  }

  const scopedState = classifyAccessError(scope, error, accessState.hasToken);
  if (scopedState.status !== "unavailable") {
    return scopedState.detail;
  }

  const rawMessage = error instanceof Error ? error.message : fallbackMessage;
  const compactMessage = compactText(rawMessage, maxLength);
  return compactMessage || fallbackMessage;
}
