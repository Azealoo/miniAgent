import { getEvidenceReviewPayload } from "@/lib/evidence";
import { deriveMessageBlocks } from "@/lib/message-blocks";
import type {
  Message,
  RetrievalResult,
  SessionContentBlock,
  ToolResultEnvelope,
  WorkflowStepState,
} from "@/lib/types";
import type {
  FeedEntryDescriptor,
  FeedLineDescriptor,
  FeedPlanningDescriptor,
  FeedSectionDescriptor,
  FeedSectionKey,
  FeedTone,
} from "./blocks/types";

function humanizeValue(value?: string | null): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

function sentenceCase(value: string): string {
  if (!value) return value;
  return value[0].toUpperCase() + value.slice(1);
}

function compactInline(value?: string | null, maxLength = 88): string | null {
  if (!value) return null;

  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }

  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength - 1)}…`;
}

function looksStructuredInline(value?: string | null): boolean {
  if (!value) {
    return false;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }

  return (
    (trimmed.startsWith("{") && /":\s*/.test(trimmed)) ||
    (trimmed.startsWith("[") && /[\]"}]/.test(trimmed)) ||
    trimmed.includes('{"') ||
    trimmed.includes('["') ||
    trimmed.includes('":')
  );
}

function compactUserFacingInline(
  value?: string | null,
  maxLength = 88
): string | null {
  const compacted = compactInline(value, maxLength);
  if (!compacted || looksStructuredInline(compacted)) {
    return null;
  }

  return compacted;
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function displaySourceLabel(source: string): string | null {
  const trimmed = source.trim();
  if (!trimmed) {
    return null;
  }

  if (/(^|[^a-z])memory([^a-z]|$)/i.test(trimmed)) {
    return "memory";
  }

  const normalized = trimmed.replace(/\\/g, "/");
  return compactInline(normalized.split("/").pop() ?? normalized, 52);
}

function joinLabels(labels: string[], noun: string): string {
  if (labels.length === 0) {
    return noun;
  }
  if (labels.length === 1) {
    return labels[0];
  }
  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`;
  }

  return `${labels[0]}, ${labels[1]}, and ${labels.length - 2} more ${noun}${labels.length - 2 === 1 ? "" : "s"}`;
}

function summarizeRetrievalBlock(
  results: RetrievalResult[]
): FeedLineDescriptor | null {
  if (results.length === 0) {
    return null;
  }

  const labels = Array.from(
    new Set(
      results
        .map((result) => displaySourceLabel(result.source))
        .filter((value): value is string => Boolean(value))
    )
  );

  if (labels.length === 0) {
    return {
      kind: "line",
      text: "Looked at retrieved context.",
      tone: "active",
    };
  }

  if (labels.length === 1 && labels[0] === "memory") {
    return {
      kind: "line",
      text: "Looked at memory.",
      tone: "active",
    };
  }

  return {
    kind: "line",
    text: `Looked at ${joinLabels(labels, "source")}.`,
    tone: "active",
  };
}

function summarizePlanBlock(
  block: Extract<SessionContentBlock, { type: "plan" }>
): FeedPlanningDescriptor {
  const stepCount = Array.isArray(block.plan.steps) ? block.plan.steps.length : null;
  const fallback =
    block.event === "updated" ? "Updated the plan." : "Prepared a plan.";
  const summary =
    typeof stepCount === "number" && stepCount > 0
      ? block.event === "updated"
        ? `Updated the ${stepCount}-step plan.`
        : `Prepared a ${stepCount}-step plan.`
      : fallback;
  const stepSummaries = summarizePlanSteps(block.plan.steps);

  return {
    kind: "planning",
    steps: [summary, ...stepSummaries],
    tone: "active",
  };
}

function summarizeToolTraceLines(toolTrace: unknown): FeedLineDescriptor[] {
  if (!Array.isArray(toolTrace)) {
    return [];
  }

  return toolTrace.flatMap((entry) => {
    if (!isObjectRecord(entry)) {
      return [];
    }

    const tool = typeof entry.tool === "string" ? entry.tool : null;
    if (!tool || tool === "plan_agent" || tool === "verification_agent") {
      return [];
    }

    const input = typeof entry.input === "string" ? entry.input : "";
    const output =
      typeof entry.output === "string"
        ? entry.output
        : "";
    const line = completedToolLine(tool, input, output);
    return line ? [line] : [];
  });
}

