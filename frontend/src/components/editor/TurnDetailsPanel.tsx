"use client";

import type { LucideIcon } from "lucide-react";
import {
  Brain,
  Clock3,
  FileText,
  LoaderCircle,
  Search,
  ShieldAlert,
  Terminal,
} from "lucide-react";
import { compactText, shortIdentifier } from "@/lib/format";
import {
  deriveMessageBlocks,
  normalizeMessageContent,
} from "@/lib/message-blocks";
import { cn } from "@/lib/utils";
import type {
  Message,
  RetrievalResult,
  SessionContentBlock,
  SessionToolResultBlock,
  ToolResultEnvelope,
} from "@/lib/types";

interface TurnDetailsPanelProps {
  messages: Message[];
}

type RowTone = "default" | "active" | "success" | "warning" | "error";

interface BlockRowDescriptor {
  title: string;
  detail: string;
  badge?: string | null;
  icon: LucideIcon;
  tone?: RowTone;
  spin?: boolean;
}

function humanizeValue(value?: string | null): string {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

function titleCase(value: string): string {
  return value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function stripCommonExtension(value: string): string {
  return value.replace(/\.(md|markdown|txt|json|yaml|yml)$/i, "");
}

function displaySourceLabel(source: string): string {
  const trimmed = source.trim();
  if (!trimmed) return "retrieved context";
  const normalized = trimmed.replace(/\\/g, "/");
  const basename = normalized.split("/").pop() ?? normalized;
  return stripCommonExtension(basename) || trimmed;
}

function summarizeRetrieval(results: RetrievalResult[]): BlockRowDescriptor {
  const uniqueSources = Array.from(
    new Set(results.map((result) => displaySourceLabel(result.source)))
  );
  const sourcePreview = uniqueSources.slice(0, 3).join(", ");
  const strongestSnippet = compactText(
    results
      .slice()
      .sort((left, right) => right.score - left.score)
      .map((result) => result.text)
      .find((value) => value.trim().length > 0),
    120
  );

  return {
    title: "Knowledge retrieval",
    detail:
      [sourcePreview, strongestSnippet]
        .filter((value): value is string => Boolean(value))
        .join(" / ") || "Retrieved context for this turn.",
    badge: `${uniqueSources.length} source${uniqueSources.length === 1 ? "" : "s"}`,
    icon: results.length > 1 ? Brain : Search,
    tone: "active",
  };
}

function summarizeToolResult(result?: ToolResultEnvelope): {
  badge: string;
  tone: RowTone;
} {
  if (!result) {
    return { badge: "completed", tone: "default" };
  }

  const blockingWarning = result.warnings.find(
    (warning) => warning.includes("blocked") || warning.includes("violation")
  );
  if (blockingWarning) {
    return {
      badge: blockingWarning.replaceAll("_", " "),
      tone: "error",
    };
  }

  if (result.warnings.length > 0) {
    return {
      badge: result.warnings[0].replaceAll("_", " "),
      tone: "warning",
    };
  }

  if (result.status === "error") {
    return { badge: result.outcome.replaceAll("_", " "), tone: "error" };
  }

  return {
    badge: result.outcome.replaceAll("_", " "),
    tone: result.outcome === "success" ? "success" : "default",
  };
}

function summarizeToolResultBlock(block: SessionToolResultBlock): BlockRowDescriptor {
  const toolLabel = titleCase(humanizeValue(block.tool));
  const summary = summarizeToolResult(block.result);

  return {
    title: toolLabel,
    detail:
      compactText(
        block.result?.summary ??
          block.result?.error?.message ??
          block.output,
        120
      ) ?? "Tool completed.",
    badge: summary.badge,
    icon: Terminal,
    tone: summary.tone,
  };
}

function summarizeUsage(metadata: Record<string, unknown>): BlockRowDescriptor {
  const metrics = [
    typeof metadata.total_tokens === "number"
      ? `${metadata.total_tokens.toLocaleString()} total tokens`
      : null,
    typeof metadata.input_tokens === "number"
      ? `${metadata.input_tokens.toLocaleString()} input`
      : null,
    typeof metadata.output_tokens === "number"
      ? `${metadata.output_tokens.toLocaleString()} output`
      : null,
    typeof metadata.tool_tokens === "number"
      ? `${metadata.tool_tokens.toLocaleString()} tools`
      : null,
  ].filter((value): value is string => Boolean(value));

  return {
    title: "Usage",
    detail:
      metrics.join(" / ") ||
      `${Object.keys(metadata).length} usage field${Object.keys(metadata).length === 1 ? "" : "s"} recorded`,
    badge: "captured",
    icon: Clock3,
    tone: "default",
  };
}

function summarizePlanBlock(
  block: Extract<SessionContentBlock, { type: "plan" }>
): BlockRowDescriptor {
  const steps = Array.isArray(block.plan.steps) ? block.plan.steps.length : null;
  const detail =
    typeof steps === "number"
      ? `${steps} planning step${steps === 1 ? "" : "s"} captured for this turn.`
      : "Planning process captured for this turn.";

  return {
    title: "Planning",
    detail,
    badge: block.event,
    icon: Brain,
    tone: "active",
  };
}

function summarizeVerificationBlock(
  block: Extract<SessionContentBlock, { type: "verification" }>
): BlockRowDescriptor {
  const checks = Array.isArray(block.verification.checks)
    ? block.verification.checks.length
    : null;
  const detail =
    typeof checks === "number"
      ? `${checks} verification check${checks === 1 ? "" : "s"} captured for this turn.`
      : block.verdict === "pass"
        ? "Verification passed for this turn."
        : block.verdict === "repair_required"
          ? "Verification requested revisions for this turn."
          : "Verification failed for this turn.";

  return {
    title: "Verification result",
    detail,
    badge: humanizeValue(block.verdict),
    icon: block.verdict === "pass" ? Brain : ShieldAlert,
    tone:
      block.verdict === "pass"
        ? "success"
        : block.verdict === "repair_required"
          ? "warning"
          : "error",
  };
}

function rowToneClass(tone: RowTone): string {
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

function badgeToneClass(tone: RowTone): string {
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

function BlockRow({
  title,
  detail,
  badge,
  icon: Icon,
  tone = "default",
  spin = false,
}: BlockRowDescriptor) {
  return (
    <div
      className={cn(
        "rounded-[12px] border px-3 py-2.5 shadow-[0_1px_2px_rgba(32,43,35,0.03)]",
        rowToneClass(tone)
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(32,43,35,0.08)] bg-[rgba(248,250,247,0.96)] text-[var(--apex-accent-strong)]">
          <Icon size={13} className={spin ? "animate-spin" : undefined} />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[12px] font-semibold text-slate-800">{title}</p>
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
          <p className="mt-0.5 whitespace-pre-wrap text-[11px] leading-5 text-slate-600">
            {detail}
          </p>
        </div>
      </div>
    </div>
  );
}

function renderBlockRow(message: Message, block: SessionContentBlock): BlockRowDescriptor | null {
  switch (block.type) {
    case "text":
      return {
        title: message.role === "user" ? "Prompt" : "Response",
        detail: block.text,
        icon: FileText,
        tone: "default",
      };
    case "tool_use":
      return {
        title: titleCase(humanizeValue(block.tool)),
        detail: compactText(block.input, 120) ?? "Tool call started.",
        badge: "started",
        icon: Terminal,
        tone: "active",
      };
    case "tool_result":
      return summarizeToolResultBlock(block);
    case "retrieval":
      return summarizeRetrieval(block.results);
    case "usage":
      return summarizeUsage(block.metadata);
    case "plan":
      return summarizePlanBlock(block);
    case "verification":
      return summarizeVerificationBlock(block);
    default:
      return null;
  }
}

export default function TurnDetailsPanel({ messages }: TurnDetailsPanelProps) {
  if (messages.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2.5">
      {messages.map((message, index) => {
        const blocks = deriveMessageBlocks(message);
        const normalizedAssistantContent =
          message.role === "assistant"
            ? normalizeMessageContent(message).content.trim()
            : null;
        let renderedAssistantResponse = false;
        const detailCount = blocks.length + (message.pendingTool ? 1 : 0);
        const requestLabel = shortIdentifier(message.request_id);

        return (
          <section
            key={message.id}
            className="rounded-[14px] border border-[rgba(211,219,210,0.8)] bg-[rgba(251,252,248,0.88)] px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em]",
                  message.role === "assistant"
                    ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
                    : "border-[rgba(32,43,35,0.08)] bg-white/78 text-slate-600"
                )}
              >
                {message.role}
              </span>
              <span className="text-[10px] text-slate-400">Message {index + 1}</span>
              {requestLabel ? (
                <span className="rounded-full border border-[rgba(32,43,35,0.08)] bg-white/82 px-2 py-0.5 text-[9px] font-medium text-slate-500">
                  {requestLabel}
                </span>
              ) : null}
              {message.isStreaming ? (
                <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.1)] px-2 py-0.5 text-[9px] font-medium text-[var(--apex-accent-strong)]">
                  <LoaderCircle size={10} className="animate-spin" />
                  Streaming
                </span>
              ) : null}
              <span className="text-[10px] text-slate-400">
                {detailCount} detail row{detailCount === 1 ? "" : "s"}
              </span>
            </div>

            <div className="mt-2.5 space-y-2">
              {blocks.map((block, blockIndex) => {
                if (block.type === "text" && message.role === "assistant") {
                  if (renderedAssistantResponse || !normalizedAssistantContent) {
                    return null;
                  }
                  renderedAssistantResponse = true;
                }

                const row =
                  block.type === "text" && message.role === "assistant"
                    ? {
                        title: "Response",
                        detail: normalizedAssistantContent ?? "",
                        icon: FileText,
                        tone: "default" as const,
                      }
                    : renderBlockRow(message, block);
                if (!row) {
                  return null;
                }

                return (
                  <BlockRow
                    key={`${message.id}-${block.type}-${blockIndex}`}
                    {...row}
                  />
                );
              })}

              {message.pendingTool ? (
                <BlockRow
                  title={titleCase(humanizeValue(message.pendingTool.tool))}
                  detail={
                    compactText(message.pendingTool.input, 120) ??
                    "Tool execution is still running."
                  }
                  badge="running"
                  icon={Terminal}
                  tone="active"
                  spin
                />
              ) : null}
            </div>
          </section>
        );
      })}
    </div>
  );
}
