"use client";

import { AlertTriangle, Check, Clock3 } from "lucide-react";
import {
  getEvidenceRetrievalPayload,
  getEvidenceReviewPayload,
  type EvidenceArtifactMetadata,
} from "@/lib/evidence";
import {
  getMessageRetrievals,
  getMessageToolCalls,
} from "@/lib/message-blocks";
import { getLatestRequestMessages } from "@/lib/session-status";
import type {
  ConfidenceLevel,
  Message,
  SourcesInspectorCitation,
  SourcesInspectorCitationTone,
  SourcesInspectorChecklistItem,
  SourcesInspectorSummary,
  ToolResultEnvelope,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  compactText,
  humanizeLabel,
  pluralize,
  uniqueStrings,
} from "./shared-utils";
import type {
  RetrievedSourceSummary,
  SourceInspectorItem,
  SourceInspectorTone,
} from "./types";

export type { EvidenceArtifactMetadata } from "@/lib/evidence";

function getConfidenceTone(
  confidence?: ConfidenceLevel | null
): SourceInspectorTone {
  if (confidence === "high") {
    return "supported";
  }

  if (confidence === "medium") {
    return "mixed";
  }

  if (confidence === "low") {
    return "insufficient";
  }

  return "neutral";
}

function getReviewTone(result: {
  reviewStatus?: string | null;
  confidence?: ConfidenceLevel | null;
  requiresReview?: boolean;
}): SourceInspectorTone {
  if (result.requiresReview) {
    return "warning";
  }

  if (result.reviewStatus === "supported") {
    return "supported";
  }

  if (result.reviewStatus === "mixed") {
    return "mixed";
  }

  if (result.reviewStatus === "insufficient_evidence") {
    return "insufficient";
  }

  return getConfidenceTone(result.confidence);
}

function getToolArtifactRef(
  result: ToolResultEnvelope | undefined,
  artifactType: string
) {
  return (
    result?.artifact_refs.find((ref) => ref.artifact_type === artifactType) ?? null
  );
}

function extractSourceIdentifier(source: string): string | null {
  const prefixed = source.match(/\b([a-z]+:[A-Za-z0-9._/-]+)\b/i);
  if (prefixed?.[1]) {
    return prefixed[1];
  }

  const pmid = source.match(/\bPMID[:\s#-]*([0-9]{4,})\b/i);
  if (pmid?.[1]) {
    return `pmid:${pmid[1]}`;
  }

  const accession = source.match(/\b(?:GSE|GSM|SRP|SRA|PRJNA|PRJEB)\d+\b/i);
  if (accession?.[0]) {
    return accession[0];
  }

  const doi = source.match(/\b10\.\d{4,9}\/[^\s)]+/i);
  if (doi?.[0]) {
    return `doi:${doi[0].replace(/[.,;:]+$/, "")}`;
  }

  return null;
}

function getSourceScopeMessages(messages: Message[]) {
  const latestMessages = getLatestRequestMessages(messages);
  return latestMessages.length > 0 ? latestMessages : messages;
}

export function mergeSourceItemWithMetadata(
  item: SourceInspectorItem,
  metadata?: EvidenceArtifactMetadata | null
): SourceInspectorItem {
  if (!metadata) {
    return item;
  }

  const nextItem = { ...item };

  if (metadata.artifactType) {
    nextItem.artifactType = metadata.artifactType;
  }

  if (metadata.title) {
    nextItem.title = metadata.title;
  }

  if (metadata.identifier) {
    nextItem.identifier = metadata.identifier;
  }

  if (metadata.studyType) {
    nextItem.metadata = uniqueStrings([
      humanizeLabel(metadata.studyType),
      ...nextItem.metadata,
    ]);
  }

  if (
    metadata.confidence &&
    (nextItem.stateLabel === "Included" ||
      nextItem.stateLabel === "Retrieved" ||
      nextItem.stateLabel === null)
  ) {
    nextItem.stateLabel = humanizeLabel(metadata.confidence);
  }

  if (metadata.confidence && nextItem.tone === "neutral") {
    nextItem.tone = getConfidenceTone(metadata.confidence);
  }

  if (
    nextItem.sourceType === "Reviewed evidence" ||
    nextItem.sourceType === "Evidence artifact"
  ) {
    nextItem.sourceType =
      metadata.studyType != null ? "Evidence source" : "Evidence card";
  }

  return nextItem;
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(99, Math.round(value)));
}

