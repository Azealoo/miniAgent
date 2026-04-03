import type {
  AccessProbeResponse,
  ChatStreamEvent,
  ChatStreamErrorEvent,
  ChatStreamPlanCreatedEvent,
  ChatStreamPlanUpdatedEvent,
  ChatStreamVerificationResultEvent,
  FileContentsResponse,
  FileSaveResponse,
  RawFileTextResponse,
  RetrievalResult,
  Session,
  SessionContinuityResponse,
  SessionContinuitySummary,
  SessionHistoryMessage,
  SkillRegistryEntry,
  TokenStats,
  ToolResultEnvelope,
} from "./types";
import { parseChatStreamChunk } from "./chat-stream-events";

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

interface ApiPayloadErrorOptions {
  detail: string;
  path: string;
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

export class ApiPayloadError extends Error {
  readonly detail: string;
  readonly path: string;

  constructor(message: string, options: ApiPayloadErrorOptions) {
    super(message);
    this.name = "ApiPayloadError";
    this.detail = options.detail;
    this.path = options.path;
  }
}

let apiAuthProvider: ApiAuthProvider | null = null;

export function setApiAuthProvider(provider: ApiAuthProvider | null): void {
  apiAuthProvider = provider;
}

function resolveBearerToken(scope: ApiAccessScope): string | null {
  const auth = apiAuthProvider?.();
  if (!auth) {
    return null;
  }

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
      if (value === undefined || value === null) {
        return;
      }
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
  const {
    body,
    headers,
    jsonBody,
    query,
    scope = "inspection",
    ...requestInit
  } = options;

  return fetch(buildApiUrl(path, query), {
    ...requestInit,
    body: jsonBody === undefined ? body : JSON.stringify(jsonBody),
    headers: buildHeaders(scope, headers, jsonBody !== undefined),
  });
}

function extractApiErrorMessage(
  bodyText: string,
  status: number,
  statusText: string
): string {
  const trimmed = bodyText.trim();
  if (trimmed) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (typeof parsed === "string" && parsed.trim()) {
        return parsed.trim();
      }
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const detail = (parsed as { detail?: unknown }).detail;
        if (typeof detail === "string" && detail.trim()) {
          return detail.trim();
        }
        if (detail !== undefined) {
          return JSON.stringify(detail);
        }
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

export function isApiPayloadError(error: unknown): error is ApiPayloadError {
  return error instanceof ApiPayloadError;
}

export function getApiErrorBodyText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.bodyText.trim();
  }
  if (error instanceof Error) {
    return error.message.trim();
  }
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
  if (response.ok) {
    return;
  }

  const text = await response.text().catch(() => response.statusText);
  throw new ApiError(
    extractApiErrorMessage(text, response.status, response.statusText),
    {
      bodyText: text,
      path,
      scope,
      status: response.status,
    }
  );
}

async function req<T>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const scope = options.scope ?? "inspection";
  const response = await apiFetch(path, options);
  await throwForFailedResponse(response, path, scope);

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return await response.json() as T;
  } catch {
    throw createPayloadError(
      path,
      "the requested data",
      "Expected valid JSON from the backend."
    );
  }
}

type UnknownRecord = Record<string, unknown>;

function createPayloadError(path: string, label: string, detail: string): ApiPayloadError {
  return new ApiPayloadError(
    `BioAPEX received an unsupported response while loading ${label}. ${detail}`,
    {
      detail,
      path,
    }
  );
}

function isObjectRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function expectObject(value: unknown, path: string, label: string): UnknownRecord {
  if (!isObjectRecord(value)) {
    throw createPayloadError(
      path,
      label,
      "Expected a JSON object from the backend."
    );
  }
  return value;
}

function expectArray(value: unknown, path: string, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw createPayloadError(
      path,
      label,
      "Expected a JSON array from the backend."
    );
  }
  return value;
}

function expectArrayField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): unknown[] {
  return expectArray(
    value[field],
    path,
    label,
  );
}

function expectStringArrayField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): string[] {
  const items = expectArrayField(value, field, path, label);
  items.forEach((item) => {
    if (typeof item !== "string") {
      throw createPayloadError(
        path,
        label,
        `Expected "${field}" to contain only strings.`
      );
    }
  });
  return items as string[];
}

function expectNullableStringField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): string | null {
  if (!(field in value)) {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be a string or null.`
    );
  }

  const fieldValue = value[field];
  if (fieldValue === null) {
    return null;
  }
  if (typeof fieldValue !== "string") {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be a string or null.`
    );
  }
  return fieldValue;
}

