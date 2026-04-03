"use client";

import {
  getEvidenceReviewPayload,
} from "@/lib/evidence";
import { deriveMessageBlocks } from "@/lib/message-blocks";
import { cn } from "@/lib/utils";
import type {
  Message,
  RetrievalResult,
  SessionContentBlock,
  ToolResultEnvelope,
} from "@/lib/types";

interface TurnActivityFeedProps {
  message: Message;
}

type FeedTone = "default" | "active" | "success" | "warning" | "error";
type FeedSectionKey = "thinking" | "planning" | "verification";

interface FeedBlockDescriptor {
  kind: "block";
  title: string;
  detail: string;
  badge?: string | null;
  tone?: FeedTone;
}

interface FeedPlanningDescriptor {
  kind: "planning";
  steps: string[];
  tone?: FeedTone;
}

interface FeedLineDescriptor {
  kind: "line";
  text: string;
  tone?: FeedTone;
}

type FeedEntryDescriptor =
  | FeedBlockDescriptor
  | FeedPlanningDescriptor
  | FeedLineDescriptor;

interface FeedSectionDescriptor {
  key: FeedSectionKey;
  title: string;
  entries: FeedEntryDescriptor[];
}

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

function lineToneClass(tone: FeedTone): string {
  if (tone === "active" || tone === "success") {
    return "text-[var(--apex-accent-strong)]";
  }
  if (tone === "warning") {
    return "text-amber-700";
  }
  if (tone === "error") {
    return "text-rose-700";
  }
  return "text-slate-500";
}

function blockToneClass(tone: FeedTone): string {
  if (tone === "active") {
    return "border-[rgba(35,130,83,0.16)] bg-[linear-gradient(180deg,rgba(248,251,248,0.98),rgba(242,247,243,0.98))]";
  }
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50/90";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50/90";
  }
  if (tone === "error") {
    return "border-rose-200 bg-rose-50/90";
  }
  return "border-[rgba(32,43,35,0.08)] bg-white/92";
}

function badgeToneClass(tone: FeedTone): string {
  if (tone === "active") {
    return "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]";
  }
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (tone === "error") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  return "border-[rgba(32,43,35,0.08)] bg-white/78 text-slate-500";
}

function summarizeRetrievalBlock(results: RetrievalResult[]): FeedLineDescriptor | null {
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

function normalizePlanningKeyword(value: string, maxLength = 38): string | null {
  const normalized = value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }

  const compacted = compactInline(normalized, maxLength);
  return compacted ? sentenceCase(compacted) : null;
}

const PLANNING_STEP_MAX_LENGTH = 72;

function asPlanningStep(value: string): string {
  return value.replace(/[.!?]+$/, "").trim();
}

function abstractPlanningStepId(value: string): string | null {
  const normalized = value
    .replace(/^step[_\s-]*\d+[_\s-]*/i, "")
    .replace(/^step[_\s-]*/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!normalized) {
    return null;
  }

  if (!/[a-z]/i.test(normalized)) {
    return null;
  }

  return normalizePlanningKeyword(normalized, PLANNING_STEP_MAX_LENGTH);
}

function summarizePlanningPhrase(value: string): string | null {
  let normalized = value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }

  const originalLower = normalized.toLowerCase();
  if (originalLower.startsWith("establish the review scope")) {
    return "Establish review scope";
  }
  if (originalLower.startsWith("inspect core files")) {
    return "Inspect core files";
  }
  if (originalLower.startsWith("check for compliance and safety")) {
    return "Review risks and safety";
  }
  if (originalLower.startsWith("summarize likely analysis stages")) {
    return "Outline analysis stages";
  }
  if (originalLower.includes("pipeline stages")) {
    return "Outline pipeline stages";
  }
  if (originalLower.startsWith("inspect external biological references")) {
    return "Inspect biological references";
  }
  if (originalLower.startsWith("synthesize findings")) {
    return "Decide readiness";
  }

  normalized = normalized.replace(/^if\b[^,]*,\s*/i, "");
  normalized = normalized.replace(/\bincluding\b.*$/i, "");
  normalized = normalized.replace(/\bwith\b.*$/i, "");
  normalized = normalized.replace(/\busing\b.*$/i, "");

  const punctuationIndex = normalized.search(/[,:;]/);
  if (punctuationIndex > 0) {
    normalized = normalized.slice(0, punctuationIndex).trim();
  }

  const words = normalized.split(/\s+/);
  if (words.length > 12 && /\sand\s/i.test(normalized)) {
    normalized = normalized.replace(/\sand\s.*$/i, "").trim();
  }

  return normalizePlanningKeyword(normalized, PLANNING_STEP_MAX_LENGTH);
}

