/**
 * Runtime validators for `/api` JSON payloads.
 *
 * The backend owns the schema, but the frontend still validates the shape of
 * every response it hands off to the UI so a typo or missing field surfaces as
 * a typed `ApiPayloadError` instead of an unreadable `undefined.map(...)` deep
 * in a component.
 */

import type {
  FileContentsResponse,
  Session,
  SessionContinuityResponse,
  SessionContinuitySummary,
  SessionHistoryMessage,
  TokenStats,
} from "./types";

interface ApiPayloadErrorOptions {
  detail: string;
  path: string;
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

export function isApiPayloadError(error: unknown): error is ApiPayloadError {
  return error instanceof ApiPayloadError;
}

export function createPayloadError(
  path: string,
  label: string,
  detail: string
): ApiPayloadError {
  return new ApiPayloadError(
    `BioAPEX received an unsupported response while loading ${label}. ${detail}`,
    { detail, path }
  );
}

type UnknownRecord = Record<string, unknown>;

function isObjectRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function expectObject(value: unknown, path: string, label: string): UnknownRecord {
  if (!isObjectRecord(value)) {
    throw createPayloadError(path, label, "Expected a JSON object from the backend.");
  }
  return value;
}

function expectArray(value: unknown, path: string, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw createPayloadError(path, label, "Expected a JSON array from the backend.");
  }
  return value;
}

function expectArrayField(
  value: UnknownRecord,
  field: string,
  path: string,
  label: string
): unknown[] {
  return expectArray(value[field], path, label);
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
    throw createPayloadError(path, label, `Expected "${field}" to be a string.`);
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
    throw createPayloadError(path, label, `Expected "${field}" to be a number.`);
  }
  return fieldValue;
}

export function validateSessionList(value: unknown, path: string): Session[] {
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
      case "approval_gate":
        expectStringField(record, "tool", path, blockLabel);
        expectStringField(record, "input", path, blockLabel);
        expectStringField(record, "run_id", path, blockLabel);
        expectStringField(record, "reason", path, blockLabel);
        expectStringField(record, "message", path, blockLabel);
        if ("result" in record && record.result != null && !isObjectRecord(record.result)) {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "result" to be an object when present.'
          );
        }
        if ("policy" in record && record.policy != null && !isObjectRecord(record.policy)) {
          throw createPayloadError(
            path,
            blockLabel,
            'Expected "policy" to be an object when present.'
          );
        }
        break;
      default:
        break;
    }
  });
}

export function validateSessionHistory(
  value: unknown,
  path: string
): SessionHistoryMessage[] {
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

export function validateSessionContinuity(
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

export function validateFileContentsResponse(
  value: unknown,
  path: string
): FileContentsResponse {
  const response = expectObject(value, path, "the file contents response");
  expectStringField(response, "path", path, "the file contents response");
  expectStringField(response, "content", path, "the file contents response");
  return response as unknown as FileContentsResponse;
}

export function validateTokenStats(value: unknown, path: string): TokenStats {
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
