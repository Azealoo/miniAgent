import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  parseRuntimeEvent,
  RUNTIME_EVENT_SCHEMAS,
  RUNTIME_EVENT_TYPES,
  RUNTIME_EVENT_SCHEMA_VERSION,
} from "./runtime-events";

interface BackendPropertySchema {
  default?: unknown;
  anyOf?: unknown;
}

interface BackendDefSchema {
  additionalProperties?: boolean;
  properties: Record<string, BackendPropertySchema>;
  required?: string[];
}

interface BackendSchema {
  $defs: Record<string, BackendDefSchema>;
  discriminator: { propertyName: string; mapping: Record<string, string> };
  oneOf: Array<{ $ref: string }>;
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCHEMA_PATH = path.resolve(
  HERE,
  "../../../backend/runtime/events.schema.json"
);

function loadBackendSchema(): BackendSchema {
  const raw = readFileSync(SCHEMA_PATH, "utf-8");
  return JSON.parse(raw) as BackendSchema;
}

function minimalPayloadFor(eventType: string): Record<string, unknown> {
  switch (eventType) {
    case "retrieval":
      return { type: "retrieval", query: "q", results: [] };
    case "token":
      return { type: "token", content: "hello" };
    case "tool_start":
      return {
        type: "tool_start",
        tool: "read_file",
        input: "memory/MEMORY.md",
        run_id: "run-1",
      };
    case "tool_end":
      return {
        type: "tool_end",
        tool: "read_file",
        output: "ok",
        run_id: "run-1",
      };
    case "tool_awaiting_approval":
      return {
        type: "tool_awaiting_approval",
        tool: "terminal",
        input: "rm -rf /",
        run_id: "run-2",
        reason: "requires_approval",
        message: "Approve this destructive command before it runs.",
      };
    case "tool_chunk":
      return {
        type: "tool_chunk",
        tool: "terminal",
        run_id: "run-2",
        chunk_index: 0,
        chunk: "partial output...",
        terminal: false,
      };
    case "plan_created":
      return {
        type: "plan_created",
        summary: "planned",
        plan: { steps: [] },
      };
    case "plan_updated":
      return {
        type: "plan_updated",
        summary: "refined",
        plan: { steps: [] },
      };
    case "verification_result":
      return {
        type: "verification_result",
        summary: "looks good",
        verdict: "pass",
        verification: { verdict: "pass" },
      };
    case "new_response":
      return { type: "new_response" };
    case "compaction_event":
      return {
        type: "compaction_event",
        from_turn: 1,
        to_turn: 4,
        summary: "Compacted early turns.",
        saved_tokens: 1200,
      };
    case "done":
      return { type: "done", content: "final answer" };
    case "error":
      return { type: "error", error: "boom" };
    default:
      throw new Error(`No minimal payload defined for ${eventType}`);
  }
}

describe("runtime-events zod schemas", () => {
  it("covers every event type listed in the backend JSON schema snapshot", () => {
    const backend = loadBackendSchema();
    const backendTypes = Object.keys(backend.discriminator.mapping).sort();
    const frontendTypes = [...RUNTIME_EVENT_TYPES].sort();
    expect(frontendTypes).toEqual(backendTypes);
  });

  it.each(RUNTIME_EVENT_TYPES)(
    "accepts a minimal valid payload for %s",
    (eventType) => {
      const payload = minimalPayloadFor(eventType);
      const result = parseRuntimeEvent(payload);
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.event.type).toBe(eventType);
        expect(result.event.schema_version).toBe(RUNTIME_EVENT_SCHEMA_VERSION);
      }
    }
  );

  it.each(RUNTIME_EVENT_TYPES)(
    "rejects unknown fields on %s (strict mode mirrors pydantic extra='forbid')",
    (eventType) => {
      const payload = {
        ...minimalPayloadFor(eventType),
        mystery: "should be rejected",
      };
      const result = parseRuntimeEvent(payload);
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error).toMatch(/mystery|Unrecognized/i);
      }
    }
  );

  it("matches backend required-field expectations for every event type", () => {
    const backend = loadBackendSchema();
    for (const eventType of RUNTIME_EVENT_TYPES) {
      const defName = backend.discriminator.mapping[eventType]?.split("/").pop();
      expect(defName).toBeDefined();
      const def = backend.$defs[defName!];
      expect(def).toBeDefined();
      const required = def.required ?? [];
      for (const field of required) {
        const broken: Record<string, unknown> = {
          ...minimalPayloadFor(eventType),
        };
        delete broken[field];
        const result = parseRuntimeEvent(broken);
        expect(
          result.ok,
          `${eventType} should reject payloads missing required field ${field}`
        ).toBe(false);
      }
    }
  });

  it("accepts transport envelope fields (request_id, event_index)", () => {
    const payload = {
      type: "token" as const,
      content: "hi",
      request_id: "req-1",
      event_index: 3,
      schema_version: RUNTIME_EVENT_SCHEMA_VERSION,
    };
    const result = parseRuntimeEvent(payload);
    expect(result.ok).toBe(true);
    if (result.ok && result.event.type === "token") {
      expect(result.event.request_id).toBe("req-1");
      expect(result.event.event_index).toBe(3);
    }
  });

  it("returns a parse error for wholly malformed payloads", () => {
    const result = parseRuntimeEvent({ type: "nonexistent", foo: "bar" });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.length).toBeGreaterThan(0);
    }
  });

  it("exposes a zod schema for every runtime event type", () => {
    for (const eventType of RUNTIME_EVENT_TYPES) {
      const schema = RUNTIME_EVENT_SCHEMAS[eventType];
      expect(schema, `${eventType} has a zod schema`).toBeDefined();
      const parsed = schema.safeParse(minimalPayloadFor(eventType));
      expect(parsed.success).toBe(true);
    }
  });
});
