import type {
  AccessProbeResponse,
  ChatStreamErrorEvent,
  FileSaveResponse,
  RawFileTextResponse,
  Session,
} from "./types";
import {
  ApiPayloadError,
  isApiPayloadError,
  createPayloadError,
  validateFileContentsResponse,
  validateSessionContinuity,
  validateSessionHistory,
  validateSessionList,
  validateTokenStats,
} from "./api-payload";
import {
  createChatStreamDispatcher,
  parseChatStreamChunk,
  type StreamCallbacks,
} from "./chat-stream-events";
import { RUNTIME_EVENT_SCHEMA_VERSION } from "./runtime-events";
import { log } from "./telemetry";

export { ApiPayloadError, isApiPayloadError };
export type { StreamCallbacks };

function getBase(): string {
  if (typeof window === "undefined") return "http://localhost:8002";
  return `http://${window.location.hostname}:8002`;
}

export type ApiAccessScope = "public" | "inspection" | "execution" | "admin";
export type ProtectedApiAccessScope = Exclude<ApiAccessScope, "public">;

export interface ApiAuthState {
  inspectionBearerToken?: string | null;
  executionBearerToken?: string | null;
  adminBearerToken?: string | null;
}

export type ApiAuthProvider = () => ApiAuthState | null | undefined;

type QueryValue = string | number | boolean | null | undefined;
type QueryParams = Record<string, QueryValue | QueryValue[]>;

interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | null;
  jsonBody?: unknown;
  query?: QueryParams;
  scope?: ApiAccessScope;
}

interface ApiErrorOptions {
  bodyText: string;
  path: string;
  scope: ApiAccessScope;
  status: number;
}

export class ApiError extends Error {
  readonly bodyText: string;
  readonly path: string;
  readonly scope: ApiAccessScope;
  readonly status: number;

  constructor(message: string, options: ApiErrorOptions) {
    super(message);
    this.name = "ApiError";
    this.bodyText = options.bodyText;
    this.path = options.path;
    this.scope = options.scope;
    this.status = options.status;
  }
}

export interface SessionCorruptDetail {
  sessionId: string;
  quarantinePath: string;
  message: string;
}

/**
 * Returns the structured "session_corrupt" payload when *error* is a 422
 * response from a session endpoint, otherwise null. Drives the user-visible
 * "session corrupt" notice in the UI.
 */
export function getSessionCorruptDetail(
  error: unknown
): SessionCorruptDetail | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const text = error.bodyText.trim();
  if (!text) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  const detail =
    parsed && typeof parsed === "object" && "detail" in parsed
      ? (parsed as { detail?: unknown }).detail
      : parsed;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const record = detail as Record<string, unknown>;
  if (record.error !== "session_corrupt") return null;
  const sessionId = typeof record.session_id === "string" ? record.session_id : "";
  const quarantinePath =
    typeof record.quarantine_path === "string" ? record.quarantine_path : "";
  const message =
    typeof record.message === "string" && record.message.trim()
      ? record.message
      : "The saved session file was corrupt and has been quarantined.";
  return { sessionId, quarantinePath, message };
}

export function isSessionCorruptError(error: unknown): boolean {
  return getSessionCorruptDetail(error) !== null;
}

let apiAuthProvider: ApiAuthProvider | null = null;

export function setApiAuthProvider(provider: ApiAuthProvider | null): void {
  apiAuthProvider = provider;
}

export function resolveBearerToken(scope: ApiAccessScope): string | null {
  const auth = apiAuthProvider?.();
  if (!auth) return null;
  switch (scope) {
    case "inspection":
      return auth.inspectionBearerToken ?? null;
    case "execution":
      return auth.executionBearerToken ?? null;
    case "admin":
      return auth.adminBearerToken ?? null;
    case "public":
      return null;
  }
}

function buildApiUrl(path: string, query?: QueryParams): string {
  const url = new URL(path, getBase());
  const searchParams = new URLSearchParams(url.search);
  Object.entries(query ?? {}).forEach(([key, rawValue]) => {
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    values.forEach((value) => {
      if (value === undefined || value === null) return;
      searchParams.append(key, String(value));
    });
  });
  url.search = searchParams.toString();
  return url.toString();
}

