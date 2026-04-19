/**
 * Client-side telemetry logger.
 *
 * Small, typed wrapper that ships unhandled frontend errors and SSE
 * transport failures to the backend audit log through
 * `POST /api/audit/client`. Callers are the React `ErrorBoundary`
 * (which reports whatever React catches in `componentDidCatch`) and the
 * SSE stream consumer in `api.ts` (which reports `stream_overflow` /
 * terminal `error` events). Nothing about this module is user-visible —
 * the goal is to stop dropping production errors on the floor.
 *
 * PII scrub policy (enforced here before the request is sent):
 *   - URLs have their query string and fragment removed — bearer tokens,
 *     identifiers, and search params routinely land in URLs and those
 *     should never leave the browser.
 *   - `message` is trimmed and hard-capped at MAX_MESSAGE_CHARS so a
 *     hostile error message cannot act as an exfil channel.
 *   - `stack` is split into frames; frames that resolve to a file path
 *     outside the workspace (i.e. not a webpack/next/app chunk served by
 *     the BioAPEX frontend) are dropped. This strips OS usernames and
 *     local directory layouts that some browsers include in stacks.
 *   - `meta` is shallow-copied. String values get the same scrub as
 *     `message`; any key whose name looks secret-ish (`token`, `password`,
 *     `auth`, `cookie`, `secret`) is redacted.
 *   - We never include the full `document.cookie`, query string of
 *     `window.location`, or raw request bodies. Callers must not pass them.
 *
 * Transport behaviour:
 *   - Fire-and-forget. We never throw from `log.error` and we never let
 *     a telemetry failure surface to the user — a broken logger must not
 *     mask the original error.
 *   - Uses `keepalive: true` so events issued during `beforeunload` still
 *     reach the backend.
 *   - Hard cooldown on repeated backend 429s: once the backend tells us
 *     to back off we stop sending for the rest of the session to avoid
 *     DoS-ing our own audit log on a stuck retry loop.
 */

const ENDPOINT_PATH = "/api/audit/client";
const MAX_MESSAGE_CHARS = 500;
const MAX_STACK_CHARS = 4_000;
const MAX_META_VALUE_CHARS = 1_000;
const MAX_META_KEYS = 24;

const SECRET_META_KEY_PATTERN = /(token|password|auth|cookie|secret|api[_-]?key)/i;

export type TelemetryLevel = "error" | "warning";

export interface TelemetryMeta {
  [key: string]: unknown;
}

export interface TelemetryEventInput {
  /** Short, machine-friendly event identifier, e.g. `"error_boundary"`. */
  event: string;
  /** Human-readable summary of what went wrong. Truncated if very long. */
  message?: string;
  /** Optional stack; file paths outside the frontend chunk are stripped. */
  stack?: string;
  /** Extra context. Values are scrubbed; secret-looking keys are redacted. */
  meta?: TelemetryMeta;
  /** Correlation id for the turn, if known. */
  requestId?: string;
  /** Session id, if the telemetry is tied to a chat session. */
  sessionId?: string;
}

interface TelemetryEnvelope {
  level: TelemetryLevel;
  event: string;
  message?: string;
  stack?: string;
  meta?: TelemetryMeta;
  request_id?: string;
  session_id?: string;
  user_agent?: string;
}

export interface Logger {
  error: (event: string | TelemetryEventInput, meta?: TelemetryMeta) => void;
  warn: (event: string | TelemetryEventInput, meta?: TelemetryMeta) => void;
}

let globallyDisabled = false;

function resolveEndpoint(): string {
  if (typeof window === "undefined") {
    return `http://localhost:8002${ENDPOINT_PATH}`;
  }
  return `http://${window.location.hostname}:8002${ENDPOINT_PATH}`;
}

function scrubUrl(value: string): string {
  try {
    const url = new URL(value, "http://placeholder.invalid");
    url.search = "";
    url.hash = "";
    if (url.origin === "http://placeholder.invalid") {
      return url.pathname;
    }
    return url.toString();
  } catch {
    return truncate(value.split("?")[0].split("#")[0], MAX_META_VALUE_CHARS);
  }
}

function truncate(value: string, maxChars: number): string {
  if (value.length <= maxChars) return value;
  return value.slice(0, Math.max(0, maxChars - 16)).trimEnd() + "...[truncated]";
}

