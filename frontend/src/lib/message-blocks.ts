import type {
  JsonObject,
  Message,
  RetrievalResult,
  SessionContentBlock,
  SessionPlanBlock,
  SessionVerificationBlock,
  SessionHistoryMessage,
  ToolCall,
  ToolResultEnvelope,
} from "./types";

type BlockCompatibleMessage = {
  role: Message["role"] | SessionHistoryMessage["role"];
  content?: string;
  request_id?: string;
  tool_calls?: ToolCall[];
  retrievals?: RetrievalResult[];
  blocks?: SessionContentBlock[];
};

type TurnCompatibleMessage = BlockCompatibleMessage & {
  role: string;
};

export interface NormalizedMessageContent {
  blocks: SessionContentBlock[];
  content: string;
  toolCalls: ToolCall[];
  retrievals: RetrievalResult[];
}

export interface NormalizeMessageContentOptions {
  forceHasPlan?: boolean;
  forceHasVerification?: boolean;
  forceHasProcessActivity?: boolean;
}

function toolBlockKey(tool: string, runId?: string): string {
  return runId ?? tool;
}

function asObjectRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asJsonObjectArray(value: unknown): JsonObject[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value
    .filter(
      (item): item is Record<string, unknown> =>
        Boolean(item) && typeof item === "object" && !Array.isArray(item)
    )
    .map((item) => ({ ...item }) as JsonObject);
}

function helperResultSummary(
  result: ToolResultEnvelope | undefined,
  output: string,
  fallback: string
): string {
  const summary = typeof result?.summary === "string" ? result.summary.trim() : "";
  if (summary) {
    return summary;
  }

  const normalizedOutput = output.trim();
  return normalizedOutput || fallback;
}

function inferPlanEvent(summary: string): SessionPlanBlock["event"] {
  return /\b(update|updated|refine|refined|revise|revised)\b/i.test(summary)
    ? "updated"
    : "created";
}

function extractPlanBlockFromToolResult(
  block: Extract<SessionContentBlock, { type: "tool_result" }>
): SessionPlanBlock | null {
  if (block.tool !== "plan_agent") {
    return null;
  }

  const payload = asObjectRecord(block.result?.structured_payload);
  if (payload?.agent_type !== "plan") {
    return null;
  }

  const plan = asObjectRecord(payload.plan);
  if (!plan) {
    return null;
  }

  const summary = helperResultSummary(
    block.result,
    block.output,
    "Planning steps captured."
  );
  const toolTrace = asJsonObjectArray(payload.tool_trace);

  return {
    type: "plan",
    event: inferPlanEvent(summary),
    summary,
    run_id: block.run_id,
    plan: { ...plan } as JsonObject,
    ...(toolTrace ? { tool_trace: toolTrace } : {}),
  };
}

function extractVerificationBlockFromToolResult(
  block: Extract<SessionContentBlock, { type: "tool_result" }>
): SessionVerificationBlock | null {
  if (block.tool !== "verification_agent") {
    return null;
  }

  const payload = asObjectRecord(block.result?.structured_payload);
  if (payload?.agent_type !== "verification") {
    return null;
  }

  const verification = asObjectRecord(payload.verification);
  if (!verification) {
    return null;
  }

  const verdict = verification.verdict;
  const normalizedVerdict =
    verdict === "pass" || verdict === "repair_required" || verdict === "fail"
      ? verdict
      : "fail";
  const toolTrace = asJsonObjectArray(payload.tool_trace);

  return {
    type: "verification",
    summary: helperResultSummary(
      block.result,
      block.output,
      "Verification result captured."
    ),
    verdict: normalizedVerdict,
    run_id: block.run_id,
    verification: { ...verification } as JsonObject,
    ...(toolTrace ? { tool_trace: toolTrace } : {}),
  };
}

