/**
 * Backend → frontend TypeScript codegen.
 *
 * Reads the two committed JSON-schema snapshots and emits
 * ``frontend/src/lib/types.generated.ts``:
 *
 *   1. ``backend/codegen/shared_types.schema.json`` — tool-contract + session
 *      block DTOs (pydantic BaseModels + TypedDicts).
 *   2. ``backend/runtime/events.schema.json`` — the 13-variant discriminated
 *      union of runtime events.
 *
 * The committed ``types.generated.ts`` is the contract the hand-written
 * ``types.ts`` re-exports from. Two drift-guards enforce that nothing diverges
 * silently:
 *
 *   - ``backend/tests/test_shared_types_schema.py`` fails if the pydantic
 *     models drift from the committed JSON snapshot.
 *   - ``frontend/src/lib/types.generated.test.ts`` fails if the committed
 *     TypeScript file drifts from the generator output.
 *
 * Manual regeneration:
 *
 *   python -m codegen.shared_types            # from backend/
 *   npm run codegen:types                     # from frontend/
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* ------------------------------ Paths ---------------------------------- */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..");
const SHARED_SCHEMA_PATH = path.join(
  REPO_ROOT,
  "backend/codegen/shared_types.schema.json",
);
const EVENTS_SCHEMA_PATH = path.join(
  REPO_ROOT,
  "backend/runtime/events.schema.json",
);
const OUTPUT_PATH = path.join(
  REPO_ROOT,
  "frontend/src/lib/types.generated.ts",
);

/* ------------------------------ JSON Schema types ----------------------- */

interface JsonSchema {
  type?: string | string[];
  const?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  items?: JsonSchema | Record<string, never>;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  title?: string;
  description?: string;
  default?: unknown;
  [key: string]: unknown;
}

interface SharedTypesManifest {
  schema_version: number;
  models: Record<string, JsonSchema>;
  composites: Record<
    string,
    { kind: "union"; members: string[] }
  >;
}

interface RuntimeEventsSchema {
  $defs: Record<string, JsonSchema>;
  discriminator?: { propertyName: string; mapping: Record<string, string> };
  oneOf?: Array<{ $ref: string }>;
}

/* ------------------------------ Name mapping ---------------------------- */

// Keep generated types aligned with the frontend names that ``types.ts`` has
// used historically. The mapping is narrow: pydantic class name → exported TS
// name. Anything not in this map keeps its backend name verbatim.
const EVENT_NAME_MAP: Record<string, string> = {
  RetrievalRuntimeEvent: "ChatStreamRetrievalEvent",
  TokenRuntimeEvent: "ChatStreamTokenEvent",
  ToolStartRuntimeEvent: "ChatStreamToolStartEvent",
  ToolEndRuntimeEvent: "ChatStreamToolEndEvent",
  ToolAwaitingApprovalRuntimeEvent: "ChatStreamToolAwaitingApprovalEvent",
  ToolChunkRuntimeEvent: "ChatStreamToolChunkEvent",
  PlanCreatedRuntimeEvent: "ChatStreamPlanCreatedEvent",
  PlanUpdatedRuntimeEvent: "ChatStreamPlanUpdatedEvent",
  VerificationResultRuntimeEvent: "ChatStreamVerificationResultEvent",
  NewResponseRuntimeEvent: "ChatStreamNewResponseEvent",
  CompactionRuntimeEvent: "ChatStreamCompactionEvent",
  DoneRuntimeEvent: "ChatStreamDoneEvent",
  ErrorRuntimeEvent: "ChatStreamErrorEvent",
  WorkflowStepStartedRuntimeEvent: "ChatStreamWorkflowStepStartedEvent",
  WorkflowStepEndedRuntimeEvent: "ChatStreamWorkflowStepEndedEvent",
  WorkflowStepFailedRuntimeEvent: "ChatStreamWorkflowStepFailedEvent",
};

function mappedName(rawName: string, knownTopLevel: Set<string>): string {
  if (EVENT_NAME_MAP[rawName]) return EVENT_NAME_MAP[rawName];
  if (knownTopLevel.has(rawName)) return rawName;
  return rawName;
}

/* ------------------------------ Schema → TS type ------------------------ */

// These object-shape schemas encode the pydantic ``JsonLike`` alias (any JSON
// value, including nested). Collapsing them to the shared ``JsonValue`` type
// keeps the generated file readable and matches the hand-written shim.
function isJsonLikeAnyOf(schemas: JsonSchema[]): boolean {
  if (schemas.length < 5) return false;
  const keys = new Set(
    schemas.map((s) => {
      if (s.type === "null") return "null";
      if (s.type === "string") return "string";
      if (s.type === "integer" || s.type === "number") return "number";
      if (s.type === "boolean") return "boolean";
      if (s.type === "array") return "array";
      if (s.type === "object" && s.additionalProperties === true) return "object";
      return "other";
    }),
  );
  return (
    keys.has("object") &&
    keys.has("array") &&
    keys.has("string") &&
    keys.has("number") &&
    keys.has("boolean")
  );
}