function isConcisePlanningPhrase(value: string): boolean {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return false;
  }

  const words = normalized.split(/\s+/);
  return normalized.length <= 34 && words.length <= 6;
}

function extractPlanKeywords(
  block: Extract<SessionContentBlock, { type: "plan" }>
): string[] {
  const keywords: string[] = [];

  const pushKeyword = (raw: unknown, maxLength = 38) => {
    if (typeof raw !== "string") {
      return;
    }

    const normalized = normalizePlanningKeyword(raw, maxLength);
    if (!normalized || keywords.includes(normalized)) {
      return;
    }

    keywords.push(normalized);
  };

  const steps = Array.isArray(block.plan.steps) ? block.plan.steps : [];
  steps.forEach((step) => {
    if (keywords.length >= 3) {
      return;
    }

    if (typeof step === "string") {
      pushKeyword(step);
      return;
    }

    if (!step || typeof step !== "object" || Array.isArray(step)) {
      return;
    }

    const record = step as Record<string, unknown>;
    const conciseCandidates = [
      record.intent,
      record.title,
      record.label,
      record.action,
    ];

    for (const candidate of conciseCandidates) {
      if (typeof candidate === "string" && isConcisePlanningPhrase(candidate)) {
        const before = keywords.length;
        pushKeyword(candidate, PLANNING_STEP_MAX_LENGTH);
        if (keywords.length > before) {
          return;
        }
      }
    }

    if (typeof record.step_id === "string") {
      const stepIdSummary = abstractPlanningStepId(record.step_id);
      if (stepIdSummary) {
        const before = keywords.length;
        pushKeyword(stepIdSummary, PLANNING_STEP_MAX_LENGTH);
        if (keywords.length > before) {
          return;
        }
      }
    }

    const summaryCandidates = [
      record.intent,
      record.title,
      record.label,
      record.description,
      record.action,
      record.tool,
    ];

    for (const candidate of summaryCandidates) {
      if (typeof candidate === "string") {
        const summarized = summarizePlanningPhrase(candidate);
        const before = keywords.length;
        pushKeyword(summarized, PLANNING_STEP_MAX_LENGTH);
        if (keywords.length > before) {
          break;
        }
      }
    }
  });

  if (keywords.length === 0 && Array.isArray(block.tool_trace)) {
    block.tool_trace.forEach((item) => {
      if (keywords.length >= 3) {
        return;
      }

      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return;
      }

      const record = item as Record<string, unknown>;
      const candidates = [record.summary, record.tool];

      for (const candidate of candidates) {
        if (typeof candidate === "string") {
          const summarized = summarizePlanningPhrase(candidate);
          const before = keywords.length;
          pushKeyword(summarized, PLANNING_STEP_MAX_LENGTH);
          if (keywords.length > before) {
            break;
          }
        }
      }
    });
  }

  return keywords;
}

function summarizePlanBlock(
  block: Extract<SessionContentBlock, { type: "plan" }>
): FeedPlanningDescriptor {
  const steps = extractPlanKeywords(block)
    .map(asPlanningStep)
    .filter((step) => step.length > 0);
  const fallback = block.event === "updated" ? "Refine next steps" : "Plan next steps";

  return {
    kind: "planning",
    steps: steps.length > 0 ? steps : [fallback],
    tone: "active",
  };
}

