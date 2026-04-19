/**
 * Drift-guard: committed ``runtime-events.generated.ts`` must match what the
 * codegen script produces from the current committed JSON schema snapshot.
 *
 * If this test fails, run:
 *   npm run codegen:types         # from frontend/
 *
 * If the backend pydantic models changed, regenerate the JSON snapshot first:
 *   pytest backend/tests/test_runtime_events.py
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  generateRuntimeEventsZod,
  loadInputs,
  PATHS,
} from "../../../scripts/codegen-types";

describe("runtime-events.generated.ts drift-guard", () => {
  it("matches the codegen output for the current JSON schema snapshot", () => {
    const expected = generateRuntimeEventsZod(loadInputs().events);
    const actual = readFileSync(PATHS.RUNTIME_EVENTS_OUTPUT_PATH, "utf-8");
    expect(actual).toBe(expected);
  });

  it("emits a zod schema for every event in events.schema.json", () => {
    const events = JSON.parse(
      readFileSync(PATHS.EVENTS_SCHEMA_PATH, "utf-8"),
    ) as { discriminator: { mapping: Record<string, string> } };
    const generated = readFileSync(
      PATHS.RUNTIME_EVENTS_OUTPUT_PATH,
      "utf-8",
    );
    for (const ref of Object.values(events.discriminator.mapping)) {
      const defName = ref.replace(/^#\/\$defs\//, "");
      expect(
        generated,
        `runtime-events.generated.ts is missing ${defName}Schema`,
      ).toMatch(new RegExp(`export const ${defName}Schema\\b`));
    }
  });
});