function augmentHelperBlocks(
  blocks: SessionContentBlock[]
): SessionContentBlock[] {
  if (blocks.length === 0) {
    return blocks;
  }

  const hasPlanBlock = blocks.some((block) => block.type === "plan");
  const hasVerificationBlock = blocks.some(
    (block) => block.type === "verification"
  );

  if (hasPlanBlock && hasVerificationBlock) {
    return blocks;
  }

  const augmented: SessionContentBlock[] = [];
  blocks.forEach((block) => {
    augmented.push(block);

    if (block.type !== "tool_result") {
      return;
    }

    if (!hasPlanBlock) {
      const planBlock = extractPlanBlockFromToolResult(block);
      if (planBlock) {
        augmented.push(planBlock);
      }
    }

    if (!hasVerificationBlock) {
      const verificationBlock = extractVerificationBlockFromToolResult(block);
      if (verificationBlock) {
        augmented.push(verificationBlock);
      }
    }
  });

  return augmented;
}

function hasBlockType(
  blocks: SessionContentBlock[],
  type: "plan" | "verification"
): boolean {
  return blocks.some((block) => block.type === type);
}

function hasToolActivity(
  blocks: SessionContentBlock[],
  tool: "plan_agent" | "verification_agent"
): boolean {
  return blocks.some(
    (block) =>
      (block.type === "tool_use" || block.type === "tool_result") &&
      block.tool === tool
  );
}

function textBlockTouchesBlockType(
  blocks: SessionContentBlock[],
  index: number,
  type: "plan" | "verification"
): boolean {
  return [index - 1, index + 1].some((candidateIndex) => {
    const candidate = blocks[candidateIndex];
    return candidate?.type === type;
  });
}

interface HelperNarrationOptions {
  hasPlan: boolean;
  hasVerification: boolean;
  hasProcessActivity?: boolean;
  planNearby?: boolean;
  verificationNearby?: boolean;
  nearbyPlan?: SessionPlanBlock | null;
}

function adjacentPlanBlock(
  blocks: SessionContentBlock[],
  index: number
): SessionPlanBlock | null {
  for (const candidateIndex of [index - 1, index + 1]) {
    const candidate = blocks[candidateIndex];
    if (candidate?.type === "plan") {
      return candidate;
    }
  }
  return null;
}

function stripLeadingMatchingPattern(
  text: string,
  patterns: RegExp[]
): { text: string; changed: boolean } {
  let working = text;
  let changed = false;

  while (true) {
    const trimmed = working.trimStart();
    const match = patterns.find((pattern) => pattern.test(trimmed));
    if (!match) {
      return { text: changed ? working : text, changed };
    }
    working = trimmed.replace(match, "");
    changed = true;
  }
}

function stripLeadingJsonObject(text: string): { text: string; changed: boolean } {
  const trimmed = text.trimStart();
  if (!trimmed.startsWith("{")) {
    return { text, changed: false };
  }

  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let index = 0; index < trimmed.length; index += 1) {
    const char = trimmed[index];

    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === "\"") {
        inString = false;
      }
      continue;
    }

    if (char === "\"") {
      inString = true;
      continue;
    }

    if (char === "{") {
      depth += 1;
      continue;
    }

    if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return {
          text: trimmed.slice(index + 1).trimStart(),
          changed: true,
        };
      }
    }
  }

  return { text, changed: false };
}

