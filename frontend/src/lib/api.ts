import type {
  AccessProbeResponse,
  ArtifactRegistryLookupResult,
  ArtifactRegistryQuery,
  ArtifactRegistrySnapshot,
  AuditEventsQuery,
  AuditEventsResponse,
  ConnectorActionRequest,
  ConnectorActionResult,
  ConnectorExecutionAction,
  ConnectorRegistryAdminDetailResponse,
  ConnectorRegistryEntry,
  ConnectorRegistryListResponse,
  ConnectorRegistryUpdateRequest,
  ConnectorRegistryUpdateResponse,
  ConnectorValidationRequest,
  FileContentsResponse,
  FileSaveResponse,
  FilesWorkspaceSummaryResponse,
  FlowsWorkspaceSummaryResponse,
  ObservabilityDashboardDefinitionsResponse,
  ObservabilityMetricsQuery,
  ObservabilityMetricsResponse,
  ObservabilityOverview,
  ObservabilityOverviewQuery,
  ObservabilityTracesQuery,
  ObservabilityTracesResponse,
  RagModeResponse,
  RawFileTextResponse,
  RetrievalResult,
  Session,
  SessionCompressionResponse,
  SessionHistoryMessage,
  SessionTitleResponse,
  Skill,
  SkillRegistryEntry,
  SkillRegistryUpdateRequest,
  SkillRegistryUpdateResponse,
  TokenStats,
  ToolResultEnvelope,
  WorkflowStreamEvent,
} from "./types";

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

  return response.json() as Promise<T>;
}

const inspectReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "inspection" });

const executeReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "execution" });

const adminReq = <T>(path: string, options: Omit<ApiRequestOptions, "scope"> = {}) =>
  req<T>(path, { ...options, scope: "admin" });

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

export const listSessions = () => inspectReq<Session[]>("/api/sessions");

export const getHistory = (id: string) =>
  inspectReq<SessionHistoryMessage[]>(`/api/sessions/${id}/history`);

export const getFlowsWorkspaceSummary = () =>
  inspectReq<FlowsWorkspaceSummaryResponse>("/api/sessions/workflows/summary");

