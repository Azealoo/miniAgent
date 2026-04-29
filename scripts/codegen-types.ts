/**
 * Backend → frontend TypeScript codegen.
 *
 * Reads the two committed JSON-schema snapshots and emits two sibling files
 * under ``frontend/src/lib/``:
 *
 *   - ``types.generated.ts`` — TypeScript interfaces and a discriminated-union
 *     ``ChatStreamEventDTO`` type for every pydantic BaseModel / TypedDict.
 *   - ``runtime-events.generated.ts`` — matching zod schemas for every runtime
 *     event plus a ``ChatStreamEventSchema`` discriminated union. The
 *     hand-written ``runtime-events.ts`` re-exports from here so every SSE
 *     payload that flows through ``parseRuntimeEvent`` is validated against a
 *     zod schema generated from the pydantic contract.
 *
 * The committed generated files are the contracts the hand-written
 * ``types.ts`` and ``runtime-events.ts`` compose from. Three drift-guards
 * enforce that nothing diverges silently:
 *
 *   - ``backend/tests/test_shared_types_schema.py`` fails if the pydantic
 *     models drift from the committed JSON snapshot.
 *   - ``frontend/src/lib/types.generated.test.ts`` fails if the committed
 *     TypeScript file drifts from the generator output.
 *   - ``frontend/src/lib/runtime-events.generated.test.ts`` fails if the
 *     committed zod file drifts from the generator output.
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
const RUNTIME_EVENTS_OUTPUT_PATH = path.join(
  REPO_ROOT,
  "frontend/src/lib/runtime-events.generated.ts",
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
  RetrievalErrorRuntimeEvent: "ChatStreamRetrievalErrorEvent",
  TokenRuntimeEvent: "ChatStreamTokenEvent",
  ToolStartRuntimeEvent: "ChatStreamToolStartEvent",
  ToolEndRuntimeEvent: "ChatStreamToolEndEvent",
  ToolAwaitingApprovalRuntimeEvent: "ChatStreamToolAwaitingApprovalEvent",
  ToolChunkRuntimeEvent: "ChatStreamToolChunkEvent",
  PlanCreatedRuntimeEvent: "ChatStreamPlanCreatedEvent",
  PlanUpdatedRuntimeEvent: "ChatStreamPlanUpdatedEvent",
  VerificationResultRuntimeEvent: "ChatStreamVerificationResultEvent",
  NewResponseRuntimeEvent: "ChatStreamNewResponseEvent",
  PrefixInvalidatedRuntimeEvent: "ChatStreamPrefixInvalidatedEvent",
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

/* ------------------------------ Zod emission ---------------------------- */

// Module-scope constants we emit so the generated zod file stays readable and
// existing consumers (api.ts, runtime-events.test.ts) keep importing the same
// names. Anything not listed here is rendered inline against the JSON schema.
const SCHEMA_VERSION_FIELD_NAME = "schema_version";
const TURN_EXIT_DEF_NAME = "TurnExit";
const COMPACTION_EVENT_DEF_NAME = "CompactionRuntimeEvent";