function stripLeadingProcessLines(
  text: string,
  {
    hasPlan,
    hasVerification,
  }: Pick<HelperNarrationOptions, "hasPlan" | "hasVerification">
): { text: string; changed: boolean } {
  let working = text;
  let changed = false;

  while (true) {
    const trimmed = working.trimStart();
    let updated = trimmed;

    if (hasPlan) {
      updated = updated.replace(/^(?:started|running)\s+planning\.\s*/i, "");
      updated = updated.replace(
        /^ran\s+planning(?::\s*|\.\s*)[^\n]*(?:\n+|$)\s*/i,
        ""
      );
      updated = updated.replace(/^planner produced \d+ steps?\.?\s*/i, "");
    }

    if (hasVerification) {
      updated = updated.replace(/^(?:started|running)\s+verification\.\s*/i, "");
      updated = updated.replace(
        /^ran\s+verification(?::\s*|\.\s*)[^\n]*(?:\n+|$)\s*/i,
        ""
      );
      updated = updated.replace(
        /^verifier verdict:\s*[a-z_]+\.[^\n]*(?:\n+|$)\s*/i,
        ""
      );
      updated = updated.replace(/^verification feedback:\s*/i, "");
    }

    if (updated === trimmed) {
      return { text: changed ? working : text, changed };
    }

    working = updated;
    changed = true;
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function planStepPattern(intent: string): string | null {
  const tokens = intent.toLowerCase().match(/[a-z0-9]+/g);
  if (!tokens || tokens.length === 0) {
    return null;
  }
  return tokens.map((token) => escapeRegExp(token)).join("[^a-z0-9]+");
}

function consumeLeadingMatchedPlanSteps(
  text: string,
  nearbyPlan: SessionPlanBlock | null
): { remainder: string; matchedCount: number } {
  const steps = Array.isArray(nearbyPlan?.plan?.steps)
    ? nearbyPlan?.plan?.steps
    : [];
  let remainder = text.trimStart();
  let matchedCount = 0;

  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    if (!step || typeof step !== "object") {
      break;
    }
    const intent = (step as { intent?: unknown }).intent;
    if (typeof intent !== "string" || !intent.trim()) {
      break;
    }

    const intentPattern = planStepPattern(intent);
    if (!intentPattern) {
      break;
    }

    const marker = index + 1;
    const match = remainder.match(
      new RegExp(
        `^\\s*(?:step\\s*${marker}|${marker})\\s*[.):-]\\s*${intentPattern}(?=$|\\s|[.!?,;:])\\s*`,
        "i"
      )
    );
    if (!match) {
      break;
    }

    remainder = remainder.slice(match[0].length).trimStart();
    matchedCount += 1;
  }

  return { remainder, matchedCount };
}

function looksLikeVerificationMetadataJson(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) {
    return false;
  }

  const hasSummary = /"summary"\s*:/.test(normalized);
  const hasChecks = /"checks"\s*:/.test(normalized);
  const hasIssues = /"issues"\s*:/.test(normalized);
  const hasRepairInstructions = /"repair_instructions"\s*:/.test(normalized);

  return (
    (hasSummary && (hasChecks || hasIssues || hasRepairInstructions)) ||
    (hasChecks && (hasIssues || hasRepairInstructions)) ||
    (hasIssues && hasRepairInstructions)
  );
}