function getSupportPercentFromTone(tone: SourceInspectorTone): number | null {
  if (tone === "supported") {
    return 94;
  }

  if (tone === "mixed") {
    return 81;
  }

  if (tone === "insufficient") {
    return 58;
  }

  if (tone === "warning") {
    return 64;
  }

  if (tone === "retrieved") {
    return 91;
  }

  return null;
}

function getSupportPercentFromRetrievalScore(score: number): number | null {
  if (!Number.isFinite(score)) {
    return null;
  }

  if (score >= 0 && score <= 1) {
    return clampPercent(score * 100);
  }

  return clampPercent(score);
}

export function buildSourcesInspectorSummary(args: {
  scopedMessages: Message[];
  reviewedItems: SourceInspectorItem[];
  retrievedItems: RetrievedSourceSummary[];
}): SourcesInspectorSummary {
  const citations: SourcesInspectorCitation[] = [];
  const seenCitationKeys = new Set<string>();

  args.reviewedItems.forEach((item) => {
    if (item.kind !== "evidence") {
      return;
    }

    const supportPercent = getSupportPercentFromTone(item.tone);
    if (supportPercent === null) {
      return;
    }

    const citation: SourcesInspectorCitation = {
      id: item.id,
      title: item.title,
      identifier: item.identifier,
      source_type: item.sourceType,
      support_percent: supportPercent,
      tone: item.tone,
      detail: item.detail,
      path: item.path,
      last_seen_order: item.lastSeenOrder,
    };
    const citationKey =
      citation.identifier?.toLowerCase() ??
      citation.path ??
      citation.title.toLowerCase();
    if (seenCitationKeys.has(citationKey)) {
      return;
    }
    seenCitationKeys.add(citationKey);
    citations.push(citation);
  });

  args.retrievedItems.forEach((item) => {
    const supportPercent = getSupportPercentFromRetrievalScore(item.score);
    if (supportPercent === null) {
      return;
    }

    const citation: SourcesInspectorCitation = {
      id: item.source,
      title: item.source,
      identifier: item.identifier,
      source_type: "Retrieved context",
      support_percent: supportPercent,
      tone: "retrieved",
      detail: `${pluralize(item.count, "hit")} attached to the latest turn.`,
      path: null,
      last_seen_order: item.lastSeenOrder,
    };
    const citationKey =
      citation.identifier?.toLowerCase() ?? citation.title.toLowerCase();
    if (seenCitationKeys.has(citationKey)) {
      return;
    }
    seenCitationKeys.add(citationKey);
    citations.push(citation);
  });

  citations.sort((left, right) => right.last_seen_order - left.last_seen_order);

  const provenanceBackedCount = citations.filter((citation) => citation.path).length;
  const provenanceState: SourcesInspectorChecklistItem["state"] =
    citations.length === 0
      ? "pending"
      : provenanceBackedCount === citations.length
        ? "complete"
        : "warning";
  const reviewedEvidenceCount = args.reviewedItems.filter(
    (item) => item.kind === "evidence"
  ).length;
  const evidenceState: SourcesInspectorChecklistItem["state"] =
    reviewedEvidenceCount > 0
      ? "complete"
      : args.retrievedItems.length > 0
        ? "warning"
        : "pending";
  const scopeState: SourcesInspectorChecklistItem["state"] =
    args.scopedMessages.length > 0 ? "complete" : "pending";
  const checklistState: SourcesInspectorChecklistItem["state"] =
    citations.length === 0
      ? args.scopedMessages.length > 0
        ? "pending"
        : "pending"
      : provenanceState === "complete" && evidenceState === "complete"
        ? "complete"
        : "warning";
  const checklistLabel =
    checklistState === "complete"
      ? "Grounded"
      : checklistState === "warning"
        ? "Attention"
        : "Pending";
  const checklistDetail =
    args.scopedMessages.length === 0
      ? "Send a message to populate source evidence for this session."
      : citations.length === 0
        ? "No reviewed evidence or retrieved context is linked to the current source scope yet."
        : provenanceBackedCount === citations.length
          ? "Visible citations are backed by inspectable files or artifacts."
          : "Some visible citations are not yet backed by inspectable files or artifacts.";

  return {
    scoped_message_count: args.scopedMessages.length,
    citations: citations.slice(0, 8),
    checklist: {
      summary_label: checklistLabel,
      detail: checklistDetail,
      state: checklistState,
      items: [
        {
          id: "provenance-verified",
          label: "Provenance verified",
          state: provenanceState,
          detail:
            citations.length === 0
              ? "Waiting for source-backed evidence."
              : provenanceBackedCount === citations.length
                ? "Each citation is backed by an inspectable artifact in the current scope."
                : "Some visible citations are not yet backed by inspectable source artifacts.",
        },
        {
          id: "evidence-surfaced",
          label: "Evidence surfaced",
          state: evidenceState,
          detail:
            reviewedEvidenceCount > 0
              ? `${pluralize(reviewedEvidenceCount, "reviewed source")} is linked to this scope.`
              : args.retrievedItems.length > 0
                ? "Retrieved context is present, but reviewed evidence has not been materialized yet."
                : "No reviewed evidence or retrieved context is attached yet.",
        },
        {
          id: "scope-captured",
          label: "Turn scope captured",
          state: scopeState,
          detail:
            args.scopedMessages.length > 0
              ? `${pluralize(args.scopedMessages.length, "message")} is grouped into the current source scope.`
              : "No scoped messages are available yet.",
        },
      ],
    },
  };
}