function expectNullableObjectField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): UnknownRecord | null {
  if (!(field in value)) {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be a JSON object or null.`
    );
  }

  const fieldValue = value[field];
  if (fieldValue === null) {
    return null;
  }
  return expectObject(
    fieldValue,
    path,
    label
  );
}

function expectObjectField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): UnknownRecord {
  return expectObject(value[field], path, label);
}

function expectStringField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): string {
  const fieldValue = value[field];
  if (typeof fieldValue !== "string") {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be a string.`
    );
  }
  return fieldValue;
}

function expectStringLiteralField<T extends string>(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string,
  allowed: readonly T[]
): T {
  const fieldValue = expectStringField(value, field, path, label);
  if (!(allowed as readonly string[]).includes(fieldValue)) {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be one of: ${allowed.join(", ")}.`
    );
  }
  return fieldValue as T;
}

function expectNumberField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): number {
  const fieldValue = value[field];
  if (typeof fieldValue !== "number" || Number.isNaN(fieldValue)) {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be a number.`
    );
  }
  return fieldValue;
}

function expectBooleanField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): boolean {
  const fieldValue = value[field];
  if (typeof fieldValue !== "boolean") {
    throw createPayloadError(
      path,
      label,
      `Expected "${field}" to be a boolean.`
    );
  }
  return fieldValue;
}

function validateSessionList(value: unknown, path: string): Session[] {
  const sessions = expectArray(value, path, "the saved session list");
  sessions.forEach((session, index) => {
    const record = expectObject(session, path, "the saved session list");
    expectStringField(record, "id", path, `session ${index + 1}`);
    expectStringField(record, "title", path, `session ${index + 1}`);
    expectNumberField(record, "updated_at", path, `session ${index + 1}`);
    expectNumberField(record, "message_count", path, `session ${index + 1}`);
  });
  return sessions as Session[];
}

function validateSessionContentBlocks(
  value: unknown,
  path: string,
  label: string
): void {
  const blocks = expectArray(value, path, label);
  blocks.forEach((block, index) => {
    const record = expectObject(block, path, label);
    const blockLabel = `${label} block ${index + 1}`;
    const blockType = expectStringField(record, "type", path, blockLabel);

    switch (blockType) {
      case "text":
        expectStringField(record, "text", path, blockLabel);
        break;
      case "tool_use":
        expectStringField(record, "tool", path, blockLabel);
        expectStringField(record, "input", path, blockLabel);
        if ("run_id" in record && typeof record.run_id !== "string") {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "run_id" to be a string when present.'
          );
        }
        break;
      case "tool_result":
        expectStringField(record, "tool", path, blockLabel);
        expectStringField(record, "output", path, blockLabel);
        if ("run_id" in record && typeof record.run_id !== "string") {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "run_id" to be a string when present.'
          );
        }
        if ("result" in record && !isObjectRecord(record.result)) {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "result" to be an object when present.'
          );
        }
        break;
      case "retrieval":
        expectArrayField(record, "results", path, blockLabel);
        if ("query" in record && typeof record.query !== "string") {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "query" to be a string when present.'
          );
        }
        break;
      case "usage":
        expectObjectField(record, "metadata", path, blockLabel);
        break;
      case "plan":
        expectStringLiteralField(record, "event", path, blockLabel, [
          "created",
          "updated",
        ] as const);
        expectStringField(record, "summary", path, blockLabel);
        expectObjectField(record, "plan", path, blockLabel);
        if ("run_id" in record && typeof record.run_id !== "string") {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "run_id" to be a string when present.'
          );
        }
        if ("tool_trace" in record && !Array.isArray(record.tool_trace)) {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "tool_trace" to be an array when present.'
          );
        }
        break;
      case "verification":
        expectStringLiteralField(record, "verdict", path, blockLabel, [
          "pass",
          "repair_required",
          "fail",
        ] as const);
        expectStringField(record, "summary", path, blockLabel);
        expectObjectField(record, "verification", path, blockLabel);
        if ("run_id" in record && typeof record.run_id !== "string") {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "run_id" to be a string when present.'
          );
        }
        if ("tool_trace" in record && !Array.isArray(record.tool_trace)) {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "tool_trace" to be an array when present.'
          );
        }
        break;
      default:
        break;
    }
  });
}

function validateSessionHistory(value: unknown, path: string): SessionHistoryMessage[] {
  const history = expectArray(value, path, "the session history");
  history.forEach((message, index) => {
    const record = expectObject(message, path, "the session history");
    expectStringField(record, "role", path, `session history item ${index + 1}`);
    if ("content" in record && typeof record.content !== "string") {
      throw createPayloadError(
        path,
        `session history item ${index + 1}`,
        'Expected "content" to be a string when present.'
      );
    }
    if ("blocks" in record) {
      validateSessionContentBlocks(
        record.blocks,
        path,
        `session history item ${index + 1}`
      );
    }
  });
  return history as SessionHistoryMessage[];
}