function scrubMessage(message: string | undefined): string | undefined {
  if (!message) return undefined;
  const cleaned = message.trim();
  if (!cleaned) return undefined;
  // Strip inline URLs by collapsing them to their origin+path.
  const withoutUrls = cleaned.replace(
    /\bhttps?:\/\/[^\s<>"']+/gi,
    (match) => scrubUrl(match)
  );
  return truncate(withoutUrls, MAX_MESSAGE_CHARS);
}

function isWorkspaceFrame(frame: string): boolean {
  // Keep frames that come from the app bundle; drop frames that reveal
  // the user's local filesystem layout. In dev Next.js surfaces webpack
  // module paths like `webpack-internal:///./src/...`; in prod it surfaces
  // `/_next/static/chunks/...`. We also keep bare anonymous frames.
  if (!frame.includes("(") && !frame.includes("@")) return true;
  if (/webpack-internal:/.test(frame)) return true;
  if (/\/_next\//.test(frame)) return true;
  if (/\/__tests__\//.test(frame)) return true;
  if (/\/src\//.test(frame)) return true;
  // Absolute filesystem paths and file:// urls leak usernames — drop.
  if (/\bfile:\/\//.test(frame)) return false;
  if (/\((?:\/|[A-Za-z]:\\)/.test(frame)) return false;
  return true;
}

function scrubStack(stack: string | undefined): string | undefined {
  if (!stack) return undefined;
  const lines = stack.split("\n").map((line) => line.trim()).filter(Boolean);
  const kept = lines.filter(isWorkspaceFrame);
  if (kept.length === 0) return undefined;
  return truncate(kept.join("\n"), MAX_STACK_CHARS);
}

function scrubMeta(meta: TelemetryMeta | undefined): TelemetryMeta | undefined {
  if (!meta) return undefined;
  const out: TelemetryMeta = {};
  let count = 0;
  for (const [key, value] of Object.entries(meta)) {
    if (count >= MAX_META_KEYS) {
      out._meta_truncated = true;
      break;
    }
    count += 1;
    if (SECRET_META_KEY_PATTERN.test(key)) {
      out[key] = "[redacted]";
      continue;
    }
    if (value === null || value === undefined) {
      out[key] = value ?? null;
      continue;
    }
    if (typeof value === "string") {
      const looksLikeUrl = /^https?:\/\//i.test(value);
      const scrubbed = looksLikeUrl ? scrubUrl(value) : scrubMessage(value);
      out[key] = scrubbed ?? "";
      continue;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      out[key] = value;
      continue;
    }
    // For objects / arrays, JSON-stringify then truncate. Avoids shipping
    // arbitrary nested structures that may carry PII.
    try {
      out[key] = truncate(JSON.stringify(value), MAX_META_VALUE_CHARS);
    } catch {
      out[key] = "[unserializable]";
    }
  }
  return out;
}

function scrubUserAgent(): string | undefined {
  if (typeof navigator === "undefined") return undefined;
  const ua = navigator.userAgent;
  if (!ua) return undefined;
  return truncate(ua, MAX_META_VALUE_CHARS);
}

function normalizeInput(
  input: string | TelemetryEventInput,
  meta: TelemetryMeta | undefined
): TelemetryEventInput {
  if (typeof input === "string") {
    return { event: input, meta };
  }
  if (meta && !input.meta) {
    return { ...input, meta };
  }
  if (meta && input.meta) {
    return { ...input, meta: { ...input.meta, ...meta } };
  }
  return input;
}

function buildEnvelope(
  level: TelemetryLevel,
  input: TelemetryEventInput
): TelemetryEnvelope {
  return {
    level,
    event: truncate(input.event.trim() || "unknown", 80),
    message: scrubMessage(input.message),
    stack: scrubStack(input.stack),
    meta: scrubMeta(input.meta),
    request_id: input.requestId ? truncate(input.requestId, 64) : undefined,
    session_id: input.sessionId ? truncate(input.sessionId, 64) : undefined,
    user_agent: scrubUserAgent(),
  };
}

async function send(envelope: TelemetryEnvelope): Promise<void> {
  if (globallyDisabled) return;
  if (typeof fetch === "undefined") return;
  try {
    const response = await fetch(resolveEndpoint(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(envelope),
      keepalive: true,
    });
    if (response.status === 429) {
      // Backend has asked us to back off — stop flooding it for the
      // remainder of the session. A page refresh clears this flag.
      globallyDisabled = true;
    }
  } catch {
    // Never let telemetry failures surface. Dropping the event is safer
    // than recursively logging our own logging failure.
  }
}

function emit(
  level: TelemetryLevel,
  input: string | TelemetryEventInput,
  meta: TelemetryMeta | undefined
): void {
  const envelope = buildEnvelope(level, normalizeInput(input, meta));
  void send(envelope);
}

export const logger: Logger = {
  error(event, meta) {
    emit("error", event, meta);
  },
  warn(event, meta) {
    emit("warning", event, meta);
  },
};

export const log = logger;

// Test-only hooks. Not exported from the public entry point but importable
// from tests to reset internal state between cases.
export function __resetTelemetryForTests(): void {
  globallyDisabled = false;
}

export function __scrubForTests(
  level: TelemetryLevel,
  input: TelemetryEventInput
): TelemetryEnvelope {
  return buildEnvelope(level, input);
}