function refToName(ref: string, knownTopLevel: Set<string>): string {
  const raw = ref.replace(/^#\/\$defs\//, "");
  return mappedName(raw, knownTopLevel);
}

function renderType(schema: JsonSchema, knownTopLevel: Set<string>): string {
  if (schema.$ref) {
    return refToName(schema.$ref, knownTopLevel);
  }

  if (schema.const !== undefined) {
    return JSON.stringify(schema.const);
  }

  if (schema.enum) {
    return schema.enum.map((v) => JSON.stringify(v)).join(" | ");
  }

  if (schema.anyOf || schema.oneOf) {
    const variants = (schema.anyOf ?? schema.oneOf) as JsonSchema[];
    if (isJsonLikeAnyOf(variants)) {
      return "JsonValue";
    }
    // ``exclude_none=True`` at the pydantic serializer means ``Optional[T]``
    // never becomes literal ``null`` on the wire — it's just absent. Treat
    // ``anyOf: [T, null]`` as ``T``; the optional ``?`` marker on the field
    // encodes the absence case for us.
    const nonNull = variants.filter((v) => v.type !== "null");
    const rendered = nonNull.map((v) => renderType(v, knownTopLevel));
    return Array.from(new Set(rendered)).join(" | ");
  }

  if (schema.type === "null") return "null";
  if (schema.type === "string") return "string";
  if (schema.type === "integer" || schema.type === "number") return "number";
  if (schema.type === "boolean") return "boolean";

  if (schema.type === "array") {
    const items = schema.items as JsonSchema | undefined;
    if (!items || Object.keys(items).length === 0) {
      return "JsonValue[]";
    }
    const inner = renderType(items, knownTopLevel);
    return inner.includes("|") ? `Array<${inner}>` : `${inner}[]`;
  }

  if (schema.type === "object") {
    if (
      schema.additionalProperties &&
      typeof schema.additionalProperties === "object"
    ) {
      const value = renderType(
        schema.additionalProperties as JsonSchema,
        knownTopLevel,
      );
      return `Record<string, ${value}>`;
    }
    if (schema.additionalProperties === true) {
      return "JsonObject";
    }
    if (schema.properties) {
      return renderInlineObject(schema, knownTopLevel);
    }
    return "JsonObject";
  }

  return "unknown";
}

function renderInlineObject(
  schema: JsonSchema,
  knownTopLevel: Set<string>,
): string {
  const required = new Set(schema.required ?? []);
  const props = schema.properties ?? {};
  const lines: string[] = ["{"];
  for (const key of Object.keys(props).sort()) {
    const field = props[key];
    const optional = !required.has(key);
    const type = renderType(field, knownTopLevel);
    lines.push(`    ${key}${optional ? "?" : ""}: ${type};`);
  }
  lines.push("  }");
  return lines.join("\n");
}

/* ------------------------------ Interface emission ---------------------- */

function emitInterface(
  name: string,
  schema: JsonSchema,
  knownTopLevel: Set<string>,
): string {
  const required = new Set(schema.required ?? []);
  const props = schema.properties ?? {};
  const lines: string[] = [];
  if (schema.description) {
    const lead = schema.description.split("\n")[0]?.trim() ?? "";
    if (lead) lines.push(`/** ${lead} */`);
  }
  lines.push(`export interface ${name} {`);
  for (const key of Object.keys(props).sort()) {
    const field = props[key];
    // Discriminator fields (those with a `const`) are always required even
    // when the backend emits them as optional-with-default. Without this,
    // TypeScript's discriminated-union narrowing breaks on ``block.type``.
    const isDiscriminator = field.const !== undefined;
    const optional = !isDiscriminator && !required.has(key);
    const type = renderType(field, knownTopLevel);
    lines.push(`  ${key}${optional ? "?" : ""}: ${type};`);
  }
  lines.push("}");
  return lines.join("\n");
}

/* ------------------------------ Top-level generate ---------------------- */

const HEADER = `/**
 * AUTO-GENERATED. Do not edit by hand.
 *
 * Produced by scripts/codegen-types.ts from:
 *   - backend/codegen/shared_types.schema.json
 *   - backend/runtime/events.schema.json
 *
 * Regenerate with:
 *   python -m codegen.shared_types             # from backend/
 *   npm run codegen:types                      # from frontend/
 */

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface JsonObject {
  [key: string]: JsonValue;
}
`;

interface GenerateInput {
  shared: SharedTypesManifest;
  events: RuntimeEventsSchema;
}

export function generateTypes({ shared, events }: GenerateInput): string {
  const sharedModels = shared.models;
  const eventDefs = events.$defs;

  // Top-level names are whatever we plan to emit at module scope. Properties
  // referencing ``$ref`` resolve against this set so envelopes point at
  // ToolArtifactRef / ToolResultError by name instead of inlining them.
  const topLevelNames = new Set<string>();
  for (const name of Object.keys(sharedModels)) topLevelNames.add(name);
  for (const rawName of Object.keys(eventDefs)) {
    topLevelNames.add(mappedName(rawName, new Set()));
  }

  const sections: string[] = [HEADER];

  // 1. Tool-contract + session block DTOs, in the order declared by the
  //    Python manifest (``_MODEL_SOURCES``). Each model is emitted once.
  sections.push("/* =========================================================");
  sections.push(" * Tool contracts and session content blocks");
  sections.push(" * source: backend/codegen/shared_types.schema.json");
  sections.push(" * ======================================================= */");
  for (const [name, schema] of Object.entries(sharedModels)) {
    sections.push(emitInterface(name, schema, topLevelNames));
  }

  // 2. Composite unions defined in the manifest (e.g. SessionContentBlock).
  for (const [name, composite] of Object.entries(shared.composites)) {
    if (composite.kind === "union") {
      const body = composite.members
        .map((m) => `  | ${m}`)
        .join("\n");
      sections.push(`export type ${name} =\n${body};`);
    }
  }

  // 3. Runtime events — each $def becomes a ChatStream*Event interface.
  sections.push("");
  sections.push("/* =========================================================");
  sections.push(" * Runtime events (SSE / streaming)");
  sections.push(" * source: backend/runtime/events.schema.json");
  sections.push(" * ======================================================= */");
  const eventTypeNames: string[] = [];
  for (const rawName of Object.keys(eventDefs).sort()) {
    const schema = eventDefs[rawName];
    const mapped = mappedName(rawName, topLevelNames);
    eventTypeNames.push(mapped);
    sections.push(emitInterface(mapped, schema, topLevelNames));
  }

  // 4. Discriminated union of all runtime event types.
  if (events.oneOf && events.oneOf.length > 0) {
    const orderedMembers = events.oneOf.map((ref) =>
      refToName(ref.$ref, topLevelNames),
    );
    const body = orderedMembers.map((m) => `  | ${m}`).join("\n");
    sections.push(
      `/** Discriminated union of every backend-emitted streaming event. */`,
    );
    sections.push(`export type ChatStreamEventDTO =\n${body};`);
  } else {
    const body = eventTypeNames.map((m) => `  | ${m}`).join("\n");
    sections.push(`export type ChatStreamEventDTO =\n${body};`);
  }

  return sections.join("\n") + "\n";
}

/* ------------------------------ CLI ------------------------------------- */

export function loadInputs(): GenerateInput {
  const shared = JSON.parse(
    readFileSync(SHARED_SCHEMA_PATH, "utf-8"),
  ) as SharedTypesManifest;
  const events = JSON.parse(
    readFileSync(EVENTS_SCHEMA_PATH, "utf-8"),
  ) as RuntimeEventsSchema;
  return { shared, events };
}

export function runCli(): void {
  const output = generateTypes(loadInputs());
  writeFileSync(OUTPUT_PATH, output);
  console.log(`wrote ${OUTPUT_PATH}`);
}

export function checkCli(): void {
  const expected = generateTypes(loadInputs());
  const actual = readFileSync(OUTPUT_PATH, "utf-8");
  if (actual !== expected) {
    console.error(
      `DRIFT: ${OUTPUT_PATH} is out of date with the committed JSON schemas.\n` +
        `Regenerate with: npm run codegen:types (from frontend/)`,
    );
    process.exit(1);
  }
  console.log(`OK: ${OUTPUT_PATH} is in sync with the committed JSON schemas`);
}

// Invoked directly (tsx scripts/codegen-types.ts or node --experimental-strip-types).
const invokedDirectly =
  import.meta.url === `file://${process.argv[1]}` ||
  import.meta.url.endsWith(path.basename(process.argv[1] ?? ""));
if (invokedDirectly) {
  if (process.argv.includes("--check")) {
    checkCli();
  } else {
    runCli();
  }
}

export const PATHS = {
  SHARED_SCHEMA_PATH,
  EVENTS_SCHEMA_PATH,
  OUTPUT_PATH,
};