function readablePlanStepId(stepId?: string | null): string | null {
  if (!stepId) {
    return null;
  }

  const normalized = stepId
    .replace(/^step[_-]?\d+[_-]?/i, "")
    .replace(/^s\d+$/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized || !/[a-z]/i.test(normalized)) {
    return null;
  }

  const compacted = compactInline(normalized, 40);
  if (!compacted) {
    return null;
  }

  const terminal = compacted.endsWith("…") ? compacted : `${compacted}.`;
  return sentenceCase(terminal);
}

function readablePlanStepText(value?: string | null): string | null {
  if (!value) {
    return null;
  }

  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }

  const withoutTerminal = normalized.replace(/[.!?]+$/, "");
  const terminal = withoutTerminal.endsWith("…")
    ? withoutTerminal
    : `${withoutTerminal}.`;
  return sentenceCase(terminal);
}

function summarizePlanSteps(stepsValue: unknown): string[] {
  if (!Array.isArray(stepsValue)) {
    return [];
  }

  return stepsValue
    .flatMap((step, index) => {
      if (typeof step === "string") {
        const summary = readablePlanStepText(step);
        return summary ? [`${index + 1}. ${summary}`] : [];
      }

      if (!step || typeof step !== "object" || Array.isArray(step)) {
        return [`${index + 1}. Step ${index + 1}.`];
      }

      const stepRecord = step as Record<string, unknown>;
      const primaryTextCandidate =
        typeof stepRecord.intent === "string"
          ? stepRecord.intent
          : typeof stepRecord.title === "string"
            ? stepRecord.title
            : typeof stepRecord.label === "string"
              ? stepRecord.label
              : typeof stepRecord.description === "string"
                ? stepRecord.description
                : typeof stepRecord.action === "string"
                  ? stepRecord.action
                  : typeof stepRecord.exit_criteria === "string"
                    ? stepRecord.exit_criteria
                    : null;
      const intentSummary = readablePlanStepText(primaryTextCandidate);
      const stepIdSummary = readablePlanStepId(
        typeof stepRecord.step_id === "string" ? stepRecord.step_id : null
      );
      const summary = intentSummary ?? stepIdSummary ?? `Step ${index + 1}.`;

      return summary ? [`${index + 1}. ${summary}`] : [];
    });
}

function verificationTone(
  verdict: Extract<SessionContentBlock, { type: "verification" }>["verdict"]
): FeedTone {
  return verdict === "pass"
    ? "success"
    : verdict === "repair_required"
      ? "warning"
      : "error";
}

function verificationOutcomeLine(
  verdict: Extract<SessionContentBlock, { type: "verification" }>["verdict"]
): string {
  if (verdict === "pass") {
    return "Passed verification.";
  }
  if (verdict === "repair_required") {
    return "Needs revision before delivery.";
  }
  return "Verification failed.";
}

function verificationDetailTone(
  verdict: Extract<SessionContentBlock, { type: "verification" }>["verdict"],
  status?: string | null
): FeedTone {
  if (status === "pass") {
    return "success";
  }
  if (status === "fail") {
    return verdict === "fail" ? "error" : "warning";
  }
  if (status === "not_run") {
    return "default";
  }
  if (verdict === "pass") {
    return "success";
  }
  if (verdict === "fail") {
    return "error";
  }
  return "warning";
}

function sentenceWithDetail(prefix: string, detail?: string | null): string {
  const normalizedPrefix = prefix.replace(/[.!?]+$/, "").trim();
  const normalizedDetail = detail?.replace(/\s+/g, " ").trim();

  if (!normalizedDetail) {
    return `${normalizedPrefix}.`;
  }

  return `${normalizedPrefix}: ${normalizedDetail}`;
}