function buildHeaders(
  scope: ApiAccessScope,
  headersInit: HeadersInit | undefined,
  hasJsonBody: boolean
): Headers {
  const headers = new Headers(headersInit);
  if (hasJsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = resolveBearerToken(scope);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function apiFetch(
  path: string,
  options: ApiRequestOptions = {}
): Promise<Response> {
  const { body, headers, jsonBody, query, scope = "inspection", ...requestInit } = options;
  return fetch(buildApiUrl(path, query), {
    ...requestInit,
    body: jsonBody === undefined ? body : JSON.stringify(jsonBody),
    headers: buildHeaders(scope, headers, jsonBody !== undefined),
  });
}

function extractApiErrorMessage(bodyText: string, status: number, statusText: string): string {
  const trimmed = bodyText.trim();
  if (trimmed) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (typeof parsed === "string" && parsed.trim()) return parsed.trim();
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const detail = (parsed as { detail?: unknown }).detail;
        if (typeof detail === "string" && detail.trim()) return detail.trim();
        if (detail !== undefined) return JSON.stringify(detail);
      }
    } catch {
      return trimmed;
    }
    return trimmed;
  }
  const fallbackStatusText = statusText.trim();
  return fallbackStatusText ? `HTTP ${status}: ${fallbackStatusText}` : `HTTP ${status}`;
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function getApiErrorBodyText(error: unknown): string {
  if (error instanceof ApiError) return error.bodyText.trim();
  if (error instanceof Error) return error.message.trim();
  return "";
}

export function getApiErrorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

async function throwForFailedResponse(
  response: Response,
  path: string,
  scope: ApiAccessScope
): Promise<void> {
  if (response.ok) return;
  const text = await response.text().catch(() => response.statusText);
  throw new ApiError(extractApiErrorMessage(text, response.status, response.statusText), {
    bodyText: text,
    path,
    scope,
    status: response.status,
  });
}

async function req<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const scope = options.scope ?? "inspection";
  const response = await apiFetch(path, options);
  await throwForFailedResponse(response, path, scope);
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw createPayloadError(path, "the requested data", "Expected valid JSON from the backend.");
  }
}

const inspectReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "inspection" });

const executeReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "execution" });

