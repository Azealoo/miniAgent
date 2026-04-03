"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ChevronDown,
  ChevronRight,
  Package,
  Search,
  Wrench,
} from "lucide-react";
import ChatMessage from "@/components/chat/ChatMessage";
import * as api from "@/lib/api";
import { normalizeMessageContent } from "@/lib/message-blocks";
import { cn } from "@/lib/utils";
import type {
  Message,
  SessionContinuitySummary,
} from "@/lib/types";

const RECENT_TURN_COUNT = 3;

interface HistoryTurnSummary {
  id: string;
  messages: Message[];
  requestLabel: string;
  detail: string;
  toolCount: number;
  artifactCount: number;
  retrievalCount: number;
}

interface ArchiveLoadState {
  error: string | null;
  messages: Message[];
  status: "idle" | "loading" | "ready" | "error";
}

function compactText(value?: string | null, maxLength = 132): string | null {
  if (!value) return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1)}…`;
}

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function summaryBadgeClass(
  tone: "neutral" | "warning" | "approval" | "blocked"
): string {
  if (tone === "blocked") {
    return "border-[rgba(244,63,94,0.18)] bg-[rgba(255,241,242,0.95)] text-rose-700";
  }
  if (tone === "approval" || tone === "warning") {
    return "border-[rgba(217,119,6,0.18)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }
  return "border-[rgba(211,219,210,0.92)] bg-[rgba(248,250,246,0.96)] text-slate-600";
}

function groupMessagesIntoTurns(messages: Message[]): Message[][] {
  const turns: Message[][] = [];
  let currentTurn: Message[] = [];

  for (const message of messages) {
    if (message.role === "user") {
      if (currentTurn.length > 0) {
        turns.push(currentTurn);
      }
      currentTurn = [message];
      continue;
    }

    if (currentTurn.length === 0) {
      currentTurn = [message];
      continue;
    }

    currentTurn.push(message);
  }

  if (currentTurn.length > 0) {
    turns.push(currentTurn);
  }

  return turns;
}

function assistantMessagesForTurn(messages: Message[]): Message[] {
  return messages.filter((message) => message.role === "assistant");
}

function artifactCountForTurn(messages: Message[]): number {
  const artifactPaths = new Set<string>();

  for (const message of assistantMessagesForTurn(messages)) {
    for (const call of message.tool_calls ?? []) {
      for (const artifact of call.result?.artifact_refs ?? []) {
        if (artifact.path) {
          artifactPaths.add(artifact.path);
        }
      }
    }
  }

  return artifactPaths.size;
}

function summarizeTurn(messages: Message[]): HistoryTurnSummary {
  const assistants = assistantMessagesForTurn(messages);
  const firstUserMessage = messages.find((message) => message.role === "user");
  const firstAssistantText = assistants
    .map((message) => compactText(message.content, 180))
    .find((value): value is string => Boolean(value));
  const firstRetrievalQuery = assistants
    .flatMap((message) => message.retrievals ?? [])
    .map((result) => compactText(result.text, 120))
    .find((value): value is string => Boolean(value));

  return {
    id: messages[0]?.request_id ?? messages[0]?.id ?? `${messages.length}`,
    messages,
    requestLabel:
      compactText(firstUserMessage?.content, 92) ??
      compactText(firstAssistantText, 92) ??
      compactText(firstRetrievalQuery, 92) ??
      "Earlier turn",
    detail:
      firstAssistantText ??
      compactText(firstRetrievalQuery, 180) ??
      "Tools, retrieval activity, and assistant output were recorded in this turn.",
    toolCount: assistants.reduce(
      (total, message) => total + (message.tool_calls?.length ?? 0),
      0
    ),
    artifactCount: artifactCountForTurn(messages),
    retrievalCount: assistants.reduce(
      (total, message) => total + (message.retrievals?.length ?? 0),
      0
    ),
  };
}

function continuityLead(summary: SessionContinuitySummary): string {
  return (
    compactText(summary.decisions_and_rationale[0], 160) ??
    compactText(summary.results_register[0], 160) ??
    compactText(summary.legacy_summary, 160) ??
    "Earlier archived BioAPEX work is summarized here."
  );
}

function continuityDetail(summary: SessionContinuitySummary): string {
  return (
    compactText(summary.open_questions_and_next_actions[0], 180) ??
    compactText(summary.evidence_register[0], 180) ??
    "Expand this archived summary to review the older saved turns."
  );
}

function HistoryBadge({
  children,
  tone = "neutral",
  icon,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "warning" | "approval" | "blocked";
  icon?: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        summaryBadgeClass(tone)
      )}
    >
      {icon}
      {children}
    </span>
  );
}

function HistorySection({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-[22px] border border-[rgba(211,219,210,0.92)] bg-white/92 p-4 shadow-[0_8px_24px_rgba(29,42,33,0.04)] sm:p-5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
        {eyebrow}
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-3xl">
          <h3 className="text-[0.98rem] font-semibold tracking-[-0.01em] text-slate-800">
            {title}
          </h3>
          <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
        </div>
      </div>
      <div className="mt-4 space-y-3">{children}</div>
    </section>
  );
}

export default function SessionHistorySummary({
  currentSessionId,
  messages,
  continuitySummaries,
}: {
  currentSessionId: string | null;
  messages: Message[];
  continuitySummaries: SessionContinuitySummary[];
}) {
  const [expandedTurnIds, setExpandedTurnIds] = useState<Record<string, boolean>>({});
  const [archiveStates, setArchiveStates] = useState<Record<string, ArchiveLoadState>>({});

  useEffect(() => {
    setExpandedTurnIds({});
    setArchiveStates({});
  }, [currentSessionId]);

  const turnGroups = useMemo(() => groupMessagesIntoTurns(messages), [messages]);
  const olderTurns = useMemo(() => {
    const older = turnGroups.slice(0, Math.max(0, turnGroups.length - RECENT_TURN_COUNT));
    return older.map((turn) => summarizeTurn(turn));
  }, [turnGroups]);
  const recentMessages = useMemo(
    () =>
      turnGroups.length > RECENT_TURN_COUNT
        ? turnGroups.slice(-RECENT_TURN_COUNT).flat()
        : messages,
    [messages, turnGroups]
  );

  const toggleOlderTurn = (turnId: string) => {
    setExpandedTurnIds((current) => ({
      ...current,
      [turnId]: !current[turnId],
    }));
  };

  const toggleArchiveSummary = async (summary: SessionContinuitySummary) => {
    const archiveId = summary.archive_id;
    if (!archiveId || !currentSessionId) {
      return;
    }

    const existing = archiveStates[archiveId];
    if (existing?.status === "ready") {
      setArchiveStates((current) => ({
        ...current,
        [archiveId]: {
          ...existing,
          status: existing.status,
        },
      }));
    }

    const isExpanded = existing?.status === "ready" && existing.messages.length > 0;
    if (isExpanded) {
      setArchiveStates((current) => ({
        ...current,
        [archiveId]: {
          ...current[archiveId],
          messages: [],
          status: "idle",
          error: null,
        },
      }));
      return;
    }

    if (existing?.status === "loading") {
      return;
    }

    setArchiveStates((current) => ({
      ...current,
      [archiveId]: { error: null, messages: [], status: "loading" },
    }));

    try {
      const history = await api.getSessionArchive(currentSessionId, archiveId);
      setArchiveStates((current) => ({
        ...current,
        [archiveId]: {
          error: null,
          messages: history.map((message, index) => {
            const normalized = normalizeMessageContent(message);
            return {
              id: `archive-${archiveId}-${index}`,
              role: message.role as "user" | "assistant",
              content: normalized.content,
              request_id: message.request_id,
              tool_calls: normalized.toolCalls,
              retrievals: normalized.retrievals,
              blocks: normalized.blocks,
            };
          }),
          status: "ready",
        },
      }));
    } catch (error) {
      setArchiveStates((current) => ({
        ...current,
        [archiveId]: {
          error:
            error instanceof Error
              ? error.message
              : "Could not open the archived turns right now.",
          messages: [],
          status: "error",
        },
      }));
    }
  };

  return (
    <div className="flex flex-col gap-4 pb-[8rem] sm:gap-5 sm:pb-[8.75rem]">
      {continuitySummaries.length > 0 ? (
        <HistorySection
          eyebrow="Session Continuity"
          title="Archived Work"
          description="Older compressed BioAPEX work is kept as compact continuity summaries here, and any archived turn batch can be reopened on demand."
        >
          {continuitySummaries.map((summary, index) => {
            const archiveId = summary.archive_id;
            const archiveState = archiveId ? archiveStates[archiveId] : undefined;
            const archiveExpanded =
              archiveState?.status === "ready" && archiveState.messages.length > 0;

            return (
              <div
                key={`${summary.archive_id ?? "summary"}-${index}`}
                className="rounded-[18px] border border-[rgba(211,219,210,0.9)] bg-[rgba(248,250,246,0.92)] p-4"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <HistoryBadge icon={<Archive size={11} />}>
                        {summary.source_format === "legacy"
                          ? "Legacy summary"
                          : "Archived summary"}
                      </HistoryBadge>
                      <HistoryBadge icon={<Package size={11} />}>
                        {pluralize(summary.archived_message_count, "message")}
                      </HistoryBadge>
                    </div>
                    <p className="mt-3 text-sm font-medium leading-6 text-slate-800">
                      {continuityLead(summary)}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-slate-500">
                      {continuityDetail(summary)}
                    </p>
                  </div>

                  {archiveId ? (
                    <button
                      type="button"
                      onClick={() => void toggleArchiveSummary(summary)}
                      className="inline-flex items-center gap-2 self-start rounded-full border border-[var(--shell-border)] bg-white/95 px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800"
                    >
                      {archiveExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      {archiveExpanded ? "Hide archived turns" : "Open archived turns"}
                    </button>
                  ) : null}
                </div>

                {archiveState?.status === "loading" ? (
                  <p className="mt-3 text-[13px] leading-6 text-slate-500">
                    Loading archived turns…
                  </p>
                ) : null}

                {archiveState?.status === "error" ? (
                  <p className="mt-3 text-[13px] leading-6 text-rose-600">
                    {archiveState.error ?? "Could not load archived turns."}
                  </p>
                ) : null}

                {archiveExpanded ? (
                  <div className="mt-4 space-y-4 border-t border-[rgba(211,219,210,0.78)] pt-4">
                    {archiveState.messages.map((message) => (
                      <ChatMessage key={message.id} message={message} />
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </HistorySection>
      ) : null}

      {olderTurns.length > 0 ? (
        <HistorySection
          eyebrow="History Density"
          title="Earlier Turns"
          description="Older visible turns are compacted into summary rows so the latest scientific work stays foregrounded while full turn detail remains one click away."
        >
          {olderTurns.map((turn) => {
            const expanded = expandedTurnIds[turn.id] === true;

            return (
              <div
                key={turn.id}
                className="rounded-[18px] border border-[rgba(211,219,210,0.9)] bg-[rgba(248,250,246,0.92)] p-4"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {turn.toolCount > 0 ? (
                        <HistoryBadge icon={<Wrench size={11} />}>
                          {pluralize(turn.toolCount, "tool")}
                        </HistoryBadge>
                      ) : null}
                      {turn.retrievalCount > 0 ? (
                        <HistoryBadge icon={<Search size={11} />}>
                          {pluralize(turn.retrievalCount, "source")}
                        </HistoryBadge>
                      ) : null}
                      {turn.artifactCount > 0 ? (
                        <HistoryBadge icon={<Package size={11} />}>
                          {pluralize(turn.artifactCount, "artifact")}
                        </HistoryBadge>
                      ) : null}
                    </div>
                    <p className="mt-3 text-sm font-medium leading-6 text-slate-800">
                      {turn.requestLabel}
                    </p>
                    <p className="mt-1 text-sm leading-6 text-slate-500">{turn.detail}</p>
                  </div>

                  <button
                    type="button"
                    onClick={() => toggleOlderTurn(turn.id)}
                    className="inline-flex items-center gap-2 self-start rounded-full border border-[var(--shell-border)] bg-white/95 px-3 py-1.5 text-[11px] font-medium text-slate-600 transition-colors hover:bg-[var(--panel-soft)] hover:text-slate-800"
                    aria-label={
                      expanded
                        ? `Hide older turn ${turn.requestLabel}`
                        : `Show older turn ${turn.requestLabel}`
                    }
                  >
                    {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    {expanded ? "Hide turn" : "Show turn"}
                  </button>
                </div>

                {expanded ? (
                  <div className="mt-4 space-y-4 border-t border-[rgba(211,219,210,0.78)] pt-4">
                    {turn.messages.map((message) => (
                      <ChatMessage key={message.id} message={message} />
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </HistorySection>
      ) : null}

      {recentMessages.map((message) => (
        <ChatMessage key={message.id} message={message} />
      ))}
    </div>
  );
}