function summarizeVerificationChecks(
  verdict: Extract<SessionContentBlock, { type: "verification" }>["verdict"],
  verification: Record<string, unknown> | null
): FeedLineDescriptor[] {
  const checks = Array.isArray(verification?.checks) ? verification.checks : [];

  return checks.flatMap((check) => {
    if (!isObjectRecord(check)) {
      return [];
    }

    const status =
      check.status === "pass" || check.status === "fail" || check.status === "not_run"
        ? check.status
        : null;
    const name = compactInline(
      typeof check.name === "string" ? humanizeValue(check.name) : null,
      42
    );
    const note = compactUserFacingInline(
      typeof check.note === "string" ? check.note : null,
      104
    );

    const prefix =
      status === "pass"
        ? `${sentenceCase(name ?? "Check")} check passed`
        : status === "fail"
          ? `${sentenceCase(name ?? "Check")} check failed`
          : `${sentenceCase(name ?? "Check")} check not run`;

    return [
      {
        kind: "line",
        text: sentenceWithDetail(prefix, note),
        tone: verificationDetailTone(verdict, status),
      },
    ];
  });
}

function summarizeVerificationActions(
  verdict: Extract<SessionContentBlock, { type: "verification" }>["verdict"],
  verification: Record<string, unknown> | null
): FeedLineDescriptor[] {
  const actionValues = Array.isArray(verification?.repair_instructions)
    ? verification?.repair_instructions
    : Array.isArray(verification?.issues)
      ? verification?.issues
      : [];
  const seen = new Set<string>();

  return actionValues.flatMap((value) => {
    if (typeof value !== "string") {
      return [];
    }

    const text = readablePlanStepText(value);
    if (!text || seen.has(text)) {
      return [];
    }

    seen.add(text);
    return [
      {
        kind: "line",
        text,
        tone: verificationDetailTone(verdict),
      },
    ];
  });
}

function summarizeVerificationBlock(
  block: Extract<SessionContentBlock, { type: "verification" }>
): FeedLineDescriptor[] {
  const tone = verificationTone(block.verdict);
  const verification = isObjectRecord(block.verification) ? block.verification : null;
  const detailLines = [
    ...summarizeToolTraceLines(block.tool_trace),
    ...summarizeVerificationChecks(block.verdict, verification),
    ...summarizeVerificationActions(block.verdict, verification),
  ];

  return [
    {
      kind: "line",
      text: verificationOutcomeLine(block.verdict),
      tone,
    },
    ...detailLines,
  ];
}

function summarizeWarningBlock(
  block: Extract<SessionContentBlock, { type: "warning" }>
): FeedLineDescriptor | null {
  const message = compactInline(block.message, 160);
  if (!message) {
    return null;
  }
  return {
    kind: "line",
    text: message,
    tone: "warning",
  };
}

function toolPhrase(tool: string): string {
  switch (tool) {
    case "plan_agent":
      return "planning";
    case "verification_agent":
      return "verification";
    case "evidence_review":
      return "evidence review";
    case "evidence_retrieval":
    case "search_knowledge_base":
      return "source search";
    default:
      return humanizeValue(tool).toLowerCase();
  }
}

function shouldShowToolTarget(tool: string): boolean {
  if (
    tool === "plan_agent" ||
    tool === "verification_agent" ||
    tool === "evidence_review" ||
    tool === "evidence_retrieval" ||
    tool === "search_knowledge_base"
  ) {
    return false;
  }

  return !tool.toLowerCase().includes("memory");
}

function evidenceReviewStatus(result?: ToolResultEnvelope): string | null {
  const payload = getEvidenceReviewPayload(result);
  const reviewStatus = payload?.review_status;
  return typeof reviewStatus === "string" ? reviewStatus : null;
}

function evidenceReviewUnsupported(result?: ToolResultEnvelope): boolean {
  const payload = getEvidenceReviewPayload(result);
  return payload?.unsupported_claims_present === true;
}

function outcomeTone(result?: ToolResultEnvelope): FeedTone {
  if (!result) return "default";

  const reviewStatus = evidenceReviewStatus(result);
  if (evidenceReviewUnsupported(result)) return "error";
  if (reviewStatus === "mixed") return "warning";
  if (reviewStatus === "supported") return "success";

  if (
    result.status === "error" ||
    result.warnings.some((warning) => warning.includes("blocked") || warning.includes("violation"))
  ) {
    return "error";
  }
  if (result.warnings.length > 0) return "warning";
  if (result.outcome === "success_empty") return "warning";
  return "success";
}