function refToDefName(ref: string): string {
  return ref.replace(/^#\/\$defs\//, "");
}

function enumFromAnyOf(property: JsonSchema): string[] | undefined {
  if (!property.anyOf) return undefined;
  for (const variant of property.anyOf) {
    if (variant.enum && Array.isArray(variant.enum)) {
      return variant.enum as string[];
    }
  }
  return undefined;
}

function zodForType(schema: JsonSchema, defName: string, fieldName: string): string {
  if (schema.$ref) {
    return `${refToDefName(schema.$ref)}Schema`;
  }

  if (schema.const !== undefined) {
    return `z.literal(${JSON.stringify(schema.const)})`;
  }

  if (schema.enum && Array.isArray(schema.enum)) {
    // Special-case: the TurnExit.reason enum is exposed to consumers as
    // ``TURN_EXIT_REASONS`` so they can iterate it. Keep the named const.
    if (defName === TURN_EXIT_DEF_NAME && fieldName === "reason") {
      return `z.enum(TURN_EXIT_REASONS)`;
    }
    const items = schema.enum.map((v) => JSON.stringify(v)).join(", ");
    return `z.enum([${items}])`;
  }

  if (schema.anyOf) {
    const nonNull = schema.anyOf.filter((s) => s.type !== "null");
    const hasNull = schema.anyOf.some((s) => s.type === "null");
    if (nonNull.length === 1) {
      const inner = zodForType(nonNull[0], defName, fieldName);
      return hasNull ? `${inner}.nullish()` : inner;
    }
    const parts = nonNull.map((s) => zodForType(s, defName, fieldName));
    const union = `z.union([${parts.join(", ")}])`;
    return hasNull ? `${union}.nullish()` : union;
  }

  if (schema.type === "string") return "z.string()";
  if (schema.type === "integer") {
    let rendered = "z.number().int()";
    if (typeof schema.minimum === "number") rendered += `.min(${schema.minimum})`;
    if (typeof schema.maximum === "number") rendered += `.max(${schema.maximum})`;
    return rendered;
  }
  if (schema.type === "number") return "z.number()";
  if (schema.type === "boolean") return "z.boolean()";
  if (schema.type === "null") return "z.null()";

  if (schema.type === "array") {
    const items = (schema.items as JsonSchema | undefined) ?? {};
    const inner = zodForType(items, defName, fieldName);
    return `z.array(${inner})`;
  }

  if (schema.type === "object") {
    // pydantic ``dict[str, Any]`` → ``additionalProperties: true``. The
    // equivalent zod shape is ``z.record(z.string(), z.unknown())``; we do not
    // try to represent ``JsonLike`` more specifically here because pydantic
    // will round-trip anything JSON-shaped through this field.
    return "z.record(z.string(), z.unknown())";
  }

  return "z.unknown()";
}

function zodForField(
  schema: JsonSchema,
  required: boolean,
  defName: string,
  fieldName: string,
): string {
  // Discriminator fields (a literal ``type``) are always required even when
  // pydantic emits them as optional-with-default, because zod's
  // ``discriminatedUnion`` needs to see the literal on the input.
  if (schema.const !== undefined) {
    return zodForType(schema, defName, fieldName);
  }

  let rendered = zodForType(schema, defName, fieldName);

  if (required) return rendered;

  // anyOf-with-null already produced a ``.nullish()`` suffix above — keep it
  // as-is so an omitted field resolves to ``undefined`` and a wire-level
  // ``null`` stays ``null`` (matching pydantic ``Optional[T] = None``).
  if (rendered.endsWith(".nullish()")) return rendered;

  if (schema.default !== undefined && schema.default !== null) {
    // Route the common schema_version constant through the exported symbol so
    // changing the wire version is a one-line edit to ``events.py``.
    if (fieldName === SCHEMA_VERSION_FIELD_NAME && typeof schema.default === "number") {
      return `${rendered}.default(RUNTIME_EVENT_SCHEMA_VERSION)`;
    }
    return `${rendered}.default(${JSON.stringify(schema.default)})`;
  }

  // pydantic ``list[T] = Field(default_factory=list)`` does not serialize a
  // default into JSON schema, but the wire always carries ``[]``. Mirror that
  // so every consumer gets a concrete array instead of ``undefined``.
  if (schema.type === "array") {
    return `${rendered}.default([])`;
  }

  return `${rendered}.optional()`;
}

function emitZodSchema(defName: string, schema: JsonSchema): string {
  const required = new Set(schema.required ?? []);
  const props = schema.properties ?? {};
  const lines: string[] = [];
  if (schema.description) {
    const lead = schema.description.split("\n")[0]?.trim() ?? "";
    if (lead) lines.push(`/** ${lead} */`);
  }
  lines.push(`export const ${defName}Schema = z`);
  lines.push(`  .object({`);
  for (const key of Object.keys(props).sort()) {
    const field = props[key];
    const isReq = required.has(key);
    const rendered = zodForField(field, isReq, defName, key);
    lines.push(`    ${key}: ${rendered},`);
  }
  lines.push(`  })`);
  lines.push(`  .strict();`);
  return lines.join("\n");
}

const RUNTIME_EVENTS_HEADER = [
  "/**",
  " * AUTO-GENERATED. Do not edit by hand.",
  " *",
  " * Produced by scripts/codegen-types.ts from",
  " * backend/runtime/events.schema.json. The hand-written",
  " * ./runtime-events.ts re-exports from this file and adds the",
  " * `parseRuntimeEvent` helper that every SSE payload flows through.",
  " *",
  " * Regenerate with:",
  " *   python -m codegen.shared_types             # from backend/",
  " *   npm run codegen:types                      # from frontend/",
  " */",
  'import { z } from "zod";',
  "",
].join("\n");

export function generateRuntimeEventsZod(events: RuntimeEventsSchema): string {
  const defs = events.$defs;
  const sections: string[] = [RUNTIME_EVENTS_HEADER];

  // Pull the common ``schema_version`` default off any runtime-event $def so
  // changing the wire version only requires rebuilding the JSON snapshot.
  const sampleEventName = Object.keys(defs).find((name) =>
    name.endsWith("RuntimeEvent"),
  );
  const sampleEvent = sampleEventName ? defs[sampleEventName] : undefined;
  const schemaVersion =
    sampleEvent?.properties?.[SCHEMA_VERSION_FIELD_NAME]?.default;
  if (typeof schemaVersion !== "number") {
    throw new Error(
      "Could not infer RUNTIME_EVENT_SCHEMA_VERSION from events schema.",
    );
  }
  sections.push(
    `export const RUNTIME_EVENT_SCHEMA_VERSION = ${schemaVersion} as const;`,
  );

  // TurnExit is referenced by ``DoneRuntimeEvent.exit`` — emit it first so the
  // per-event schemas can point at ``TurnExitSchema`` by name.
  const turnExit = defs[TURN_EXIT_DEF_NAME];
  if (!turnExit) {
    throw new Error("Expected TurnExit $def in events schema.");
  }
  const turnExitReasons = turnExit.properties?.reason?.enum as
    | string[]
    | undefined;
  if (!turnExitReasons) {
    throw new Error("Expected TurnExit.reason to carry an enum.");
  }
  sections.push("");
  sections.push(
    `export const TURN_EXIT_REASONS = [${turnExitReasons
      .map((r) => JSON.stringify(r))
      .join(", ")}] as const;`,
  );
  sections.push(
    `export type TurnExitReason = (typeof TURN_EXIT_REASONS)[number];`,
  );
  sections.push("");
  sections.push(emitZodSchema(TURN_EXIT_DEF_NAME, turnExit));
  sections.push(`export type TurnExit = z.infer<typeof TurnExitSchema>;`);

  // CompactionRuntimeEvent.phase exposes the ``COMPACTION_PHASES`` tuple to UI
  // consumers — emit it as a named const above the per-event schemas.
  const compaction = defs[COMPACTION_EVENT_DEF_NAME];
  const phaseEnum = compaction
    ? enumFromAnyOf(compaction.properties?.phase ?? {})
    : undefined;
  if (phaseEnum) {
    sections.push("");
    sections.push(
      `export const COMPACTION_PHASES = [${phaseEnum
        .map((p) => JSON.stringify(p))
        .join(", ")}] as const;`,
    );
    sections.push(
      `export type CompactionPhase = (typeof COMPACTION_PHASES)[number];`,
    );
  }

  // Per-event schemas in the discriminator order declared by the backend.
  const orderedEventNames: string[] = events.oneOf
    ? events.oneOf.map((ref) => refToDefName(ref.$ref))
    : Object.keys(defs).filter((n) => n !== TURN_EXIT_DEF_NAME);

  sections.push("");
  for (const name of orderedEventNames) {
    sections.push(emitZodSchema(name, defs[name]));
  }

  // Discriminated union and the aliases consumers import.
  sections.push("");
  sections.push(
    `export const ChatStreamEventSchema = z.discriminatedUnion("type", [`,
  );
  for (const name of orderedEventNames) {
    sections.push(`  ${name}Schema,`);
  }
  sections.push(`]);`);
  sections.push(`export const RuntimeEventSchema = ChatStreamEventSchema;`);
  sections.push(`export type ChatStreamEvent = z.infer<typeof ChatStreamEventSchema>;`);
  sections.push(`export type RuntimeEvent = ChatStreamEvent;`);

  // Ordered type tuple + ZodType lookup so callers can iterate the wire
  // contract without touching the individual schema bindings.
  const eventTypeLiterals: string[] = [];
  for (const name of orderedEventNames) {
    const typeConst = defs[name].properties?.type?.const;
    if (typeof typeConst !== "string") {
      throw new Error(`Event ${name} is missing a string 'type' literal.`);
    }
    eventTypeLiterals.push(JSON.stringify(typeConst));
  }
  sections.push("");
  sections.push(
    `export const RUNTIME_EVENT_TYPES = [${eventTypeLiterals.join(
      ", ",
    )}] as const;`,
  );
  sections.push(
    `export type RuntimeEventType = (typeof RUNTIME_EVENT_TYPES)[number];`,
  );

  sections.push("");
  sections.push(
    `export const RUNTIME_EVENT_SCHEMAS: Record<RuntimeEventType, z.ZodTypeAny> = {`,
  );
  for (const name of orderedEventNames) {
    const typeConst = defs[name].properties?.type?.const as string;
    sections.push(`  ${typeConst}: ${name}Schema,`);
  }
  sections.push(`};`);

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

interface GeneratedFile {
  path: string;
  label: string;
  output: string;
}

function generateAll(): GeneratedFile[] {
  const inputs = loadInputs();
  return [
    {
      path: OUTPUT_PATH,
      label: "types.generated.ts",
      output: generateTypes(inputs),
    },
    {
      path: RUNTIME_EVENTS_OUTPUT_PATH,
      label: "runtime-events.generated.ts",
      output: generateRuntimeEventsZod(inputs.events),
    },
  ];
}

export function runCli(): void {
  for (const { path: out, output } of generateAll()) {
    writeFileSync(out, output);
    console.log(`wrote ${out}`);
  }
}

export function checkCli(): void {
  let drift = false;
  for (const { path: out, output: expected } of generateAll()) {
    const actual = readFileSync(out, "utf-8");
    if (actual !== expected) {
      console.error(
        `DRIFT: ${out} is out of date with the committed JSON schemas.\n` +
          `Regenerate with: npm run codegen:types (from frontend/)`,
      );
      drift = true;
    } else {
      console.log(`OK: ${out} is in sync with the committed JSON schemas`);
    }
  }
  if (drift) process.exit(1);
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
  RUNTIME_EVENTS_OUTPUT_PATH,
};
