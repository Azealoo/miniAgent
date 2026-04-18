/**
 * Drift-guard: committed ``types.generated.ts`` must match what the codegen
 * script produces from the current committed JSON schemas.
 *
 * If this test fails, run:
 *   npm run codegen:types         # from frontend/
 *
 * If the backend pydantic models changed, regenerate the JSON snapshot first:
 *   python -m codegen.shared_types   # from backend/
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { generateTypes, loadInputs, PATHS } from "../../../scripts/codegen-types";

describe("types.generated.ts drift-guard", () => {
  it("matches the codegen output for the current JSON schema snapshots", () => {
    const expected = generateTypes(loadInputs());
    const actual = readFileSync(PATHS.OUTPUT_PATH, "utf-8");
    expect(actual).toBe(expected);
  });

  it("includes every DTO declared in shared_types.schema.json", () => {
    const shared = JSON.parse(
      readFileSync(PATHS.SHARED_SCHEMA_PATH, "utf-8"),
    ) as { models: Record<string, unknown> };
    const generated = readFileSync(PATHS.OUTPUT_PATH, "utf-8");
    for (const modelName of Object.keys(shared.models)) {
      expect(
        generated,
        `types.generated.ts is missing interface ${modelName}`,
      ).toMatch(new RegExp(`export interface ${modelName}\\b`));
    }
  });

  it("includes every runtime event declared in events.schema.json", () => {
    const events = JSON.parse(
      readFileSync(PATHS.EVENTS_SCHEMA_PATH, "utf-8"),
    ) as {
      discriminator: { mapping: Record<string, string> };
    };
    const generated = readFileSync(PATHS.OUTPUT_PATH, "utf-8");
    const expectedInterfaces: Record<string, string> = {
      retrieval: "ChatStreamRetrievalEvent",
      token: "ChatStreamTokenEvent",
      tool_start: "ChatStreamToolStartEvent",
      tool_end: "ChatStreamToolEndEvent",
      tool_awaiting_approval: "ChatStreamToolAwaitingApprovalEvent",
      tool_chunk: "ChatStreamToolChunkEvent",
      plan_created: "ChatStreamPlanCreatedEvent",
      plan_updated: "ChatStreamPlanUpdatedEvent",
      verification_result: "ChatStreamVerificationResultEvent",
      new_response: "ChatStreamNewResponseEvent",
      compaction_event: "ChatStreamCompactionEvent",
      done: "ChatStreamDoneEvent",
      error: "ChatStreamErrorEvent",
      workflow_step_started: "ChatStreamWorkflowStepStartedEvent",
      workflow_step_ended: "ChatStreamWorkflowStepEndedEvent",
      workflow_step_failed: "ChatStreamWorkflowStepFailedEvent",
    };
    for (const eventType of Object.keys(events.discriminator.mapping)) {
      const interfaceName = expectedInterfaces[eventType];
      expect(
        interfaceName,
        `no expected frontend interface mapped for ${eventType}`,
      ).toBeDefined();
      expect(
        generated,
        `types.generated.ts is missing interface ${interfaceName}`,
      ).toMatch(new RegExp(`export interface ${interfaceName}\\b`));
    }
  });
});