export function collectSourceInspectorData(messages: Message[]) {
  const scopedMessages = getSourceScopeMessages(messages);
  const reviewedItems = new Map<string, SourceInspectorItem>();
  const retrievedSources = new Map<string, RetrievedSourceSummary>();
  let order = 0;

  scopedMessages.forEach((message, messageIndex) => {
    getMessageToolCalls(message).forEach((call, callIndex) => {
      const result = call.result;
      if (!result) {
        return;
      }

      if (
        call.tool === "evidence_retrieval" ||
        result.tool_name === "evidence_retrieval"
      ) {
        const payload = getEvidenceRetrievalPayload(result);
        payload?.cards.forEach((card, cardIndex) => {
          const key =
            card.artifact_path ||
            card.stable_identifier ||
            `card-${messageIndex}-${callIndex}-${cardIndex}`;
          const existing = reviewedItems.get(key);
          reviewedItems.set(key, {
            id: key,
            kind: "evidence",
            artifactType: "evidence_card",
            title: existing?.title ?? card.title,
            sourceType:
              existing?.sourceType ??
              (card.study_type ? "Evidence source" : "Evidence card"),
            identifier: existing?.identifier ?? card.stable_identifier,
            stateLabel: card.grounding_requires_clarification
              ? "Clarify grounding"
              : existing?.stateLabel ?? "Retrieved",
            detail:
              existing?.detail ??
              (card.grounding_requires_clarification
                ? "Entity grounding for this source needs clarification before stronger synthesis."
                : "Retrieved for the latest evidence turn."),
            metadata: uniqueStrings([
              ...(existing?.metadata ?? []),
              humanizeLabel(card.study_type),
              pluralize(card.claim_count, "claim"),
              card.limitation_count > 0
                ? pluralize(card.limitation_count, "limitation")
                : null,
            ]),
            tone: card.grounding_requires_clarification
              ? "warning"
              : existing?.tone ?? "retrieved",
            path: existing?.path ?? card.artifact_path,
            lastSeenOrder: order,
          });
          order += 1;
        });
      }

      if (call.tool === "evidence_review" || result.tool_name === "evidence_review") {
        const payload = getEvidenceReviewPayload(result);
        if (!payload) {
          return;
        }

        const reviewArtifact = getToolArtifactRef(result, "evidence_review");
        const reviewKey =
          payload.artifact_path ??
          reviewArtifact?.path ??
          `review-${messageIndex}-${callIndex}`;

        reviewedItems.set(reviewKey, {
          id: reviewKey,
          kind: "review",
          artifactType: "evidence_review",
          title:
            payload.question ??
            compactText(payload.synthesized_conclusions[0]?.statement, 120) ??
            "Evidence review",
          sourceType: "Evidence review",
          identifier: reviewArtifact?.identifier ?? null,
          stateLabel: payload.review_status
            ? humanizeLabel(payload.review_status)
            : null,
          detail:
            compactText(payload.synthesized_conclusions[0]?.statement, 180) ??
            compactText(result.summary, 180),
          metadata: uniqueStrings([
            payload.confidence ? `${humanizeLabel(payload.confidence)} confidence` : null,
            payload.evidence_included.length > 0
              ? pluralize(payload.evidence_included.length, "included source")
              : null,
            payload.evidence_excluded.length > 0
              ? pluralize(payload.evidence_excluded.length, "excluded source")
              : null,
            payload.synthesized_conclusions.length > 0
              ? pluralize(payload.synthesized_conclusions.length, "conclusion")
              : null,
            payload.unresolved_conflicts.length > 0
              ? pluralize(payload.unresolved_conflicts.length, "conflict")
              : null,
          ]),
          tone: getReviewTone({
            reviewStatus: payload.review_status,
            confidence: payload.confidence,
            requiresReview: payload.requires_review,
          }),
          path: payload.artifact_path ?? reviewArtifact?.path ?? null,
          lastSeenOrder: order,
        });
        order += 1;

        const sourceFactsByPath = new Map<string, (typeof payload.source_facts)[number]>();
        const sourceFactsByIdentifier = new Map<
          string,
          (typeof payload.source_facts)[number]
        >();

        payload.source_facts.forEach((fact) => {
          if (fact.evidence?.path) {
            sourceFactsByPath.set(fact.evidence.path, fact);
          }
          if (fact.stable_identifier) {
            sourceFactsByIdentifier.set(fact.stable_identifier, fact);
          }
        });

        payload.evidence_included.forEach((ref, refIndex) => {
          const key =
            ref.path || ref.id || `reviewed-evidence-${messageIndex}-${callIndex}-${refIndex}`;
          const existing = reviewedItems.get(key);
          const fact =
            sourceFactsByPath.get(ref.path) ??
            (existing?.identifier
              ? sourceFactsByIdentifier.get(existing.identifier)
              : undefined);

          reviewedItems.set(key, {
            id: key,
            kind: "evidence",
            artifactType: ref.artifact_type ?? null,
            title:
              existing?.title ??
              compactText(
                fact?.statement ?? fact?.stable_identifier ?? ref.id ?? ref.path,
                120
              ) ??
              "Reviewed evidence",
            sourceType:
              existing?.sourceType ??
              (fact ? "Reviewed evidence" : "Evidence artifact"),
            identifier:
              existing?.identifier ?? fact?.stable_identifier ?? ref.id ?? null,
            stateLabel:
              humanizeLabel(fact?.confidence) ??
              existing?.stateLabel ??
              "Included",
            detail:
              existing?.detail ??
              compactText(
                fact?.statement ?? "Included in the latest evidence review.",
                180
              ),
            metadata: uniqueStrings([
              ...(existing?.metadata ?? []),
              "Included in review",
              payload.review_status ? humanizeLabel(payload.review_status) : null,
              fact?.claim_id ? humanizeLabel(fact.claim_id) : null,
            ]),
            tone:
              fact?.confidence
                ? getConfidenceTone(fact.confidence)
                : getReviewTone({
                    reviewStatus: payload.review_status,
                    confidence: payload.confidence,
                    requiresReview: payload.requires_review,
                  }),
            path: existing?.path ?? ref.path,
            lastSeenOrder: order,
          });
          order += 1;
        });
      }
    });

    getMessageRetrievals(message).forEach((result) => {
      const existing = retrievedSources.get(result.source);
      if (existing) {
        existing.score = Math.max(existing.score, result.score);
        existing.count += 1;
        existing.lastSeenOrder = order;
      } else {
        retrievedSources.set(result.source, {
          source: result.source,
          identifier: extractSourceIdentifier(result.source),
          score: result.score,
          count: 1,
          lastSeenOrder: order,
        });
      }
      order += 1;
    });
  });

  return {
    scopedMessages,
    reviewedItems: Array.from(reviewedItems.values()).sort(
      (left, right) => right.lastSeenOrder - left.lastSeenOrder
    ),
    retrievedItems: Array.from(retrievedSources.values()).sort(
      (left, right) => right.lastSeenOrder - left.lastSeenOrder
    ),
  };
}