function validateSessionContinuitySummary(
  value: unknown,
  path: string,
  label: string
): SessionContinuitySummary {
  const summary = expectObject(value, path, label);
  expectStringField(summary, "source_format", path, label);
  if ("legacy_summary" in summary && summary.legacy_summary !== null) {
    expectStringField(summary, "legacy_summary", path, label);
  }
  expectArrayField(summary, "decisions_and_rationale", path, label);
  expectArrayField(summary, "results_register", path, label);
  expectArrayField(summary, "evidence_register", path, label);
  expectArrayField(summary, "compliance_register", path, label);
  expectArrayField(summary, "open_questions_and_next_actions", path, label);
  if ("archive_id" in summary && summary.archive_id !== null) {
    expectStringField(summary, "archive_id", path, label);
  }
  expectNumberField(summary, "archived_message_count", path, label);
  return summary as unknown as SessionContinuitySummary;
}

function validateSessionContinuity(
  value: unknown,
  path: string
): SessionContinuityResponse {
  const response = expectObject(value, path, "the session continuity response");
  const summaries = expectArrayField(
    response,
    "summaries",
    path,
    "the session continuity response"
  );
  summaries.forEach((summary, index) =>
    validateSessionContinuitySummary(
      summary,
      path,
      `session continuity summary ${index + 1}`
    )
  );
  return response as unknown as SessionContinuityResponse;
}

function validateFileContentsResponse(value: unknown, path: string): FileContentsResponse {
  const response = expectObject(value, path, "the file contents response");
  expectStringField(response, "path", path, "the file contents response");
  expectStringField(response, "content", path, "the file contents response");
  return response as unknown as FileContentsResponse;
}

function validateTokenStats(value: unknown, path: string): TokenStats {
  const response = expectObject(value, path, "the usage summary");
  expectStringField(response, "session_id", path, "the usage summary");
  expectStringField(response, "model_name", path, "the usage summary");
  expectStringLiteralField(
    response,
    "tokenizer_backend",
    path,
    "the usage summary",
    ["tiktoken_cl100k_base", "deterministic_fallback"] as const
  );
  expectStringLiteralField(
    response,
    "tokenizer_accuracy",
    path,
    "the usage summary",
    ["model_aligned", "approximate"] as const
  );
  return response as unknown as TokenStats;
}

function validateSkillRegistry(value: unknown, path: string): SkillRegistryEntry[] {
  return expectArray(value, path, "the skills registry") as SkillRegistryEntry[];
}

const inspectReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "inspection" });

const executeReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "execution" });

const inspectFetch = (
  path: string,
  options: Omit<ApiRequestOptions, "scope"> = {}
) => apiFetch(path, { ...options, scope: "inspection" });

const executeFetch = (
  path: string,
  options: Omit<ApiRequestOptions, "scope"> = {}
) => apiFetch(path, { ...options, scope: "execution" });

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
    await inspectReq<unknown>("/api/files", {
      query: { path },
    }),
    "/api/files"
  );

export const getSessionTokens = async (id: string) =>
  validateTokenStats(
    await inspectReq<unknown>(`/api/tokens/session/${id}`),
    `/api/tokens/session/${id}`
  );

export const fetchRawFile = (path: string, signal?: AbortSignal) =>
  inspectFetch("/api/files/raw", {
    cache: "no-store",
    query: { path },
    signal,
  });

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

const RAW_ACTIVE_CONTENT_EXTENSIONS = new Set([".htm", ".html", ".svg", ".xhtml"]);

function getPathExtension(path: string): string {
  const cleanPath = path.split("?")[0] ?? path;
  const index = cleanPath.lastIndexOf(".");
  return index >= 0 ? cleanPath.slice(index).toLowerCase() : "";
}

function shouldKeepRawOpenOffAppOrigin(path: string): boolean {
  return RAW_ACTIVE_CONTENT_EXTENSIONS.has(getPathExtension(path));
}

function rawFileName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts.at(-1) ?? "raw-file";
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function writePopupMessage(popup: Window, title: string, message: string): void {
  popup.document.title = title;
  popup.document.body.innerHTML =
    `<div style="font-family: sans-serif; padding: 16px; color: #334155;">${message}</div>`;
}