function startedToolLine(
  tool: string,
  input: string,
  isPending: boolean
): FeedLineDescriptor {
  const target = shouldShowToolTarget(tool)
    ? compactUserFacingInline(input)
    : null;
  return {
    kind: "line",
    text: sentenceCase(
      target
        ? `${isPending ? "Running" : "Started"} ${toolPhrase(tool)} on ${target}.`
        : `${isPending ? "Running" : "Started"} ${toolPhrase(tool)}.`
    ),
    tone: isPending ? "active" : "default",
  };
}

function completedToolLine(
  tool: string,
  input: string,
  output: string,
  result?: ToolResultEnvelope
): FeedLineDescriptor | null {
  const target = shouldShowToolTarget(tool)
    ? compactUserFacingInline(input)
    : null;
  const detail = compactUserFacingInline(output, 72);

  if (tool === "evidence_review") {
    return {
      kind: "line",
      text: "Ran evidence review.",
      tone: outcomeTone(result),
    };
  }

  if (tool === "verification_agent") {
    return {
      kind: "line",
      text: "Ran verification.",
      tone: outcomeTone(result),
    };
  }

  if (result?.status === "error") {
    return {
      kind: "line",
      text: `${sentenceCase(toolPhrase(tool))} hit an error.`,
      tone: "error",
    };
  }

  if (tool.toLowerCase().includes("memory")) {
    return {
      kind: "line",
      text: "Used memory.",
      tone: outcomeTone(result),
    };
  }

  return {
    kind: "line",
    text: target
      ? `Ran ${toolPhrase(tool)} on ${target}.`
      : detail
        ? `Ran ${toolPhrase(tool)}: ${detail}`
        : `Ran ${toolPhrase(tool)}.`,
    tone: outcomeTone(result),
  };
}

function toolBlockKey(tool: string, runId?: string): string {
  return `${tool}::${runId ?? "__pending__"}`;
}

function isPlannerTool(tool: string): boolean {
  return tool === "plan_agent";
}

function isVerificationTool(tool: string): boolean {
  return tool === "verification_agent";
}

function sectionKeyForTool(tool: string): FeedSectionKey {
  if (isPlannerTool(tool)) {
    return "planning";
  }
  if (isVerificationTool(tool)) {
    return "verification";
  }
  return "thinking";
}

function shouldSuppressSectionToolLine(
  tool: string,
  hasVerificationResult: boolean
): boolean {
  return isPlannerTool(tool) || (hasVerificationResult && isVerificationTool(tool));
}

function maybePushSectionPlaceholder(
  sections: Record<FeedSectionKey, FeedEntryDescriptor[]>,
  key: FeedSectionKey,
  allowPlaceholder: boolean
): void {
  if (key !== "planning" || !allowPlaceholder) {
    return;
  }

  const hasPlanningEntry = sections.planning.some(
    (entry) => entry.kind === "planning"
  );
  if (!hasPlanningEntry) {
    sections.planning.push({
      kind: "planning",
      steps: ["Planning next steps."],
      tone: "active",
    });
  }
}

function makeEmptySections(): Record<FeedSectionKey, FeedEntryDescriptor[]> {
  return {
    thinking: [],
    planning: [],
    verification: [],
    workflow: [],
  };
}

function summarizeWorkflowStep(step: WorkflowStepState): FeedLineDescriptor {
  const position = `${step.step_index}/${step.total_steps}`;
  const label = step.label ?? step.step_id;
  const attemptSuffix = step.attempt > 1 ? ` (attempt ${step.attempt})` : "";
  if (step.status === "running") {
    return {
      kind: "line",
      text: `Step ${position}: ${label} — running${attemptSuffix}`,
      tone: "active",
    };
  }
  if (step.status === "ok") {
    const duration =
      typeof step.duration_ms === "number" ? ` in ${step.duration_ms} ms` : "";
    return {
      kind: "line",
      text: `Step ${position}: ${label} — done${duration}${attemptSuffix}`,
      tone: "success",
    };
  }
  const errorSuffix = step.error ? `: ${step.error}` : "";
  return {
    kind: "line",
    text: `Step ${position}: ${label} — failed${attemptSuffix}${errorSuffix}`,
    tone: "error",
  };
}