function getCitationPercentClass(tone: SourcesInspectorCitationTone) {
  if (tone === "supported") {
    return "text-emerald-700";
  }

  if (tone === "mixed") {
    return "text-amber-700";
  }

  if (tone === "insufficient") {
    return "text-rose-700";
  }

  if (tone === "warning") {
    return "text-orange-700";
  }

  if (tone === "retrieved") {
    return "text-slate-500";
  }

  return "text-slate-500";
}

export function getChecklistCardClass(
  state: SourcesInspectorChecklistItem["state"]
) {
  if (state === "blocked") {
    return "border-rose-200 bg-[linear-gradient(180deg,rgba(255,247,247,0.98),rgba(254,241,241,0.98))]";
  }

  if (state === "warning") {
    return "border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.98),rgba(254,243,199,0.7))]";
  }

  if (state === "complete") {
    return "border-[rgba(35,130,83,0.14)] bg-[linear-gradient(180deg,rgba(248,251,248,0.98),rgba(242,247,243,0.98))]";
  }

  return "border-[rgba(211,219,210,0.86)] bg-[linear-gradient(180deg,rgba(252,252,251,0.98),rgba(247,249,246,0.98))]";
}

export function getChecklistBadgeClass(
  state: SourcesInspectorChecklistItem["state"]
) {
  if (state === "blocked") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }

  if (state === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }

  if (state === "complete") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }

  return "border-[rgba(211,219,210,0.86)] bg-white/80 text-slate-500";
}