function renderAuthenticatedRawSourceView(
  popup: Window,
  path: string,
  content: string,
  contentType: string | null
): void {
  const downloadUrl = URL.createObjectURL(
    new Blob([content], {
      type: contentType ?? "text/plain; charset=utf-8",
    })
  );
  const cleanup = () => URL.revokeObjectURL(downloadUrl);
  popup.addEventListener("beforeunload", cleanup, { once: true });
  window.setTimeout(cleanup, 5 * 60_000);

  const escapedPath = escapeHtml(path);
  const escapedContent = escapeHtml(content);
  const escapedType = escapeHtml(contentType ?? "text/plain");
  const escapedName = escapeHtml(rawFileName(path));

  popup.document.open();
  popup.document.write(`<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Raw Source View</title>
    <style>
      :root {
        color-scheme: light;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      }
      body {
        margin: 0;
        background: #f4f5ef;
        color: #162116;
      }
      main {
        max-width: 1100px;
        margin: 0 auto;
        padding: 32px 20px 40px;
      }
      .panel {
        border: 1px solid rgba(179, 190, 176, 0.8);
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.96);
        box-shadow: 0 10px 28px rgba(29, 42, 33, 0.08);
        overflow: hidden;
      }
      .hero {
        padding: 22px 24px 18px;
        border-bottom: 1px solid rgba(214, 221, 212, 0.9);
        background: linear-gradient(180deg, rgba(246, 248, 241, 0.98), rgba(255, 255, 255, 0.98));
      }
      .eyebrow {
        margin: 0;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: #6b7280;
      }
      h1 {
        margin: 10px 0 0;
        font-size: 24px;
        line-height: 1.2;
      }
      p {
        margin: 12px 0 0;
        line-height: 1.6;
        color: #475569;
      }
      .meta {
        margin-top: 14px;
        font-size: 12px;
        color: #64748b;
        word-break: break-all;
      }
      .actions {
        display: flex;
        gap: 12px;
        align-items: center;
        margin-top: 18px;
      }
      .button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid rgba(35, 130, 83, 0.18);
        background: rgba(223, 242, 228, 0.92);
        color: #166534;
        font-size: 13px;
        font-weight: 700;
        text-decoration: none;
      }
      pre {
        margin: 0;
        padding: 24px;
        overflow: auto;
        background: #f8faf7;
        color: #1f2937;
        font: 12px/1.65 "IBM Plex Mono", "SFMono-Regular", monospace;
        white-space: pre-wrap;
        word-break: break-word;
      }
    </style>
  </head>
  <body>
    <main>
      <section class="panel">
        <div class="hero">
          <p class="eyebrow">Raw Source View</p>
          <h1>${escapedName}</h1>
          <p>
            Active raw content is shown as source here so authenticated opens do not mint a
            same-origin document inside the BioAPEX app.
          </p>
          <div class="meta">Path: ${escapedPath}<br />Content-Type: ${escapedType}</div>
          <div class="actions">
            <a class="button" href="${downloadUrl}" download="${escapedName}">Download Raw File</a>
          </div>
        </div>
        <pre>${escapedContent}</pre>
      </section>
    </main>
  </body>
</html>`);
  popup.document.close();
}

export const createRawFileObjectUrl = async (
  path: string,
  signal?: AbortSignal
): Promise<RawFileObjectUrl> => {
  const { blob, contentType } = await readRawFileBlob(path, signal);
  const url = URL.createObjectURL(blob);
  return {
    path,
    contentType,
    url,
    revoke: () => URL.revokeObjectURL(url),
  };
};

export const openRawFileInNewTab = async (path: string): Promise<void> => {
  if (typeof window === "undefined") {
    return;
  }

  if (shouldKeepRawOpenOffAppOrigin(path) && !resolveBearerToken("inspection")) {
    window.open(getRawFileUrl(path), "_blank", "noopener,noreferrer");
    return;
  }

  const popup = window.open("", "_blank");
  if (popup) {
    // Keep the synchronous popup for browser popup-blocker compatibility,
    // but sever opener access before any same-origin blob navigation occurs.
    popup.opener = null;
    writePopupMessage(popup, "Loading raw file", "Loading raw file...");
  }

  try {
    if (shouldKeepRawOpenOffAppOrigin(path)) {
      if (!popup || popup.closed) {
        throw new Error("Could not open a safe raw-source window.");
      }

      const { content, contentType } = await readRawFileText(path);
      renderAuthenticatedRawSourceView(popup, path, content, contentType);
      return;
    }

    const { url } = await createRawFileObjectUrl(path);
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);

    if (popup && !popup.closed) {
      popup.location.replace(url);
      return;
    }

    window.open(url, "_blank", "noopener,noreferrer");
  } catch (error) {
    if (popup && !popup.closed) {
      writePopupMessage(
        popup,
        "Raw file unavailable",
        '<span style="color: #991b1b;">Could not load the raw file.</span>'
      );
    }
    throw error;
  }
};