export const getFilesWorkspaceSummary = (sessionId: string) =>
  inspectReq<FilesWorkspaceSummaryResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/files/summary`
  );

export const readFile = (path: string) =>
  inspectReq<FileContentsResponse>("/api/files", {
    query: { path },
  });

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

export const listSkills = () => inspectReq<Skill[]>("/api/skills");

export const listSkillsRegistry = () =>
  inspectReq<SkillRegistryEntry[]>("/api/skills/registry");

export const getSessionTokens = (id: string) =>
  inspectReq<TokenStats>(`/api/tokens/session/${id}`);

export const listArtifactRegistry = (query: ArtifactRegistryQuery = {}) =>
  inspectReq<ArtifactRegistryLookupResult>("/api/artifacts/registry", {
    query: { ...query },
  });

export const listAuditEvents = (query: AuditEventsQuery = {}) =>
  inspectReq<AuditEventsResponse>("/api/audit/events", {
    query: { ...query },
  });

export const listObservabilityMetrics = (
  query: ObservabilityMetricsQuery = {}
) =>
  inspectReq<ObservabilityMetricsResponse>("/api/observability/metrics", {
    query: { ...query },
  });

export const listObservabilityTraces = (
  query: ObservabilityTracesQuery = {}
) =>
  inspectReq<ObservabilityTracesResponse>("/api/observability/traces", {
    query: { ...query },
  });

export const getObservabilityOverview = (
  query: ObservabilityOverviewQuery = {}
) =>
  inspectReq<ObservabilityOverview>("/api/observability/overview", {
    query: { ...query },
  });

export const getObservabilityDashboardDefinitions = () =>
  inspectReq<ObservabilityDashboardDefinitionsResponse>(
    "/api/observability/dashboard-definitions"
  );

export const listConnectorRegistry = () =>
  inspectReq<ConnectorRegistryListResponse>("/api/connectors/registry");

export const getConnectorRegistryDetail = (connectorName: string) =>
  inspectReq<ConnectorRegistryEntry>(
    `/api/connectors/registry/${encodeURIComponent(connectorName)}`
  );

export const getConnectorRegistryAdminDetail = (connectorName: string) =>
  adminReq<ConnectorRegistryAdminDetailResponse>(
    `/api/connectors/registry/${encodeURIComponent(connectorName)}/admin-detail`
  );

// Execution routes

export const createSession = () =>
  executeReq<Session>("/api/sessions", { method: "POST" });

export const renameSession = (id: string, title: string) =>
  executeReq<Session>(`/api/sessions/${id}`, {
    jsonBody: { title },
    method: "PUT",
  });

export const deleteSession = (id: string) =>
  executeReq<void>(`/api/sessions/${id}`, { method: "DELETE" });

export const generateTitle = (id: string) =>
  executeReq<SessionTitleResponse>(`/api/sessions/${id}/generate-title`, {
    method: "POST",
  });

export const saveFile = (path: string, content: string) =>
  executeReq<FileSaveResponse>("/api/files", {
    jsonBody: { content, path },
    method: "POST",
  });

export const compressSession = (id: string) =>
  executeReq<SessionCompressionResponse>(`/api/sessions/${id}/compress`, {
    method: "POST",
  });

// Admin routes

export const getRagMode = () =>
  adminReq<RagModeResponse>("/api/config/rag-mode");

export const setRagMode = (enabled: boolean) =>
  adminReq<RagModeResponse>("/api/config/rag-mode", {
    jsonBody: { enabled },
    method: "PUT",
  });

export const rebuildArtifactRegistry = () =>
  adminReq<ArtifactRegistrySnapshot>("/api/artifacts/registry/rebuild", {
    method: "POST",
  });

export const updateConnectorRegistryEntry = (
  connectorName: string,
  body: ConnectorRegistryUpdateRequest
) =>
  adminReq<ConnectorRegistryUpdateResponse>(
    `/api/connectors/registry/${encodeURIComponent(connectorName)}`,
    {
      jsonBody: body,
      method: "PUT",
    }
  );

export const validateConnectorRegistryEntry = (
  connectorName: string,
  body?: ConnectorValidationRequest
) =>
  adminReq<ConnectorActionResult>(
    `/api/connectors/registry/${encodeURIComponent(connectorName)}/validate`,
    {
      jsonBody: body,
      method: "POST",
    }
  );

export const runConnectorRegistryAction = (
  connectorName: string,
  action: ConnectorExecutionAction,
  body?: ConnectorActionRequest
) =>
  adminReq<ConnectorActionResult>(
    `/api/connectors/registry/${encodeURIComponent(connectorName)}/actions/${action}`,
    {
      jsonBody: body,
      method: "POST",
    }
  );

export const updateSkillRegistryEntry = (
  skillName: string,
  body: SkillRegistryUpdateRequest
) =>
  adminReq<SkillRegistryUpdateResponse>(
    `/api/skills/registry/${encodeURIComponent(skillName)}`,
    {
      jsonBody: body,
      method: "PUT",
    }
  );

// Chat streaming (custom SSE parser — POST-based)

export interface StreamCallbacks {
  onRetrieval: (query: string, results: RetrievalResult[]) => void;
  onToken: (content: string) => void;
  onToolStart: (
    tool: string,
    input: string,
    runId: string,
    requestId?: string
  ) => void;
  onToolEnd: (
    tool: string,
    output: string,
    runId: string,
    result?: ToolResultEnvelope,
    requestId?: string
  ) => void;
  onWorkflowEvent: (event: WorkflowStreamEvent) => void;
  onNewResponse: () => void;
  onDone: (content: string, requestId?: string) => void;
  onTitle: (title: string) => void;
  onError: (error: string, requestId?: string) => void;
}

export interface ChatRequestContext {
  attachedIdentifiers?: string[];
  selectedWorkflow?: string | null;
}

export async function streamChat(
  message: string,
  sessionId: string,
  callbacks: StreamCallbacks,
  context?: ChatRequestContext
): Promise<void> {
  const response = await executeFetch("/api/chat", {
    jsonBody: {
      attached_identifiers: context?.attachedIdentifiers ?? [],
      message,
      selected_workflow: context?.selectedWorkflow ?? null,
      session_id: sessionId,
      stream: true,
    },
    method: "POST",
  });

  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => response.statusText);
    callbacks.onError(
      extractApiErrorMessage(text, response.status, response.statusText)
    );
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";

      for (const event of events) {
        for (const line of event.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            switch (data.type) {
              case "retrieval":
                callbacks.onRetrieval(data.query, data.results);
                break;
              case "token":
                callbacks.onToken(data.content);
                break;
              case "tool_start":
                callbacks.onToolStart(
                  data.tool,
                  data.input,
                  data.run_id ?? data.tool,
                  data.request_id
                );
                break;
              case "tool_end":
                callbacks.onToolEnd(
                  data.tool,
                  data.output,
                  data.run_id ?? data.tool,
                  data.result,
                  data.request_id
                );
                break;
              case "workflow_start":
              case "workflow_step_start":
              case "workflow_step_end":
              case "workflow_blocked":
              case "workflow_artifact":
              case "workflow_done":
                callbacks.onWorkflowEvent(data as WorkflowStreamEvent);
                break;
              case "new_response":
                callbacks.onNewResponse();
                break;
              case "done":
                callbacks.onDone(data.content ?? "", data.request_id);
                break;
              case "title":
                callbacks.onTitle(data.title);
                break;
              case "error":
                callbacks.onError(data.error ?? "Unknown error", data.request_id);
                break;
            }
          } catch {
            // Skip malformed lines
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