function summarizeVerificationBlock(
  block: Extract<SessionContentBlock, { type: "verification" }>
): FeedBlockDescriptor {
  const verificationRecord =
    block.verification && typeof block.verification === "object"
      ? (block.verification as Record<string, unknown>)
      : null;
  const repairInstructions = Array.isArray(verificationRecord?.repair_instructions)
    ? verificationRecord?.repair_instructions
    : [];
  const issues = Array.isArray(verificationRecord?.issues)
    ? verificationRecord?.issues
    : [];
  const checks = Array.isArray(verificationRecord?.checks)
    ? verificationRecord?.checks
    : [];
  const firstFailingCheck = checks.find((check) => {
    if (!check || typeof check !== "object" || Array.isArray(check)) {
      return false;
    }
    const status = (check as Record<string, unknown>).status;
    return status === "fail" || status === "repair_required";
  }) as Record<string, unknown> | undefined;
  const candidateDetails = [
    typeof block.verification?.summary === "string"
      ? block.verification.summary
      : null,
    typeof repairInstructions[0] === "string" ? repairInstructions[0] : null,
    typeof issues[0] === "string" ? issues[0] : null,
    typeof firstFailingCheck?.note === "string" ? firstFailingCheck.note : null,
    block.summary,
  ];
  let conciseDetail: string | null = null;

  for (const candidate of candidateDetails) {
    if (!candidate) {
      continue;
    }

    const normalized = candidate.replace(/\s+/g, " ").trim();
    if (!normalized) {
      continue;
    }

    const withoutVerdict = normalized.replace(
      /^verifier verdict:\s*[a-z_]+\.\s*/i,
      ""
    );
    const firstSentence = withoutVerdict
      .split(/(?<=[.!?])\s+/)
      .find((sentence) => sentence.trim().length > 0)
      ?.trim();
    const lowerSentence = firstSentence?.toLowerCase() ?? "";

    if (
      block.verdict === "repair_required" &&
      (
        lowerSentence.startsWith("the draft is") ||
        lowerSentence.startsWith("the answer is") ||
        lowerSentence.startsWith("it is") ||
        lowerSentence.startsWith("it gives") ||
        lowerSentence.startsWith("however")
      )
    ) {
      continue;
    }

    if (
      firstSentence &&
      firstSentence.length <= 96 &&
      firstSentence.split(/\s+/).length <= 16
    ) {
      conciseDetail = firstSentence;
      break;
    }

    const firstClause = withoutVerdict.split(/[,:;]/)[0]?.trim();
    if (
      firstClause &&
      firstClause.length <= 96 &&
      firstClause.split(/\s+/).length <= 16
    ) {
      conciseDetail = firstClause;
      break;
    }

    const compacted = compactInline(withoutVerdict, 96);
    if (compacted) {
      conciseDetail = compacted;
      break;
    }
  }

  const fallback =
    block.verdict === "pass"
      ? "Looks good."
      : block.verdict === "repair_required"
        ? "Needs revision."
        : "Check failed.";

  return {
    kind: "block",
    title: "Verification result",
    detail: conciseDetail ?? fallback,
    badge: humanizeValue(block.verdict),
    tone:
      block.verdict === "pass"
        ? "success"
        : block.verdict === "repair_required"
          ? "warning"
          : "error",
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
  const target = shouldShowToolTarget(tool) ? compactInline(input) : null;
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
  const target = shouldShowToolTarget(tool) ? compactInline(input) : null;

  if (tool === "evidence_review") {
    return {
      kind: "line",
      text: "Ran evidence review.",
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
      : compactInline(output)
        ? `Ran ${toolPhrase(tool)}: ${compactInline(output, 72)}`
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

function shouldSuppressSectionToolLine(tool: string): boolean {
  return isPlannerTool(tool);
}

function maybePushSectionPlaceholder(
  sections: Record<FeedSectionKey, FeedEntryDescriptor[]>,
  key: FeedSectionKey
): void {
  if (key !== "planning") {
    return;
  }

  const hasPlanningEntry = sections.planning.some(
    (entry) => entry.kind === "planning"
  );
  if (!hasPlanningEntry) {
    sections.planning.push({
      kind: "planning",
      steps: ["Plan next steps"],
      tone: "active",
    });
  }
}

function makeEmptySections(): Record<FeedSectionKey, FeedEntryDescriptor[]> {
  return {
    thinking: [],
    planning: [],
    verification: [],
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

function buildFeedSections(message: Message, live: boolean): FeedSectionDescriptor[] {
  const blocks = deriveMessageBlocks(message);
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
        sections.planning.push(summarizePlanBlock(block));
        break;
      case "verification":
        sections.verification.push(summarizeVerificationBlock(block));
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
        if (shouldSuppressSectionToolLine(block.tool)) {
          maybePushSectionPlaceholder(sections, sectionKey);
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
          if (shouldSuppressSectionToolLine(block.tool)) {
            maybePushSectionPlaceholder(sections, sectionKey);
          } else {
            sections[sectionKey].push(line);
          }
        }
        break;
      }
      case "usage":
        break;
    }
  });

  if (message.pendingTool && !renderedPendingTool) {
    const sectionKey = sectionKeyForTool(message.pendingTool.tool);
    if (shouldSuppressSectionToolLine(message.pendingTool.tool)) {
      maybePushSectionPlaceholder(sections, sectionKey);
    } else {
      sections[sectionKey].push(
        startedToolLine(message.pendingTool.tool, message.pendingTool.input, true)
      );
    }
  }

  if (
    live &&
    sections.thinking.length === 0 &&
    sections.planning.length === 0 &&
    sections.verification.length === 0
  ) {
    sections.thinking.push(summarizeFallback(message));
  }

  const order: Array<{ key: FeedSectionKey; title: string }> = [
    { key: "thinking", title: "Thinking" },
    { key: "planning", title: "Planning" },
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

function FeedLine({ text, tone = "default" }: Omit<FeedLineDescriptor, "kind">) {
  return (
    <p
      className={cn(
        "font-mono text-[11px] italic leading-5",
        lineToneClass(tone)
      )}
    >
      {text}
    </p>
  );
}

function FeedBlock({
  title,
  detail,
  badge,
  tone = "default",
}: FeedBlockDescriptor) {
  return (
    <div
      className={cn(
        "rounded-[12px] border px-3 py-2 shadow-[0_1px_2px_rgba(32,43,35,0.03)]",
        blockToneClass(tone)
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[11px] font-semibold text-slate-800">{title}</p>
        {badge ? (
          <span
            className={cn(
              "rounded-full border px-2 py-0.5 text-[9px] font-medium tracking-[0.02em]",
              badgeToneClass(tone)
            )}
          >
            {badge}
          </span>
        ) : null}
      </div>
      <p className="mt-1 whitespace-pre-wrap text-[11px] leading-5 text-slate-600">{detail}</p>
    </div>
  );
}

function FeedPlanning({ steps, tone = "active" }: FeedPlanningDescriptor) {
  return (
    <div className="space-y-1">
      {steps.map((step) => (
        <FeedLine key={step} text={step} tone={tone} />
      ))}
    </div>
  );
}

function FeedSection({
  live,
  title,
  entries,
}: {
  live: boolean;
  title: string;
  entries: FeedEntryDescriptor[];
}) {
  const animated = live && (title === "Thinking" || title === "Planning");

  return (
    <div className="space-y-1.5">
      <div className="-mx-2 rounded-[12px] px-2 py-1">
        <p className="font-mono text-[11px] font-medium italic text-slate-500">
          <span className={cn(animated && "apex-thinking-label")}>
            {title}
          </span>
        </p>
      </div>

      <div className="space-y-1.5">
        {entries.map((entry, index) =>
          entry.kind === "block" ? (
            <FeedBlock key={`${title}-${entry.title}-${entry.badge ?? "none"}-${index}`} {...entry} />
          ) : entry.kind === "planning" ? (
            <FeedPlanning key={`${title}-planning-${index}`} {...entry} />
          ) : (
            <FeedLine key={`${title}-${entry.text}-${index}`} {...entry} />
          )
        )}
      </div>
    </div>
  );
}

export default function TurnActivityFeed({ message }: TurnActivityFeedProps) {
  const live = message.isStreaming === true;
  const sections = buildFeedSections(message, live);

  if (!live && sections.length === 0) {
    return null;
  }

  return (
    <section
      role="status"
      aria-live={live ? "polite" : undefined}
      className={cn(
        "apex-process-rail space-y-1.5",
        live ? "apex-transcript-enter" : "mt-3"
      )}
    >
      {sections.map((section) => (
        <FeedSection
          key={section.key}
          live={live}
          title={section.title}
          entries={section.entries}
        />
      ))}
    </section>
  );
}