const inspectFetch = (path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  apiFetch(path, { ...options, scope: "inspection" });

const executeFetch = (path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  apiFetch(path, { ...options, scope: "execution" });

export const getHealth = (signal?: AbortSignal) =>
  req<{ status: string; service: string }>("/", {
    cache: "no-store",
    scope: "public",
    signal,
  });

export const probeAccess = (scope: ProtectedApiAccessScope) =>
  req<AccessProbeResponse>("/api/access/probe", {
    cache: "no-store",
    query: { scope },
    scope,
  });

// Inspection routes

export const listSessions = async () =>
  validateSessionList(await inspectReq<unknown>("/api/sessions"), "/api/sessions");

export const getHistory = async (id: string) =>
  validateSessionHistory(
    await inspectReq<unknown>(`/api/sessions/${id}/history`),
    `/api/sessions/${id}/history`
  );

export const getSessionContinuity = async (id: string) =>
  validateSessionContinuity(
    await inspectReq<unknown>(`/api/sessions/${id}/continuity`),
    `/api/sessions/${id}/continuity`
  );

export const getSessionArchive = async (id: string, archiveId: string) =>
  validateSessionHistory(
    await inspectReq<unknown>(`/api/sessions/${id}/archives/${archiveId}`),
    `/api/sessions/${id}/archives/${archiveId}`
  );

export const readFile = async (path: string) =>
  validateFileContentsResponse(
    await inspectReq<unknown>("/api/files", { query: { path } }),
    "/api/files"
  );

export const getSessionTokens = async (id: string) =>
  validateTokenStats(
    await inspectReq<unknown>(`/api/tokens/session/${id}`),
    `/api/tokens/session/${id}`
  );

// Raw file routes

export const fetchRawFile = (path: string, signal?: AbortSignal) =>
  inspectFetch("/api/files/raw", { cache: "no-store", query: { path }, signal });

export const readRawFileText = async (
  path: string,
  signal?: AbortSignal
): Promise<RawFileTextResponse> => {
  const response = await fetchRawFile(path, signal);
  await throwForFailedResponse(response, "/api/files/raw", "inspection");
  return {
    path,
    content: await response.text(),
    contentType: response.headers.get("content-type"),
  };
};

export interface RawFileBlobResponse {
  path: string;
  contentType: string | null;
  blob: Blob;
}

export interface RawFileObjectUrl {
  path: string;
  contentType: string | null;
  url: string;
  revoke: () => void;
}

export const readRawFileBlob = async (
  path: string,
  signal?: AbortSignal
): Promise<RawFileBlobResponse> => {
  const response = await fetchRawFile(path, signal);
  await throwForFailedResponse(response, "/api/files/raw", "inspection");
  return {
    path,
    blob: await response.blob(),
    contentType: response.headers.get("content-type"),
  };
};

export const createRawFileObjectUrl = async (
  path: string,
  signal?: AbortSignal
): Promise<RawFileObjectUrl> => {
  const { blob, contentType } = await readRawFileBlob(path, signal);
  const url = URL.createObjectURL(blob);
  return { path, contentType, url, revoke: () => URL.revokeObjectURL(url) };
};

export const getRawFileUrl = (path: string) => buildApiUrl("/api/files/raw", { path });

export { openRawFileInNewTab } from "./raw-file-popup";

// Execution routes

export const createSession = () =>
  executeReq<Session>("/api/sessions", { method: "POST" });

export const renameSession = (id: string, title: string) =>
  executeReq<Session>(`/api/sessions/${id}`, { jsonBody: { title }, method: "PUT" });

export const generateSessionTitle = (id: string) =>
  executeReq<{ session_id: string; title: string }>(
    `/api/sessions/${id}/generate-title`,
    { method: "POST" }
  );

export const deleteSession = (id: string) =>
  executeReq<void>(`/api/sessions/${id}`, { method: "DELETE" });

export const saveFile = (path: string, content: string) =>
  executeReq<FileSaveResponse>("/api/files", {
    jsonBody: { content, path },
    method: "POST",
  });

export interface ApprovalDecisionPayload {
  session_id: string;
  run_id: string;
  tool_name: string;
  decision: "approve" | "deny";
  actor?: string;
  rationale?: string | null;
}

export interface ApprovalDecisionResponse {
  recorded: boolean;
  session_id: string;
  run_id: string;
  tool_name: string;
  decision: "approve" | "deny";
  actor: string;
  recorded_at: string;
}

export const submitApprovalDecision = (payload: ApprovalDecisionPayload) =>
  executeReq<ApprovalDecisionResponse>("/api/chat/approval", {
    jsonBody: payload,
    method: "POST",
  });

// Chat streaming (custom SSE parser — POST-based)

export interface StreamChatOptions {
  /**
   * Optional client-side correlation id for this turn. Surfaces on the
   * optimistic assistant message and on synthetic error events so a retry can
   * be paired with its original attempt. The backend still mints its own
   * per-turn request_id; this override is not forwarded in the request body.
   */
  requestId?: string;
  /**
   * Cap on the SSE parser's unterminated buffered remainder. Defaults to the
   * parser's own default (4 MB). When exceeded, a synthetic
   * `stream_overflow` event is dispatched and the reader is cancelled.
   */
  maxBufferBytes?: number;
}

export async function streamChat(
  message: string,
  sessionId: string,
  callbacks: StreamCallbacks,
  options: StreamChatOptions = {}
): Promise<void> {
  const response = await executeFetch("/api/chat", {
    jsonBody: { message, session_id: sessionId },
    method: "POST",
    signal: callbacks.signal,
    headers: {
      "X-Runtime-Event-Schema-Version": String(RUNTIME_EVENT_SCHEMA_VERSION),
    },
  });

  const dispatcher = createChatStreamDispatcher(callbacks, {
    expectedRequestId: options.requestId,
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => response.statusText);
    const errorMessage = extractApiErrorMessage(text, response.status, response.statusText);
    log.error({
      event: "sse_stream_open_failed",
      message: errorMessage,
      requestId: options.requestId,
      sessionId,
      meta: { status: response.status },
    });
    const errorEvent: ChatStreamErrorEvent = {
      type: "error",
      error: errorMessage,
      request_id: options.requestId,
    };
    dispatcher.dispatch(errorEvent);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parseOptions = { maxBufferBytes: options.maxBufferBytes };
  let buffer = "";
  let aborted = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const parsed = parseChatStreamChunk(
        buffer,
        decoder.decode(value, { stream: true }),
        parseOptions
      );
      buffer = parsed.bufferedRemainder;
      for (const event of parsed.events) dispatcher.dispatch(event);
      if (parsed.overflow) {
        log.error({
          event: "sse_stream_overflow",
          message: "SSE buffered remainder exceeded the cap; stream cancelled.",
          requestId: dispatcher.lastRequestId() ?? options.requestId,
          sessionId,
          meta: {
            buffered_bytes: parsed.overflow.bufferedBytes,
            max_buffer_bytes: parsed.overflow.maxBufferBytes,
          },
        });
        dispatcher.dispatch({
          type: "stream_overflow",
          bufferedBytes: parsed.overflow.bufferedBytes,
          maxBufferBytes: parsed.overflow.maxBufferBytes,
          request_id: dispatcher.lastRequestId() ?? options.requestId,
        });
        buffer = "";
        aborted = true;
        await reader.cancel().catch(() => undefined);
        break;
      }
    }

    if (!aborted) {
      const finalParsed = parseChatStreamChunk(buffer, decoder.decode(), {
        ...parseOptions,
        flush: true,
      });
      buffer = finalParsed.bufferedRemainder;
      for (const event of finalParsed.events) dispatcher.dispatch(event);

      if (!dispatcher.sawTerminalEvent()) {
        const truncationMessage = "The response stream closed before completion.";
        log.error({
          event: "sse_stream_truncated",
          message: truncationMessage,
          requestId: dispatcher.lastRequestId() ?? options.requestId,
          sessionId,
        });
        dispatcher.dispatch({
          type: "error",
          error: truncationMessage,
          request_id: dispatcher.lastRequestId() ?? options.requestId,
        });
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // The reader may already be released (e.g. after an overflow-driven
      // cancel() resolves). Swallow so teardown cannot mask the primary flow.
    }
  }
}