function looksLikeMalformedVerificationJson(text: string): boolean {
  const normalized = text.trim();
  if (!normalized.startsWith("{")) {
    return false;
  }

  const markerMatches = [
    /^{"ver/i,
    /"verdict"\s*:/i,
    /"summary"\s*:/i,
    /"checks"\s*:/i,
    /"issues"\s*:/i,
    /"repair_instructions"\s*:/i,
  ].filter((pattern) => pattern.test(normalized)).length;

  return markerMatches >= 2;
}

function stripLeadingMalformedVerificationJson(
  text: string
): { text: string; changed: boolean } {
  const trimmed = text.trimStart();
  if (!looksLikeMalformedVerificationJson(trimmed)) {
    return { text, changed: false };
  }

  const boundary = trimmed.search(/\n\s*\n/);
  if (boundary === -1) {
    return { text: "", changed: true };
  }

  return {
    text: trimmed.slice(boundary).trimStart(),
    changed: true,
  };
}

function sanitizeHelperNarrationText(
  text: string,
  {
    hasPlan,
    hasVerification,
    hasProcessActivity = false,
    planNearby = false,
    nearbyPlan = null,
  }: HelperNarrationOptions
): string {
  const normalized = text.trim();
  if (!normalized) {
    return text;
  }

  const hasPlanLikeJson =
    /"goal"\s*:/.test(normalized) &&
    (
      /"steps"\s*:/.test(normalized) ||
      /"assumptions"\s*:/.test(normalized) ||
      /"constraints"\s*:/.test(normalized) ||
      /"verification_checks"\s*:/.test(normalized) ||
      /"success_criteria"\s*:/.test(normalized)
    );
  const hasVerificationLikeJson =
    /"verdict"\s*:/.test(normalized) &&
    (/"summary"\s*:/.test(normalized) ||
      /"checks"\s*:/.test(normalized) ||
      /"issues"\s*:/.test(normalized) ||
      /"repair_instructions"\s*:/.test(normalized));
  const hasPlanJson = hasPlanLikeJson && (hasPlan || hasProcessActivity);
  const hasVerificationJson =
    hasVerificationLikeJson && (hasVerification || hasProcessActivity);
  const strippedGenericProcessPreamble =
    hasProcessActivity
      ? stripLeadingMatchingPattern(text, [
          /^(?:i(?:'ll| will) help you[^.\n{]*\.\s*)/i,
          /^(?:now\s+)?let me start by planning\b[^.\n{]*\.\s*/i,
          /^(?:now\s+)?let me execute the plan\b[^.\n{]*\.\s*/i,
          /^(?:first,\s*)?i(?:'ll| will)\s+(?:search|inspect|check|look|review|gather|use)\b[^.\n{]*\.\s*/i,
          /^(?:i see many [^.\n{]*\.\s*)/i,
          /^(?:let me get more specific\b[^.\n{]*\.\s*)/i,
          /^(?:let me search\b[^.\n{]*\.\s*)/i,
          /^(?:now\s+)?let me\b[^.\n{]*\.\s*/i,
        ])
      : { text, changed: false };
  const strippedPlanPreamble = hasPlan
    ? stripLeadingMatchingPattern(strippedGenericProcessPreamble.text, [
        /^(?:i(?:'ll| will) help you[^.\n{]*\.\s*)/i,
        /^(?:first,\s*)?let me\b[^.\n{]*\.\s*/i,
        /^(?:first,\s*)?let me (?:start|begin)\b[^:\n{]*plan[^:\n{]*:\s*/i,
        /^(?:i(?:'m| am) going to\b[^.\n{]*\.\s*)/i,
        /^(?:based on what i found[^.\n{]*\.\s*)/i,
        /^(?:based on that[^.\n{]*\.\s*)/i,
        /^(?:with that in mind[^.\n{]*\.\s*)/i,
        /^(?:given that[^.\n{]*\.\s*)/i,
        /^(?:here(?:'s| is) a structured plan:\s*)/i,
        /^(?:here(?:'s| is) the(?: updated)? plan:\s*)/i,
        /^(?:update the plan:\s*)/i,
        /^(?:revised plan:\s*)/i,
      ])
    : { text: strippedGenericProcessPreamble.text, changed: false };
  const strippedVerificationPreamble =
    hasVerification
      ? stripLeadingMatchingPattern(strippedPlanPreamble.text, [
          /^(?:now\s+)?let me (?:verify|revise|refine)\b[^.\n{]*\.\s*/i,
          /^(?:now\s+)?let me (?:verify|revise|refine)\b[^:\n{]*:\s*/i,
        ])
      : { text: strippedPlanPreamble.text, changed: false };
  const strippedProcessLines = stripLeadingProcessLines(
    strippedVerificationPreamble.text,
    {
      hasPlan,
      hasVerification,
    }
  );
  const startsWithStructuredJson = strippedProcessLines.text.trimStart().startsWith("{");
  const hasVerificationMetadataJson =
    hasVerification &&
    startsWithStructuredJson &&
    strippedVerificationPreamble.changed &&
    looksLikeVerificationMetadataJson(strippedProcessLines.text);
  const strippedLeadingJson =
    hasPlanJson || hasVerificationJson || hasVerificationMetadataJson
      ? stripLeadingJsonObject(strippedProcessLines.text)
      : { text: strippedProcessLines.text, changed: false };
  const strippedMalformedVerificationJson =
    hasVerification && !strippedLeadingJson.changed
      ? stripLeadingMalformedVerificationJson(strippedLeadingJson.text)
      : { text: strippedLeadingJson.text, changed: false };
  const workingText = strippedMalformedVerificationJson.text;
  const workingLower = workingText.trim().toLowerCase();
  const leakedIncompletePlanJson =
    hasPlanJson &&
    startsWithStructuredJson &&
    !strippedLeadingJson.changed &&
    (
      normalized.startsWith("{") ||
      strippedGenericProcessPreamble.changed ||
      strippedPlanPreamble.changed
    );
  const leakedIncompleteVerificationJson =
    (hasVerificationJson || hasVerificationMetadataJson) &&
    startsWithStructuredJson &&
    !strippedLeadingJson.changed &&
    (
      normalized.startsWith("{") ||
      strippedGenericProcessPreamble.changed ||
      strippedVerificationPreamble.changed
    );

  if (leakedIncompletePlanJson || leakedIncompleteVerificationJson) {
    return "";
  }

  if (
    hasPlanJson &&
    !workingText.trim() &&
    (
      normalized.startsWith("{") ||
      strippedGenericProcessPreamble.changed ||
      strippedPlanPreamble.changed ||
      strippedLeadingJson.changed
    )
  ) {
    return "";
  }
  if (
    (hasVerificationJson || hasVerificationMetadataJson) &&
    !workingText.trim() &&
    (
      normalized.startsWith("{") ||
      strippedGenericProcessPreamble.changed ||
      strippedVerificationPreamble.changed ||
      strippedLeadingJson.changed ||
      strippedMalformedVerificationJson.changed
    )
  ) {
    return "";
  }

  if (planNearby && nearbyPlan) {
    const matchedSteps = consumeLeadingMatchedPlanSteps(
      workingText,
      nearbyPlan
    );
    if (matchedSteps.matchedCount > 0) {
      if (!matchedSteps.remainder.trim()) {
        return "";
      }
      if (
        strippedGenericProcessPreamble.changed ||
        strippedPlanPreamble.changed ||
        strippedProcessLines.changed ||
        strippedLeadingJson.changed ||
        matchedSteps.matchedCount > 1
      ) {
        return matchedSteps.remainder.trimStart();
      }
    }
  }

  if (
    strippedGenericProcessPreamble.changed ||
    strippedPlanPreamble.changed ||
    strippedVerificationPreamble.changed ||
    strippedProcessLines.changed ||
    strippedLeadingJson.changed ||
    strippedMalformedVerificationJson.changed
  ) {
    return workingText.trimStart();
  }
  if (
    hasVerification &&
    (
      workingLower.includes("verification agent") ||
      workingLower.includes("verification feedback") ||
      workingLower.includes("verifier verdict")
    )
  ) {
    return workingText.trimStart();
  }

  return text;
}

export function shouldSuppressHelperNarrationText(
  text: string,
  options: HelperNarrationOptions
): boolean {
  const sanitized = sanitizeHelperNarrationText(text, options);
  return Boolean(text.trim()) && sanitized.trim().length === 0;
}

function looksLikePlanHelperText(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) {
    return false;
  }

  const lower = normalized.toLowerCase();
  return (
    (/"goal"\s*:/.test(normalized) &&
      (/"steps"\s*:/.test(normalized) ||
        /"assumptions"\s*:/.test(normalized) ||
        /"constraints"\s*:/.test(normalized) ||
        /"verification_checks"\s*:/.test(normalized) ||
        /"success_criteria"\s*:/.test(normalized))) ||
    /^started planning\./i.test(normalized) ||
    /^ran planning(?::|\.)/i.test(normalized) ||
    lower.includes("let me start by planning") ||
    lower.includes("creating a structured plan") ||
    lower.includes("here is the updated plan") ||
    lower.includes("here's the updated plan") ||
    lower.includes("update the plan")
  );
}

function looksLikeVerificationHelperText(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) {
    return false;
  }

  const lower = normalized.toLowerCase();
  return (
    (/"verdict"\s*:/.test(normalized) &&
      (/"summary"\s*:/.test(normalized) ||
        /"checks"\s*:/.test(normalized) ||
        /"issues"\s*:/.test(normalized) ||
        /"repair_instructions"\s*:/.test(normalized))) ||
    /^started verification\./i.test(normalized) ||
    /^ran verification(?::|\.)/i.test(normalized) ||
    lower.includes("verification feedback") ||
    lower.includes("verification agent") ||
    lower.includes("verifier verdict")
  );
}

export function normalizeTurnMessages<T extends TurnCompatibleMessage>(
  messages: T[]
): T[] {
  const collapsedMessages = collapseVerificationRetryMessages(messages);
  const assistants = collapsedMessages.filter(
    (message) => message.role === "assistant"
  );
  const assistantBlocks = assistants.flatMap((message) => deriveMessageBlocks(message));
  const forceHasPlan =
    assistantBlocks.some(
      (block) =>
        block.type === "plan" ||
        ((block.type === "tool_use" || block.type === "tool_result") &&
          block.tool === "plan_agent")
    ) || assistants.some((message) => looksLikePlanHelperText(message.content ?? ""));
  const forceHasVerification =
    assistantBlocks.some(
      (block) =>
        block.type === "verification" ||
        ((block.type === "tool_use" || block.type === "tool_result") &&
          block.tool === "verification_agent")
    ) ||
    assistants.some((message) =>
      looksLikeVerificationHelperText(message.content ?? "")
    );
  const forceHasProcessActivity =
    forceHasPlan ||
    forceHasVerification ||
    assistantBlocks.some((block) => block.type !== "text" && block.type !== "usage");

  return collapsedMessages.map((message) => {
    if (message.role !== "assistant") {
      return message;
    }

    const normalized = normalizeMessageContent(message, {
      forceHasPlan,
      forceHasVerification,
      forceHasProcessActivity,
    });
    const sanitizedBlocks: SessionContentBlock[] = normalized.blocks.filter(
      (block) => block.type !== "text"
    );
    if (normalized.content.trim()) {
      sanitizedBlocks.push({
        type: "text",
        text: normalized.content,
      });
    }

    return {
      ...message,
      content: normalized.content,
      blocks: sanitizedBlocks,
    };
  }) as T[];
}

function messageHasVerificationContext(message: BlockCompatibleMessage): boolean {
  const blocks = deriveMessageBlocks(message);
  if (
    blocks.some(
      (block) =>
        block.type === "verification" ||
        ((block.type === "tool_use" || block.type === "tool_result") &&
          block.tool === "verification_agent")
    )
  ) {
    return true;
  }

  return looksLikeVerificationHelperText(message.content ?? "");
}

function collapseVerificationRetryMessages<T extends TurnCompatibleMessage>(
  messages: T[]
): T[] {
  if (messages.length < 2) {
    return messages;
  }

  const collapsed: T[] = [];

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (message.role !== "assistant") {
      collapsed.push(message);
      continue;
    }

    let endIndex = index;
    while (
      endIndex + 1 < messages.length &&
      messages[endIndex + 1]?.role === "assistant"
    ) {
      endIndex += 1;
    }

    const cluster = messages.slice(index, endIndex + 1);
    const shouldCollapse =
      cluster.length > 1 &&
      cluster.slice(0, -1).some((entry) => messageHasVerificationContext(entry));

    if (!shouldCollapse) {
      collapsed.push(...cluster);
      index = endIndex;
      continue;
    }

    const first = cluster[0] as T & {
      id?: string;
      startedAtMs?: number;
      endedAtMs?: number;
      isStreaming?: boolean;
      pendingTool?: { tool: string; input: string; runId: string };
    };
    const last = cluster[cluster.length - 1] as T & {
      id?: string;
      startedAtMs?: number;
      endedAtMs?: number;
      isStreaming?: boolean;
      pendingTool?: { tool: string; input: string; runId: string };
    };
    const mergedBlocks: SessionContentBlock[] = [
      ...cluster.slice(0, -1).flatMap((entry) =>
        deriveMessageBlocks(entry).filter((block) => block.type !== "text")
      ),
      ...deriveMessageBlocks(last),
    ];

    collapsed.push({
      ...first,
      ...last,
      id: first.id ?? last.id,
      request_id: last.request_id ?? first.request_id,
      content: last.content ?? "",
      blocks: mergedBlocks,
      startedAtMs: first.startedAtMs ?? last.startedAtMs,
      endedAtMs: last.endedAtMs ?? first.endedAtMs,
      isStreaming: last.isStreaming ?? false,
      pendingTool: last.pendingTool,
    } as T);
    index = endIndex;
  }

  return collapsed;
}

export function deriveMessageBlocks(
  message: BlockCompatibleMessage
): SessionContentBlock[] {
  const hasStoredBlocks = (message.blocks?.length ?? 0) > 0;
  const blocks: SessionContentBlock[] = hasStoredBlocks
    ? [...(message.blocks ?? [])]
    : [];

  if (!hasStoredBlocks && message.role === "assistant") {
    if ((message.retrievals?.length ?? 0) > 0) {
      blocks.push({
        type: "retrieval",
        results: [...(message.retrievals ?? [])],
      });
    }

    for (const call of message.tool_calls ?? []) {
      blocks.push({
        type: "tool_use",
        tool: call.tool,
        input: call.input,
        run_id: call.run_id,
      });
      blocks.push({
        type: "tool_result",
        tool: call.tool,
        output: call.output,
        run_id: call.run_id,
        result: call.result,
      });
    }
  }

  if (!hasStoredBlocks && (message.content ?? "").trim()) {
    blocks.push({
      type: "text",
      text: message.content ?? "",
    });
  }

  return message.role === "assistant" ? augmentHelperBlocks(blocks) : blocks;
}

export function normalizeMessageContent(
  message: BlockCompatibleMessage,
  options: NormalizeMessageContentOptions = {}
): NormalizedMessageContent {
  const blocks = deriveMessageBlocks(message);
  const hasTextBlock = blocks.some((block) => block.type === "text");
  const hasPlan = hasBlockType(blocks, "plan");
  const hasVerification = hasBlockType(blocks, "verification");
  const hasPlanContext =
    options.forceHasPlan === true ||
    hasPlan ||
    hasToolActivity(blocks, "plan_agent");
  const hasVerificationContext =
    options.forceHasVerification === true ||
    hasVerification ||
    hasToolActivity(blocks, "verification_agent");
  const hasProcessActivity =
    options.forceHasProcessActivity === true ||
    blocks.some((block) => block.type !== "text" && block.type !== "usage");
  const textParts: string[] = [];
  const toolCalls: ToolCall[] = [];
  const retrievals: RetrievalResult[] = [];
  const pendingUses = new Map<string, Array<{ input: string; run_id?: string }>>();

  blocks.forEach((block, index) => {
    switch (block.type) {
      case "text":
        {
          const sanitized = sanitizeHelperNarrationText(block.text, {
            hasPlan: hasPlanContext,
            hasVerification: hasVerificationContext,
            hasProcessActivity,
            planNearby: textBlockTouchesBlockType(blocks, index, "plan"),
            verificationNearby: textBlockTouchesBlockType(
              blocks,
              index,
              "verification"
            ),
            nearbyPlan: adjacentPlanBlock(blocks, index),
          });
          if (sanitized.trim()) {
            textParts.push(sanitized);
          }
        }
        break;
      case "tool_use": {
        const key = toolBlockKey(block.tool, block.run_id);
        const queue = pendingUses.get(key) ?? [];
        queue.push({ input: block.input, run_id: block.run_id });
        pendingUses.set(key, queue);
        break;
      }
      case "tool_result": {
        const key = toolBlockKey(block.tool, block.run_id);
        const queue = pendingUses.get(key) ?? [];
        const started = queue.shift();
        if (queue.length > 0) {
          pendingUses.set(key, queue);
        } else {
          pendingUses.delete(key);
        }

        toolCalls.push({
          tool: block.tool,
          input: started?.input ?? "",
          output: block.output,
          run_id: block.run_id ?? started?.run_id,
          result: block.result,
        });
        break;
      }
      case "retrieval":
        retrievals.push(...block.results);
        break;
      case "usage":
      case "plan":
      case "verification":
      case "approval_gate":
        break;
    }
  });

  return {
    blocks,
    content: hasTextBlock ? textParts.join("") : (message.content ?? ""),
    toolCalls:
      toolCalls.length > 0 ? toolCalls : [...(message.tool_calls ?? [])],
    retrievals:
      retrievals.length > 0 ? retrievals : [...(message.retrievals ?? [])],
  };
}

export function messageHasProcessTrail(
  message: Pick<Message, "role" | "content" | "blocks" | "pendingTool">
): boolean {
  return (
    deriveMessageBlocks(message).some(
      (block) =>
        block.type !== "text" &&
        block.type !== "usage" &&
        block.type !== "plan" &&
        !(
          (block.type === "tool_use" || block.type === "tool_result") &&
          block.tool === "plan_agent"
        )
    ) ||
    (message.pendingTool !== undefined && message.pendingTool.tool !== "plan_agent")
  );
}

export function getMessageToolCalls(
  message: BlockCompatibleMessage
): ToolCall[] {
  return normalizeMessageContent(message).toolCalls;
}

export function getMessageRetrievals(
  message: BlockCompatibleMessage
): RetrievalResult[] {
  return normalizeMessageContent(message).retrievals;
}