function getChecklistItemPresentation(
  state: SourcesInspectorChecklistItem["state"]
) {
  if (state === "blocked") {
    return {
      icon: AlertTriangle,
      iconClass: "bg-rose-50 text-rose-600",
    };
  }

  if (state === "warning") {
    return {
      icon: AlertTriangle,
      iconClass: "bg-amber-50 text-amber-600",
    };
  }

  if (state === "complete") {
    return {
      icon: Check,
      iconClass: "bg-emerald-50 text-emerald-600",
    };
  }

  return {
    icon: Clock3,
    iconClass: "bg-slate-100 text-slate-500",
  };
}

export function SourceCitationRow({
  citation,
  onInspect,
}: {
  citation: SourcesInspectorCitation;
  onInspect: (path: string) => void;
}) {
  const interactive = Boolean(citation.path);
  const body = (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium leading-5 text-slate-700">
          {citation.title}
        </p>
        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
          {citation.identifier ? (
            <span className="rounded-full border border-[rgba(35,130,83,0.12)] bg-[rgba(35,130,83,0.08)] px-1.5 py-0.5 font-mono text-[9px] font-semibold text-[var(--apex-accent-strong)]">
              {citation.identifier}
            </span>
          ) : null}
          {!citation.identifier ? (
            <span className="text-[9px] font-medium uppercase tracking-[0.12em] text-slate-400">
              {citation.source_type}
            </span>
          ) : null}
        </div>
      </div>
      <span
        className={cn(
          "shrink-0 pt-0.5 text-[13px] font-semibold",
          getCitationPercentClass(citation.tone)
        )}
      >
        {citation.support_percent !== null ? `${citation.support_percent}%` : "--"}
      </span>
    </div>
  );

  if (!interactive || !citation.path) {
    return (
      <div className="rounded-[14px] border border-transparent px-2 py-1.5">
        {body}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onInspect(citation.path!)}
      title={citation.path}
      className={cn(
        "w-full rounded-[14px] border border-transparent px-2 py-1.5 text-left transition-colors",
        "hover:border-[rgba(211,219,210,0.9)] hover:bg-white/75"
      )}
    >
      {body}
    </button>
  );
}

export function ChecklistRow({
  item,
}: {
  item: SourcesInspectorChecklistItem;
}) {
  const presentation = getChecklistItemPresentation(item.state);
  const Icon = presentation.icon;

  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
          presentation.iconClass
        )}
      >
        <Icon size={11} />
      </span>
      <span className="text-[12px] leading-5 text-slate-600">{item.label}</span>
    </div>
  );
}