export const getRawFileUrl = (path: string) =>
  buildApiUrl("/api/files/raw", { path });

export const listSkillsRegistry = () =>
  inspectReq<unknown>("/api/skills/registry").then((payload) =>
    validateSkillRegistry(payload, "/api/skills/registry")
  );

// Execution routes

export const createSession = () =>
  executeReq<Session>("/api/sessions", { method: "POST" });

export const renameSession = (id: string, title: string) =>
  executeReq<Session>(`/api/sessions/${id}`, {
    jsonBody: { title },
    method: "PUT",
  });

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

// Chat streaming (custom SSE parser — POST-based)

export interface StreamCallbacks {
  signal?: AbortSignal;
  onEvent?: (event: ChatStreamEvent) => void;
  onRetrieval?: (query: string, results: RetrievalResult[]) => void;
  onToken?: (content: string) => void;
  onToolStart?: (
    tool: string,
    input: string,
    runId: string,
    requestId?: string
  ) => void;
  onToolEnd?: (
    tool: string,
    output: string,
    runId: string,
    result?: ToolResultEnvelope,
    requestId?: string
  ) => void;
  onPlanCreated?: (event: ChatStreamPlanCreatedEvent) => void;
  onPlanUpdated?: (event: ChatStreamPlanUpdatedEvent) => void;
  onVerificationResult?: (event: ChatStreamVerificationResultEvent) => void;
  onNewResponse?: () => void;
  onDone?: (content: string, requestId?: string) => void;
  onError?: (error: string, requestId?: string) => void;
}

export async function streamChat(
  message: string,
  sessionId: string,
  callbacks: StreamCallbacks
): Promise<void> {
  const response = await executeFetch("/api/chat", {
    jsonBody: {
      message,
      session_id: sessionId,
    },
    method: "POST",
    signal: callbacks.signal,
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => response.statusText);
    const errorEvent: ChatStreamErrorEvent = {
      type: "error",
      error: extractApiErrorMessage(text, response.status, response.statusText),
    };
    callbacks.onEvent?.(errorEvent);
    callbacks.onError?.(errorEvent.error, errorEvent.request_id);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let sawTerminalEvent = false;
  let lastRequestId: string | undefined;

  const dispatchEvent = (event: ChatStreamEvent) => {
    if (event.request_id) {
      lastRequestId = event.request_id;
    }
    if (event.type === "done" || event.type === "error") {
      sawTerminalEvent = true;
    }

    callbacks.onEvent?.(event);
    switch (event.type) {
      case "retrieval":
        callbacks.onRetrieval?.(event.query, event.results);
        break;
      case "token":
        callbacks.onToken?.(event.content);
        break;
      case "tool_start":
        callbacks.onToolStart?.(
          event.tool,
          event.input,
          event.run_id ?? event.tool,
          event.request_id
        );
        break;
      case "tool_end":
        callbacks.onToolEnd?.(
          event.tool,
          event.output,
          event.run_id ?? event.tool,
          event.result,
          event.request_id
        );
        break;
      case "plan_created":
        callbacks.onPlanCreated?.(event);
        break;
      case "plan_updated":
        callbacks.onPlanUpdated?.(event);
        break;
      case "verification_result":
        callbacks.onVerificationResult?.(event);
        break;
      case "new_response":
        callbacks.onNewResponse?.();
        break;
      case "done":
        callbacks.onDone?.(event.content, event.request_id);
        break;
      case "error":
        callbacks.onError?.(event.error, event.request_id);
        break;
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const parsed = parseChatStreamChunk(
        buffer,
        decoder.decode(value, { stream: true })
      );
      buffer = parsed.bufferedRemainder;

      for (const event of parsed.events) {
        dispatchEvent(event);
      }
    }

    const finalParsed = parseChatStreamChunk(buffer, decoder.decode(), {
      flush: true,
    });
    buffer = finalParsed.bufferedRemainder;
    for (const event of finalParsed.events) {
      dispatchEvent(event);
    }

    if (!sawTerminalEvent) {
      const errorEvent: ChatStreamErrorEvent = {
        type: "error",
        error: "The response stream closed before completion.",
        request_id: lastRequestId,
      };
      dispatchEvent(errorEvent);
    }
  } finally {
    reader.releaseLock();
  }
}