function summarizeFallback(message: Message): FeedLineDescriptor {
  if (message.content.trim()) {
    return {
      kind: "line",
      text: "Drafting answer.",
      tone: "active",
    };
  }

  return {
    kind: "line",
    text: "Preparing next step.",
    tone: "active",
  };
}

export function buildFeedSections(
  message: Message,
  live: boolean
): FeedSectionDescriptor[] {
  const blocks = deriveMessageBlocks(message);
  const hasVerificationBlock = blocks.some((block) => block.type === "verification");
  const sections = makeEmptySections();
  const pendingUses = new Map<string, Array<{ input: string; runId?: string }>>();
  let renderedPendingTool = false;

  blocks.forEach((block) => {
    switch (block.type) {
      case "text":
        break;
      case "retrieval": {
        const line = summarizeRetrievalBlock(block.results);
        if (line) {
          sections.thinking.push(line);
        }
        break;
      }
      case "plan":
        sections.thinking.push(...summarizeToolTraceLines(block.tool_trace));
        sections.planning = [summarizePlanBlock(block)];
        break;
      case "verification":
        sections.verification.push(...summarizeVerificationBlock(block));
        break;
      case "tool_use": {
        const key = toolBlockKey(block.tool, block.run_id);
        const queue = pendingUses.get(key) ?? [];
        queue.push({ input: block.input, runId: block.run_id });
        pendingUses.set(key, queue);

        const isPending = message.pendingTool?.runId === block.run_id;
        if (isPending) {
          renderedPendingTool = true;
        }
        const sectionKey = sectionKeyForTool(block.tool);
        if (sectionKey === "planning") {
          maybePushSectionPlaceholder(sections, sectionKey, true);
          break;
        }
        if (shouldSuppressSectionToolLine(block.tool, hasVerificationBlock)) {
          maybePushSectionPlaceholder(sections, sectionKey, false);
        } else {
          sections[sectionKey].push(startedToolLine(block.tool, block.input, isPending));
        }
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

        const line = completedToolLine(
          block.tool,
          started?.input ?? "",
          block.output,
          block.result
        );
        if (line) {
          const sectionKey = sectionKeyForTool(block.tool);
          if (sectionKey === "planning") {
            break;
          }
          if (shouldSuppressSectionToolLine(block.tool, hasVerificationBlock)) {
            maybePushSectionPlaceholder(sections, sectionKey, false);
          } else {
            sections[sectionKey].push(line);
          }
        }
        break;
      }
      case "approval_gate": {
        sections.thinking.push({ kind: "gate", block });
        break;
      }
      case "warning": {
        const line = summarizeWarningBlock(block);
        if (line) {
          sections.thinking.push(line);
        }
        break;
      }
      case "usage":
        break;
    }
  });

  if (message.pendingTool && !renderedPendingTool) {
    const sectionKey = sectionKeyForTool(message.pendingTool.tool);
    if (sectionKey === "planning") {
      maybePushSectionPlaceholder(sections, sectionKey, true);
      renderedPendingTool = true;
    } else if (shouldSuppressSectionToolLine(message.pendingTool.tool, hasVerificationBlock)) {
      maybePushSectionPlaceholder(sections, sectionKey, false);
    } else {
      sections[sectionKey].push(
        startedToolLine(message.pendingTool.tool, message.pendingTool.input, true)
      );
    }
  }

  const workflowSteps = message.workflowSteps ?? [];
  if (workflowSteps.length > 0) {
    sections.workflow.push(
      ...workflowSteps.map((step) => summarizeWorkflowStep(step))
    );
  }

  if (
    live &&
    sections.thinking.length === 0 &&
    sections.verification.length === 0 &&
    sections.workflow.length === 0
  ) {
    sections.thinking.push(summarizeFallback(message));
  }

  const order: Array<{ key: FeedSectionKey; title: string }> = [
    { key: "thinking", title: "Thinking" },
    { key: "planning", title: "Planning" },
    { key: "workflow", title: "Workflow" },
    { key: "verification", title: "Verification" },
  ];

  return order
    .map(({ key, title }) => ({
      key,
      title,
      entries: sections[key],
    }))
    .filter((section) => section.entries.length > 0);
}
