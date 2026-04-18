"use client";

import dynamic from "next/dynamic";
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertTriangle,
  BookOpen,
  Brain,
  Check,
  Clock3,
  Copy,
  Download,
  FileText,
  Hash,
  Plus,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import {
  FilePreviewSurface,
  useFilePreview,
  type FilePreviewTarget,
} from "@/components/preview/FilePreviewSurface";
import TurnDetailsPanel from "@/components/editor/TurnDetailsPanel";
import {
  getSessionTokens,
  openRawFileInNewTab,
  readFile,
  saveFile,
} from "@/lib/api";
import {
  getPreviewableFileLabel,
  inferPreviewableFileKind,
} from "@/lib/file-preview";
import { compactText, humanizeToken } from "@/lib/format";
import {
  getMessageRetrievals,
  getMessageToolCalls,
} from "@/lib/message-blocks";
import {
  getLatestRequestMessages,
} from "@/lib/session-status";
import {
  summarizeSessionUsage,
  type UsageSummaryOrigin,
} from "@/lib/token-usage";
import {
  getEvidenceRetrievalPayload,
  parseEvidenceArtifactMetadata,
  getEvidenceReviewPayload,
  type EvidenceArtifactMetadata,
} from "@/lib/evidence";
import { useApp } from "@/lib/store";
import { cn, formatRelativeTime } from "@/lib/utils";
import type {
  ConfidenceLevel,
  Message,
  SourcesInspectorCitation,
  SourcesInspectorCitationTone,
  SourcesInspectorChecklistItem,
  SourcesInspectorSummary,
  TokenStats,
  ToolResultEnvelope,
} from "@/lib/types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-slate-400">
      Loading editor…
    </div>
  ),
});

const MEMORY_PATH = "memory/MEMORY.md";
const INSPECTOR_TABS = [
  { id: "files", label: "Files", icon: FileText },
  { id: "sources", label: "Sources", icon: Search },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "usage", label: "Usage", icon: Hash },
  { id: "turns", label: "Turns", icon: Clock3 },
] as const;

type GeneratedArtifactItem = {
  path: string;
  label: string;
  artifactType: string | null;
  sourceTool: string | null;
  lastSeenOrder: number;
};

type GeneratedArtifactKind =
  | "table"
  | "plot"
  | "structured"
  | "report"
  | "archive"
  | "file";

type SourceInspectorItemKind = "review" | "evidence" | "retrieval";

type SourceInspectorTone = SourcesInspectorCitationTone;

type SourceInspectorItem = {
  id: string;
  kind: SourceInspectorItemKind;
  artifactType: string | null;
  title: string;
  sourceType: string;
  identifier: string | null;
  stateLabel: string | null;
  detail: string | null;
  metadata: string[];
  tone: SourceInspectorTone;
  path: string | null;
  lastSeenOrder: number;
};

type RetrievedSourceSummary = {
  source: string;
  identifier: string | null;
  score: number;
  count: number;
  lastSeenOrder: number;
};

type MemoryInspectorItemKind = "bullet" | "numbered" | "block";

type MemoryInspectorItem = {
  id: string;
  namespace: string;
  key: string;
  value: string;
  kind: MemoryInspectorItemKind;
  rawLines: string[];
};

type ParsedMemoryDocument = {
  title: string;
  items: MemoryInspectorItem[];
};

type MemoryItemDraft = {
  mode: "create" | "edit";
  targetId: string | null;
  namespace: string;
  key: string;
  value: string;
};

function humanizeLabel(value?: string | null): string | null {
  const humanized = humanizeToken(value);
  if (!humanized) {
    return null;
  }

  return humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  values.forEach((value) => {
    const trimmed = value?.trim();
    if (!trimmed || seen.has(trimmed)) {
      return;
    }

    seen.add(trimmed);
    result.push(trimmed);
  });

  return result;
}

function pluralize(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function buildExportMarkdown(title: string, messages: Message[]) {
  const lines: string[] = [
    `# ${title}`,
    "",
    `Exported: ${new Date().toISOString()}`,
    "",
  ];

  messages.forEach((message) => {
    lines.push(`## ${message.role === "user" ? "User" : "BioAPEX"}`);
    lines.push(message.content || "(empty response)");

    const retrievals = getMessageRetrievals(message);
    if (retrievals.length) {
      lines.push("");
      lines.push("Retrieved sources:");
      retrievals.forEach((result) => {
        lines.push(`- ${result.source} (score ${result.score.toFixed(3)})`);
      });
    }

    const toolCalls = getMessageToolCalls(message);
    if (toolCalls.length) {
      lines.push("");
      lines.push("Tool calls:");
      toolCalls.forEach((call) => {
        lines.push(`- ${call.tool}`);
      });
    }

    lines.push("");
  });

  return `${lines.join("\n").trim()}\n`;
}

function exportFilename(title: string): string {
  return (
    title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") ||
    "bioapex-session"
  );
}

function formatCompactTokenValue(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value >= 100_000_000 ? 0 : 1)}M`;
  }

  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  }

  return value.toString();
}

function normalizeMarkdownInline(value: string): string {
  return value
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[(.+?)\]\(.+?\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function deriveMemoryKeyAndValue(text: string): {
  key: string;
  value: string;
} {
  const normalized = normalizeMarkdownInline(text);

  if (!normalized) {
    return {
      key: "Memory note",
      value: "",
    };
  }

  const colonMatch = normalized.match(/^([^:]{1,48}):\s*(.+)$/);
  if (colonMatch) {
    return {
      key: colonMatch[1].trim(),
      value: colonMatch[2].trim(),
    };
  }

  if (normalized.length <= 56) {
    return {
      key: normalized,
      value: "",
    };
  }

  const sentence = normalized.split(/[.!?](?:\s|$)/)[0]?.trim();
  if (sentence && sentence.length <= 48) {
    return {
      key: sentence,
      value: normalized,
    };
  }

  return {
    key: compactText(normalized, 42) ?? "Memory note",
    value: normalized,
  };
}

function buildMemoryItemId(namespace: string, key: string, index: number): string {
  const normalizedNamespace = namespace
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const normalizedKey = key
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  return `${normalizedNamespace || "memory"}-${normalizedKey || "item"}-${index}`;
}

function extractMemoryItemText(rawLines: string[], kind: MemoryInspectorItemKind): string {
  if (rawLines.length === 0) {
    return "";
  }

  if (kind === "block") {
    return rawLines.map((line) => line.trim()).join(" ").trim();
  }

  const firstLine = rawLines[0]?.trim() ?? "";
  const firstLineWithoutMarker =
    kind === "numbered"
      ? firstLine.replace(/^\d+\.\s+/, "")
      : firstLine.replace(/^-\s+/, "");
  const continuation = rawLines
    .slice(1)
    .map((line) => line.trim())
    .filter(Boolean);

  return [firstLineWithoutMarker, ...continuation].join(" ").trim();
}

function renderMemoryItemLines(
  kind: MemoryInspectorItemKind,
  key: string,
  value: string
): string[] {
  const normalizedKey = key.trim() || "Memory note";
  const normalizedValue = value.trim();
  const baseText =
    normalizedValue && normalizedValue.toLowerCase() !== normalizedKey.toLowerCase()
      ? `**${normalizedKey}**: ${normalizedValue}`
      : normalizedValue || normalizedKey;
  const textLines = baseText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (textLines.length === 0) {
    return kind === "block" ? ["Memory note"] : ["- Memory note"];
  }

  if (kind === "block") {
    return textLines;
  }

  const marker = kind === "numbered" ? "1." : "-";
  return textLines.map((line, index) =>
    index === 0 ? `${marker} ${line}` : `  ${line}`
  );
}

function parseMemoryDocument(content: string): ParsedMemoryDocument {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const items: MemoryInspectorItem[] = [];
  let title = "Long-term Memory";
  let currentNamespace = "General";
  let itemIndex = 0;

  const pushItem = (rawLines: string[], kind: MemoryInspectorItemKind) => {
    const normalized = extractMemoryItemText(rawLines, kind);
    if (!normalized) {
      return;
    }

    const { key, value } = deriveMemoryKeyAndValue(normalized);
    items.push({
      id: buildMemoryItemId(currentNamespace, key, itemIndex),
      namespace: currentNamespace,
      key,
      value,
      kind,
      rawLines,
    });
    itemIndex += 1;
  };

  let lineIndex = 0;

  while (lineIndex < lines.length) {
    const line = lines[lineIndex];
    const trimmed = line.trim();

    if (!trimmed) {
      lineIndex += 1;
      continue;
    }

    if (trimmed.startsWith("# ")) {
      title = trimmed.replace(/^#\s+/, "").trim() || title;
      lineIndex += 1;
      continue;
    }

    if (trimmed.startsWith("## ")) {
      currentNamespace = trimmed.replace(/^##\s+/, "").trim() || "General";
      lineIndex += 1;
      continue;
    }

    if (trimmed.match(/^-\s+/) || trimmed.match(/^\d+\.\s+/)) {
      const kind: MemoryInspectorItemKind = trimmed.match(/^\d+\.\s+/)
        ? "numbered"
        : "bullet";
      const rawLines = [line];
      lineIndex += 1;

      while (lineIndex < lines.length) {
        const nextLine = lines[lineIndex];
        const nextTrimmed = nextLine.trim();
        if (
          !nextTrimmed ||
          nextTrimmed.startsWith("# ") ||
          nextTrimmed.startsWith("## ") ||
          nextTrimmed.match(/^-\s+/) ||
          nextTrimmed.match(/^\d+\.\s+/)
        ) {
          break;
        }
        if (nextLine.match(/^\s+/)) {
          rawLines.push(nextLine);
          lineIndex += 1;
          continue;
        }
        break;
      }

      pushItem(rawLines, kind);
      continue;
    }

    const rawLines = [line];
    lineIndex += 1;
    while (lineIndex < lines.length) {
      const nextLine = lines[lineIndex];
      const nextTrimmed = nextLine.trim();
      if (
        !nextTrimmed ||
        nextTrimmed.startsWith("# ") ||
        nextTrimmed.startsWith("## ") ||
        nextTrimmed.match(/^-\s+/) ||
        nextTrimmed.match(/^\d+\.\s+/)
      ) {
        break;
      }
      rawLines.push(nextLine);
      lineIndex += 1;
    }

    pushItem(rawLines, "block");
  }

  return {
    title,
    items,
  };
}

function serializeMemoryDocument(document: ParsedMemoryDocument): string {
  const sections = new Map<string, MemoryInspectorItem[]>();

  document.items.forEach((item) => {
    const namespace = item.namespace.trim() || "General";
    const existing = sections.get(namespace);
    if (existing) {
      existing.push(item);
    } else {
      sections.set(namespace, [item]);
    }
  });

  const lines = [`# ${document.title || "Long-term Memory"}`, ""];

  if (sections.size === 0) {
    lines.push("## General", "");
  }

  sections.forEach((sectionItems, namespace) => {
    lines.push(`## ${namespace}`);

    sectionItems.forEach((item) => {
      const key = normalizeMarkdownInline(item.key);
      const value = normalizeMarkdownInline(item.value);
      const rawLines =
        item.rawLines.length > 0
          ? item.rawLines
          : renderMemoryItemLines(item.kind, key, value);

      rawLines.forEach((line) => lines.push(line));
    });

    lines.push("");
  });

  return `${lines.join("\n").trimEnd()}\n`;
}

function upsertMemoryDocumentItem(
  document: ParsedMemoryDocument,
  draft: MemoryItemDraft
): ParsedMemoryDocument {
  const namespace = draft.namespace.trim() || "General";
  const key = draft.key.trim() || "Memory note";
  const value = draft.value.trim();
  const sourceItem =
    draft.mode === "edit" && draft.targetId
      ? document.items.find((item) => item.id === draft.targetId) ?? null
      : null;
  const nextKind = sourceItem?.kind ?? "bullet";
  const shouldPreserveRawLines =
    sourceItem !== null &&
    sourceItem.namespace === namespace &&
    sourceItem.key === key &&
    sourceItem.value === value;
  const nextItem: MemoryInspectorItem = {
    id:
      draft.mode === "edit" && draft.targetId
        ? draft.targetId
        : buildMemoryItemId(namespace, key, document.items.length),
    namespace,
    key,
    value,
    kind: nextKind,
    rawLines: shouldPreserveRawLines
      ? [...(sourceItem?.rawLines ?? [])]
      : renderMemoryItemLines(nextKind, key, value),
  };

  if (draft.mode === "edit" && draft.targetId) {
    return {
      ...document,
      items: document.items.map((item) =>
        item.id === draft.targetId ? nextItem : item
      ),
    };
  }

  return {
    ...document,
    items: [...document.items, nextItem],
  };
}

function duplicateMemoryDocumentItem(
  document: ParsedMemoryDocument,
  itemId: string
): ParsedMemoryDocument {
  const index = document.items.findIndex((item) => item.id === itemId);
  if (index === -1) {
    return document;
  }

  const source = document.items[index];
  const duplicate: MemoryInspectorItem = {
    ...source,
    id: buildMemoryItemId(source.namespace, `${source.key} copy`, document.items.length),
    rawLines: [...source.rawLines],
  };
  const nextItems = [...document.items];
  nextItems.splice(index + 1, 0, duplicate);

  return {
    ...document,
    items: nextItems,
  };
}

function removeMemoryDocumentItem(
  document: ParsedMemoryDocument,
  itemId: string
): ParsedMemoryDocument {
  return {
    ...document,
    items: document.items.filter((item) => item.id !== itemId),
  };
}

function shouldShowGeneratedArtifact(item: {
  path: string;
  artifactType: string | null;
}): boolean {
  if (!item.path) {
    return false;
  }

  if (item.artifactType?.endsWith("_run")) {
    return false;
  }

  return true;
}

function collectArtifacts(messages: Message[]) {
  const items = new Map<string, GeneratedArtifactItem>();
  let order = 0;

  const upsertArtifact = ({
    path,
    artifactType,
    sourceTool,
  }: {
    path: string;
    artifactType?: string | null;
    sourceTool?: string | null;
  }) => {
    const existing = items.get(path);
    const nextItem: GeneratedArtifactItem = {
      path,
      label: path.split("/").pop() ?? path,
      artifactType: artifactType ?? existing?.artifactType ?? null,
      sourceTool: sourceTool ?? existing?.sourceTool ?? null,
      lastSeenOrder: order,
    };
    order += 1;

    if (!shouldShowGeneratedArtifact(nextItem)) {
      return;
    }

    items.set(path, nextItem);
  };

  messages.forEach((message) => {
    getMessageToolCalls(message).forEach((call) => {
      call.result?.artifact_refs?.forEach((artifact) => {
        if (!artifact.path) {
          return;
        }

        upsertArtifact({
          path: artifact.path,
          artifactType: artifact.artifact_type ?? null,
          sourceTool: call.tool,
        });
      });
    });
  });

  return Array.from(items.values())
    .sort((left, right) => right.lastSeenOrder - left.lastSeenOrder)
    .slice(0, 12);
}

function inferGeneratedArtifactKind(item: GeneratedArtifactItem): GeneratedArtifactKind {
  return inferPreviewableFileKind({
    path: item.path,
    artifactType: item.artifactType,
    label: item.label,
  });
}

function getGeneratedArtifactCue(item: GeneratedArtifactItem) {
  const kind = inferGeneratedArtifactKind(item);
  return {
    kind,
    label: getPreviewableFileLabel({
      path: item.path,
      artifactType: item.artifactType,
      label: item.label,
    }),
  };
}

function getGeneratedArtifactTone(kind: GeneratedArtifactKind) {
  if (kind === "table") {
    return {
      badge: "border-amber-200 bg-amber-50 text-amber-700",
      icon: "bg-amber-50 text-amber-700",
      active:
        "border-amber-200 bg-[linear-gradient(180deg,rgba(255,251,235,0.95),rgba(254,243,199,0.72))]",
      idle: "border-[rgba(245,158,11,0.14)] bg-[rgba(255,251,235,0.68)]",
    };
  }

  if (kind === "plot") {
    return {
      badge: "border-rose-200 bg-rose-50 text-rose-700",
      icon: "bg-rose-50 text-rose-700",
      active:
        "border-rose-200 bg-[linear-gradient(180deg,rgba(255,241,242,0.96),rgba(255,228,230,0.74))]",
      idle: "border-[rgba(244,63,94,0.12)] bg-[rgba(255,244,246,0.7)]",
    };
  }

  if (kind === "report") {
    return {
      badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: "bg-emerald-50 text-emerald-700",
      active:
        "border-emerald-200 bg-[linear-gradient(180deg,rgba(236,253,245,0.96),rgba(209,250,229,0.72))]",
      idle: "border-[rgba(16,185,129,0.12)] bg-[rgba(240,253,244,0.72)]",
    };
  }

  if (kind === "structured") {
    return {
      badge: "border-sky-200 bg-sky-50 text-sky-700",
      icon: "bg-sky-50 text-sky-700",
      active:
        "border-sky-200 bg-[linear-gradient(180deg,rgba(240,249,255,0.96),rgba(224,242,254,0.74))]",
      idle: "border-[rgba(14,165,233,0.12)] bg-[rgba(240,249,255,0.7)]",
    };
  }

  if (kind === "archive") {
    return {
      badge: "border-slate-200 bg-slate-100 text-slate-600",
      icon: "bg-slate-100 text-slate-600",
      active:
        "border-slate-300 bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(241,245,249,0.82))]",
      idle: "border-[rgba(148,163,184,0.14)] bg-[rgba(248,250,252,0.78)]",
    };
  }

  return {
    badge: "border-stone-200 bg-stone-50 text-stone-700",
    icon: "bg-stone-50 text-stone-700",
    active:
      "border-stone-200 bg-[linear-gradient(180deg,rgba(250,250,249,0.96),rgba(245,245,244,0.82))]",
    idle: "border-[rgba(168,162,158,0.14)] bg-[rgba(250,250,249,0.76)]",
  };
}

function getGeneratedArtifactDetail(item: GeneratedArtifactItem): string {
  const values = [humanizeToken(item.artifactType), humanizeLabel(item.sourceTool)].filter(
    (value): value is string => Boolean(value)
  );

  const uniqueValues = values.filter(
    (value, index) => values.indexOf(value) === index
  );

  return uniqueValues[0] ?? "Generated artifact";
}

function getGeneratedArtifactScopeLabel(item: GeneratedArtifactItem): string | null {
  return humanizeLabel(item.sourceTool);
}

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

function mergeSourceItemWithMetadata(
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

function getSupportPercentFromTone(
  tone: SourceInspectorTone
): number | null {
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

function buildSourcesInspectorSummary(args: {
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

function collectSourceInspectorData(messages: Message[]) {
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
            card.artifact_path || card.stable_identifier || `card-${messageIndex}-${callIndex}-${cardIndex}`;
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

function shortenPath(path: string, maxSegments = 2) {
  const normalized = path.replaceAll("\\", "/");
  const segments = normalized.split("/").filter(Boolean);

  if (segments.length <= maxSegments) {
    return normalized;
  }

  return `.../${segments.slice(-maxSegments).join("/")}`;
}

function TabButton({
  active,
  icon: Icon,
  label,
  ariaLabel,
  onClick,
}: {
  active: boolean;
  icon: typeof FileText;
  label: string;
  ariaLabel: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={cn(
        "flex min-h-[44px] flex-col items-center justify-center gap-0.5 rounded-[10px] border px-1 py-1 text-center transition-colors",
        active
          ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
          : "border-transparent text-slate-500 hover:border-[var(--shell-border)] hover:bg-white/80 hover:text-slate-700"
      )}
    >
      <Icon size={12} strokeWidth={1.8} />
      <span className="text-[9px] font-medium leading-tight">
        {label}
      </span>
    </button>
  );
}

function InspectorCard({
  title,
  meta,
  controls,
  children,
}: {
  title: string;
  meta?: string;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[14px] border border-[rgba(211,219,210,0.86)] bg-[rgba(255,255,255,0.88)] px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)] backdrop-blur-sm">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
            {title}
          </h3>
          {meta ? (
            <p className="mt-1 truncate text-[10px] leading-4 text-slate-500">
              {meta}
            </p>
          ) : null}
        </div>
        {controls ? (
          <div className="flex shrink-0 items-center gap-1">{controls}</div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function ActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
          : "border-[var(--shell-border)] bg-white/85 text-slate-500 hover:bg-[var(--panel-soft)] hover:text-slate-700"
      )}
    >
      {children}
    </button>
  );
}

function MemoryCardActionButton({
  onClick,
  title,
  tone = "default",
  children,
}: {
  onClick: () => void;
  title: string;
  tone?: "default" | "danger";
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-[10px] transition-colors",
        tone === "danger"
          ? "text-slate-500 hover:bg-rose-50 hover:text-rose-600"
          : "text-slate-600 hover:bg-[rgba(35,130,83,0.08)] hover:text-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

function PrimaryActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-semibold transition-colors",
        disabled
          ? "cursor-not-allowed bg-slate-200 text-slate-400"
          : "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

function WideActionButton({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex w-full items-center justify-center gap-1.5 rounded-full border px-3 py-2 text-[11px] font-semibold transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
          : "border-[rgba(211,219,210,0.92)] bg-white text-slate-700 shadow-[0_1px_2px_rgba(32,43,35,0.03)] hover:border-[rgba(35,130,83,0.2)] hover:bg-[var(--panel-soft)] hover:text-[var(--apex-accent-strong)]"
      )}
    >
      {children}
    </button>
  );
}

function MetaBadge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
        tone === "accent" &&
          "border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]",
        tone === "success" &&
          "border-emerald-200 bg-emerald-50 text-emerald-700",
        tone === "warning" &&
          "border-amber-200 bg-amber-50 text-amber-700",
        tone === "neutral" &&
          "border-[rgba(211,219,210,0.8)] bg-[rgba(251,252,248,0.92)] text-slate-500"
      )}
    >
      {children}
    </span>
  );
}

function MiniStat({
  label,
  value,
  accent = false,
  detail,
}: {
  label: string;
  value: string;
  accent?: boolean;
  detail?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-[10px] border px-2.5 py-2",
        accent
          ? "border-[rgba(35,130,83,0.14)] bg-[rgba(35,130,83,0.08)]"
          : "border-[rgba(211,219,210,0.72)] bg-[rgba(251,252,248,0.9)]"
      )}
    >
      <p
        className={cn(
          "text-[9px] font-semibold uppercase tracking-[0.16em]",
          accent ? "text-[var(--apex-accent-strong)]" : "text-slate-400"
        )}
      >
        {label}
      </p>
      <p
        className={cn(
          "mt-0.5 text-xs font-semibold",
          accent ? "text-[var(--apex-accent-strong)]" : "text-slate-700"
        )}
      >
        {value}
      </p>
      {detail ? (
        <p className="mt-1 text-[10px] leading-4 text-slate-500">{detail}</p>
      ) : null}
    </div>
  );
}

function UsageMetricRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-[12px] leading-5">
      <span className="text-slate-400">{label}</span>
      <span className="font-semibold text-slate-700">{value}</span>
    </div>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-3 py-3 text-[11px] leading-5 text-slate-500">
      {children}
    </div>
  );
}

function GeneratedFileRow({
  item,
  active,
  onClick,
}: {
  item: GeneratedArtifactItem;
  active: boolean;
  onClick: () => void;
}) {
  const cue = getGeneratedArtifactCue(item);
  const tone = getGeneratedArtifactTone(cue.kind);
  const detail = getGeneratedArtifactDetail(item);
  const scopeLabel = getGeneratedArtifactScopeLabel(item);

  return (
    <button
      type="button"
      onClick={onClick}
      title={item.path}
      className={cn(
        "flex w-full items-start gap-2 rounded-[12px] border px-2.5 py-2 text-left transition-colors",
        active
          ? tone.active
          : `${tone.idle} hover:border-[rgba(211,219,210,0.9)] hover:bg-white`
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[9px]",
          tone.icon
        )}
      >
        <FileText size={12} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-start justify-between gap-2">
          <span className="min-w-0 truncate text-[12px] font-semibold text-slate-700">
            {item.label}
          </span>
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
              tone.badge
            )}
          >
            {cue.label}
          </span>
        </span>
        <span className="mt-1 flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[10px] font-medium text-slate-500">
            {detail}
          </span>
          {scopeLabel ? (
            <span className="shrink-0 rounded-full bg-white/80 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.08em] text-slate-400">
              {scopeLabel}
            </span>
          ) : null}
        </span>
        <span className="mt-1 block truncate font-mono text-[9px] text-slate-400">
          {shortenPath(item.path, 4)}
        </span>
      </span>
    </button>
  );
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

function getChecklistCardClass(
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

function getChecklistBadgeClass(
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

function SourceCitationRow({
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

function ChecklistRow({
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

function PreviewPane({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <pre
      className={cn(
        "max-h-[360px] overflow-y-auto whitespace-pre-wrap break-words rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)] px-2.5 py-2.5 text-[11px] leading-5 text-slate-600",
        className
      )}
    >
      {content}
    </pre>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-2.5 py-5 text-center text-[11px] text-slate-400">
      {label}
    </div>
  );
}

export default function InspectorPanel() {
  const {
    accessByScope,
    hasInspectionAccess,
    currentSessionId,
    sessions,
    messages,
    isStreaming,
    inspectorTab,
    inspectorPreviewPath,
    setInspectorTab,
    openInspectorPath,
    clearInspectorPath,
  } = useApp();

  const [tokens, setTokens] = useState<TokenStats | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageLoadError, setUsageLoadError] = useState("");
  const [usageBaselineMessageCount, setUsageBaselineMessageCount] = useState(0);
  const [memoryContent, setMemoryContent] = useState("");
  const [savedMemoryContent, setSavedMemoryContent] = useState("");
  const [memoryLoadError, setMemoryLoadError] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memorySaveMsg, setMemorySaveMsg] = useState("");
  const [memoryActionMsg, setMemoryActionMsg] = useState("");
  const [memoryItemDraft, setMemoryItemDraft] = useState<MemoryItemDraft | null>(null);
  const [memoryFileOpen, setMemoryFileOpen] = useState(false);
  const [memoryEditorOpen, setMemoryEditorOpen] = useState(false);
  const [previewActionError, setPreviewActionError] = useState("");
  const [sourceArtifactMetadata, setSourceArtifactMetadata] = useState<
    Record<string, EvidenceArtifactMetadata | null>
  >({});
  const memoryRequestIdRef = useRef(0);
  const sourceMetadataRequestIdRef = useRef(0);
  const hasLoadedMemoryRef = useRef(false);
  const inspectionAccessStatus = accessByScope.inspection.status;

  const isMemoryDirty = memoryContent !== savedMemoryContent;
  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const parsedMemoryDocument = parseMemoryDocument(memoryContent);
  const memoryItems = parsedMemoryDocument.items;
  const showMemorySaveAction = !memoryLoadError && (isMemoryDirty || memorySaving);
  const memoryNamespaces = uniqueStrings([
    ...memoryItems.map((item) => item.namespace),
    memoryItemDraft?.namespace ?? null,
  ]);
  const latestRequestMessages = getLatestRequestMessages(messages);
  const scopedMessages = latestRequestMessages.length > 0 ? latestRequestMessages : messages;
  const artifactItems = collectArtifacts(scopedMessages);
  const sourceInspectorData = collectSourceInspectorData(messages);
  const reviewedSourceItems = sourceInspectorData.reviewedItems.map((item) =>
    item.path
      ? mergeSourceItemWithMetadata(item, sourceArtifactMetadata[item.path])
      : item
  );
  const sourcesSummary = buildSourcesInspectorSummary({
    scopedMessages: sourceInspectorData.scopedMessages,
    reviewedItems: reviewedSourceItems,
    retrievedItems: sourceInspectorData.retrievedItems,
  });
  const usageSummary = summarizeSessionUsage({
    sessionId: currentSessionId,
    messages,
    exactTokens: currentSessionId && tokens?.session_id === currentSessionId ? tokens : null,
    exactMessageCount: usageBaselineMessageCount,
  });
  const sessionUsage = usageSummary?.stats ?? null;
  const usageOrigin: UsageSummaryOrigin | null = usageSummary?.origin ?? null;
  const trackedTotalTokens =
    sessionUsage?.tracked_total_tokens ?? sessionUsage?.total_tokens ?? 0;
  const promptContextTokens = sessionUsage?.total_tokens ?? 0;
  const contextWindowRatio =
    sessionUsage?.context_window_tokens && sessionUsage.context_window_tokens > 0
      ? Math.min(promptContextTokens / sessionUsage.context_window_tokens, 1)
      : null;
  const contextWindowLabel = sessionUsage?.context_window_tokens
    ? `${formatCompactTokenValue(promptContextTokens)} / ${formatCompactTokenValue(sessionUsage.context_window_tokens)}`
    : null;
  const usageStatusLabel =
    usageOrigin === "tracked_live"
      ? "Live"
      : usageOrigin === "tracked"
        ? "Tracked"
        : "Estimated";
  const selectedArtifactItem =
    artifactItems.find((item) => item.path === inspectorPreviewPath) ?? null;
  const inspectorPreviewTarget: FilePreviewTarget | null = inspectorPreviewPath
    ? {
        path: inspectorPreviewPath,
        displayName:
          selectedArtifactItem?.label ??
          inspectorPreviewPath.split("/").pop() ??
          inspectorPreviewPath,
        artifactType:
          selectedArtifactItem?.artifactType ?? null,
        outputName: null,
        runId: null,
      }
    : null;
  const preview = useFilePreview(inspectorPreviewTarget);

  useEffect(() => {
    setPreviewActionError("");
  }, [inspectorPreviewPath]);

  useEffect(() => {
    if (!currentSessionId) {
      setTokens(null);
      setUsageLoading(false);
      setUsageLoadError("");
      setUsageBaselineMessageCount(0);
      return;
    }

    if (!hasInspectionAccess) {
      setUsageLoading(false);
      return;
    }

    if (isStreaming) {
      setUsageLoading(false);
      setTokens((current) =>
        current?.session_id === currentSessionId ? current : null
      );
      setUsageBaselineMessageCount((current) =>
        current > messages.length ? 0 : current
      );
      setUsageLoadError("");
      return;
    }

    let cancelled = false;
    setUsageLoading(true);
    setUsageLoadError("");

    void getSessionTokens(currentSessionId)
      .then((nextTokens) => {
        if (cancelled) {
          return;
        }

        setTokens(nextTokens);
        setUsageBaselineMessageCount(messages.length);
        setUsageLoadError("");
      })
      .catch(() => {
        if (cancelled) {
          return;
        }

        setTokens(null);
        setUsageBaselineMessageCount(0);
        setUsageLoadError(
          "Could not load tracked token usage. Showing a live estimate instead."
        );
      })
      .finally(() => {
        if (!cancelled) {
          setUsageLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [currentSessionId, hasInspectionAccess, isStreaming, messages.length]);

  useEffect(() => {
    if (
      inspectionAccessStatus === "granted" ||
      inspectionAccessStatus === "checking" ||
      inspectionAccessStatus === "unavailable"
    ) {
      return;
    }

    hasLoadedMemoryRef.current = false;
  }, [inspectionAccessStatus]);

  useEffect(() => {
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);

    if (inspectorTab === "memory") {
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      if (
        inspectionAccessStatus !== "granted" &&
        inspectionAccessStatus !== "checking" &&
        inspectionAccessStatus !== "unavailable" &&
        !hasLoadedMemoryRef.current
      ) {
        void loadMemory();
      }
    }
  }, [inspectorTab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!hasInspectionAccess) {
      return;
    }

    if (inspectorTab === "memory" && !hasLoadedMemoryRef.current) {
      void loadMemory();
    }
  }, [hasInspectionAccess, inspectorTab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (
      inspectionAccessStatus === "granted" ||
      inspectionAccessStatus === "checking" ||
      inspectionAccessStatus === "unavailable"
    ) {
      return;
    }

    setTokens(null);
    setUsageLoading(false);
    setUsageLoadError(accessByScope.inspection.detail);
    setUsageBaselineMessageCount(0);
    setMemoryContent("");
    setSavedMemoryContent("");
    setMemoryItemDraft(null);
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);
    setMemorySaveMsg("");
    setMemoryActionMsg("");
    setMemoryLoadError(accessByScope.inspection.detail);
  }, [accessByScope.inspection.detail, inspectionAccessStatus]);

  useEffect(() => {
    const pendingPaths = reviewedSourceItems
      .filter(
        (item) =>
          item.kind === "evidence" &&
          item.artifactType === "evidence_card" &&
          item.path &&
          !Object.prototype.hasOwnProperty.call(sourceArtifactMetadata, item.path)
      )
      .map((item) => item.path as string);

    if (pendingPaths.length === 0) {
      return;
    }

    const requestId = sourceMetadataRequestIdRef.current + 1;
    sourceMetadataRequestIdRef.current = requestId;

    void Promise.all(
      pendingPaths.map(async (path) => {
        try {
          const res = await readFile(path);
          return {
            path,
            metadata: parseEvidenceArtifactMetadata(path, res.content),
          };
        } catch {
          return { path, metadata: null };
        }
      })
    ).then((entries) => {
      if (sourceMetadataRequestIdRef.current !== requestId) {
        return;
      }

      setSourceArtifactMetadata((current) => {
        const next = { ...current };
        entries.forEach(({ path, metadata }) => {
          next[path] = metadata;
        });
        return next;
      });
    });
  }, [reviewedSourceItems, sourceArtifactMetadata]);

  const confirmDiscardChanges = (targetLabel: string) => {
    if (typeof window === "undefined") {
      return false;
    }

    return window.confirm(
      `Discard unsaved memory edits and load ${targetLabel} from disk?`
    );
  };

  const canReloadMemory = () =>
    !isMemoryDirty || confirmDiscardChanges(MEMORY_PATH);

  const loadMemory = async () => {
    const requestId = memoryRequestIdRef.current + 1;
    memoryRequestIdRef.current = requestId;
    setMemoryLoading(true);
    setMemoryLoadError("");

    if (!hasInspectionAccess) {
      setMemoryContent("");
      setSavedMemoryContent("");
      setMemoryItemDraft(null);
      setMemoryFileOpen(false);
      setMemoryEditorOpen(false);
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      setMemoryLoadError(accessByScope.inspection.detail);
      hasLoadedMemoryRef.current = false;
      setMemoryLoading(false);
      return;
    }

    try {
      const res = await readFile(MEMORY_PATH);
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent(res.content);
      setSavedMemoryContent(res.content);
      setMemoryLoadError("");
      hasLoadedMemoryRef.current = true;
    } catch {
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent("");
      setSavedMemoryContent("");
      setMemoryItemDraft(null);
      setMemoryFileOpen(false);
      setMemoryEditorOpen(false);
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      setMemoryLoadError(`Could not load \`${MEMORY_PATH}\`.`);
      hasLoadedMemoryRef.current = true;
    } finally {
      if (memoryRequestIdRef.current === requestId) {
        setMemoryLoading(false);
      }
    }
  };

  const openPreviewRawFile = () => {
    if (!inspectorPreviewPath || typeof window === "undefined") {
      return;
    }

    void openRawFileInNewTab(inspectorPreviewPath).catch(() => {
      setPreviewActionError("Could not open the raw file right now.");
    });
  };

  const openRawFile = (path: string) => {
    if (typeof window === "undefined") {
      return;
    }

    void openRawFileInNewTab(path).catch(() => {
      setMemoryActionMsg("Raw file unavailable");
      window.setTimeout(() => setMemoryActionMsg(""), 2000);
    });
  };

  const inspectPathInFiles = (path: string) => {
    openInspectorPath(path);
    setInspectorTab("files");
  };

  const flashMemoryAction = (message: string) => {
    setMemoryActionMsg(message);
    window.setTimeout(() => setMemoryActionMsg(""), 2000);
  };

  const handleInspectorExport = () => {
    if (typeof window === "undefined" || messages.length === 0) {
      return;
    }

    const title =
      activeSession?.title?.trim() || currentSessionId || "BioAPEX Session";
    const content = buildExportMarkdown(title, messages);
    const blob = new Blob([content], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${exportFilename(title)}.md`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const handleMemoryRefresh = async () => {
    if (!canReloadMemory()) {
      return;
    }

    setMemoryItemDraft(null);
    await loadMemory();
  };

  const handleMemorySave = async () => {
    if (!isMemoryDirty) return;

    setMemorySaving(true);
    setMemorySaveMsg("");

    try {
      await saveFile(MEMORY_PATH, memoryContent);
      setSavedMemoryContent(memoryContent);
      setMemorySaveMsg("Saved");
      setTimeout(() => setMemorySaveMsg(""), 2000);
    } catch {
      setMemorySaveMsg("Save failed");
    } finally {
      setMemorySaving(false);
    }
  };

  const startMemoryItemDraft = (item?: MemoryInspectorItem) => {
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);
    setMemoryItemDraft(
      item
        ? {
            mode: "edit",
            targetId: item.id,
            namespace: item.namespace,
            key: item.key,
            value: item.value,
          }
        : {
            mode: "create",
            targetId: null,
            namespace: memoryItems[0]?.namespace ?? "General",
            key: "",
            value: "",
          }
    );
  };

  const handleMemoryDraftSave = () => {
    if (!memoryItemDraft) {
      return;
    }

    if (!memoryItemDraft.key.trim() && !memoryItemDraft.value.trim()) {
      flashMemoryAction("Add a key or value first");
      return;
    }

    const nextDocument = upsertMemoryDocumentItem(parsedMemoryDocument, memoryItemDraft);
    setMemoryContent(serializeMemoryDocument(nextDocument));
    setMemoryItemDraft(null);
    flashMemoryAction(
      memoryItemDraft.mode === "create" ? "Memory item added" : "Memory item updated"
    );
  };

  const handleMemoryItemDelete = (itemId: string) => {
    const nextDocument = removeMemoryDocumentItem(parsedMemoryDocument, itemId);
    setMemoryContent(serializeMemoryDocument(nextDocument));
    if (memoryItemDraft?.targetId === itemId) {
      setMemoryItemDraft(null);
    }
    flashMemoryAction("Memory item removed");
  };

  const handleMemoryItemDuplicate = (itemId: string) => {
    const nextDocument = duplicateMemoryDocumentItem(parsedMemoryDocument, itemId);
    setMemoryContent(serializeMemoryDocument(nextDocument));
    flashMemoryAction("Memory item duplicated");
  };

  const renderFilesTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Current Turn"
        meta={scopedMessages.at(-1)?.request_id ?? undefined}
      >
        {scopedMessages.length > 0 ? (
          <div
            className="space-y-2 rounded-[12px] border border-[rgba(35,130,83,0.14)] bg-[linear-gradient(180deg,rgba(242,250,245,0.98),rgba(234,247,239,0.98))] px-2.5 py-2.5"
          >
            <div className="grid grid-cols-2 gap-1.5">
              <MiniStat
                label="Messages"
                value={String(scopedMessages.length)}
                accent={isStreaming}
              />
              <MiniStat
                label="Artifacts"
                value={String(artifactItems.length)}
                accent={artifactItems.length > 0}
              />
            </div>

            <p className="text-[11px] leading-5 text-slate-600">
              Generated files and source evidence below are scoped to the latest chat request.
            </p>
          </div>
        ) : (
          <EmptyState>
            Send a message to populate generated files and source detail here.
          </EmptyState>
        )}
      </InspectorCard>

      <InspectorCard
        title="Generated"
        meta={`${artifactItems.length} item${artifactItems.length === 1 ? "" : "s"}`}
      >
        {artifactItems.length > 0 ? (
          <div className="space-y-1">
            {artifactItems.map((artifact) => (
              <GeneratedFileRow
                key={artifact.path}
                item={artifact}
                active={inspectorPreviewPath === artifact.path}
                onClick={() => openInspectorPath(artifact.path)}
              />
            ))}
          </div>
        ) : (
          <EmptyState>
            Generated files will appear here once tool calls materialize inspectable artifacts.
          </EmptyState>
        )}
      </InspectorCard>

      {inspectorPreviewPath ? (
        <InspectorCard
          title="Preview"
          meta={shortenPath(inspectorPreviewPath, 3)}
          controls={
            <>
              <ActionButton onClick={preview.refresh}>
                <RefreshCw size={11} />
                Refresh
              </ActionButton>
              <ActionButton onClick={openPreviewRawFile}>Open raw</ActionButton>
              <ActionButton onClick={clearInspectorPath}>Clear</ActionButton>
            </>
          }
        >
          {previewActionError ? <EmptyState>{previewActionError}</EmptyState> : null}
          <FilePreviewSurface
            target={inspectorPreviewTarget}
            preview={preview}
            emptyMessage="Select a generated file to preview it here."
            compact
            className={previewActionError ? "mt-2" : undefined}
          />
        </InspectorCard>
      ) : null}
    </div>
  );

  const renderSourcesTab = () => (
    <div className="space-y-3">
      <section className="space-y-2">
        <div className="flex items-baseline justify-between gap-2 px-0.5">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Citations
          </h3>
          {sourcesSummary.scoped_message_count > 0 ? (
            <span className="text-[10px] text-slate-400">
              {pluralize(sourcesSummary.scoped_message_count, "message")}
            </span>
          ) : null}
        </div>

        {sourcesSummary.citations.length > 0 ? (
          <div className="space-y-1">
            {sourcesSummary.citations.map((citation) => (
              <SourceCitationRow
                key={citation.id}
                citation={citation}
                onInspect={openInspectorPath}
              />
            ))}
          </div>
        ) : (
          <EmptyState>
            No reviewed evidence or retrieval-backed citations are linked to the current turn yet. Evidence retrieval and evidence review outputs will populate this view.
          </EmptyState>
        )}
      </section>

      <section
        className={cn(
          "rounded-[16px] border px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)]",
          getChecklistCardClass(sourcesSummary.checklist.state)
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
              Source checklist
            </h3>
            {sourcesSummary.checklist.detail &&
            sourcesSummary.checklist.state !== "complete" ? (
              <p className="mt-1 text-[10px] leading-4 text-slate-500">
                {sourcesSummary.checklist.detail}
              </p>
            ) : null}
          </div>
          {sourcesSummary.checklist.summary_label ? (
            <span
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
                getChecklistBadgeClass(sourcesSummary.checklist.state)
              )}
            >
              {sourcesSummary.checklist.summary_label}
            </span>
          ) : null}
        </div>

        <div className="mt-3 space-y-2">
          {sourcesSummary.checklist.items.map((item) => (
            <ChecklistRow key={item.id} item={item} />
          ))}
        </div>
      </section>
    </div>
  );

  const renderMemoryTab = () => (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2 px-0.5">
        <div className="min-w-0">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Context Memory
          </h3>
          <p className="mt-1 truncate text-[10px] leading-4 text-slate-500">
            Synced to `{MEMORY_PATH}`
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <ActionButton onClick={() => void handleMemoryRefresh()}>
            <RefreshCw size={11} />
            Refresh
          </ActionButton>
          <ActionButton
            onClick={() => {
              if (memoryLoadError) {
                openRawFile(MEMORY_PATH);
                return;
              }

              setMemoryFileOpen((value) => !value);
              setMemoryEditorOpen(false);
            }}
          >
            <BookOpen size={11} />
            {memoryLoadError ? "Open raw" : memoryFileOpen ? "Hide file" : "Raw file"}
          </ActionButton>
          {showMemorySaveAction ? (
            <PrimaryActionButton
              onClick={() => void handleMemorySave()}
              disabled={!isMemoryDirty || memorySaving}
            >
              <Save size={11} />
              {memorySaving ? "Saving…" : "Save"}
            </PrimaryActionButton>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 px-0.5">
        {memoryLoadError ? (
          <MetaBadge tone="warning">Load issue</MetaBadge>
        ) : (
          <>
            <MetaBadge tone={isMemoryDirty ? "warning" : "success"}>
              {isMemoryDirty ? "Unsaved edits" : "File synced"}
            </MetaBadge>
            <MetaBadge>{pluralize(memoryItems.length, "item")}</MetaBadge>
            {memoryItemDraft ? <MetaBadge tone="accent">Draft open</MetaBadge> : null}
          </>
        )}
        {memorySaveMsg ? (
          <MetaBadge tone={memorySaveMsg === "Saved" ? "success" : "warning"}>
            {memorySaveMsg}
          </MetaBadge>
        ) : null}
        {memoryActionMsg ? <MetaBadge tone="accent">{memoryActionMsg}</MetaBadge> : null}
      </div>

      {memoryLoading ? (
        <LoadingState label="Loading memory..." />
      ) : memoryLoadError ? (
        <div className="space-y-2">
          <EmptyState>
            {memoryLoadError} Structured memory editing is paused until the file can
            be read again.
          </EmptyState>

          <div className="rounded-[16px] border border-[rgba(211,219,210,0.86)] bg-[rgba(251,252,248,0.92)] px-3 py-3">
            <p className="text-[10px] leading-4 text-slate-500">
              Use the raw file or Files inspector if you need to inspect the path
              directly, then refresh this tab once `memory/MEMORY.md` is reachable
              again.
            </p>

            <div className="mt-2 flex flex-wrap gap-1.5">
              <ActionButton onClick={() => openRawFile(MEMORY_PATH)}>
                Open raw
              </ActionButton>
              <ActionButton onClick={() => inspectPathInFiles(MEMORY_PATH)}>
                Inspect
              </ActionButton>
            </div>
          </div>
        </div>
      ) : (
        <>
          {memoryItemDraft ? (
            <div className="rounded-[16px] border border-[rgba(35,130,83,0.16)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,251,248,0.98))] px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)]">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
                  {memoryItemDraft.mode === "create" ? "Add Memory Item" : "Edit Memory Item"}
                </p>
                <MetaBadge tone="warning">Draft</MetaBadge>
              </div>

              <div className="mt-3 space-y-2">
                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Namespace
                  </label>
                  <input
                    list="memory-namespaces"
                    value={memoryItemDraft.namespace}
                    onChange={(event) =>
                      setMemoryItemDraft((current) =>
                        current
                          ? { ...current, namespace: event.target.value }
                          : current
                      )
                    }
                    className="w-full rounded-[12px] border border-[rgba(211,219,210,0.9)] bg-white px-3 py-2 text-[12px] text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                  />
                  {memoryNamespaces.length > 0 ? (
                    <datalist id="memory-namespaces">
                      {memoryNamespaces.map((namespace) => (
                        <option key={namespace} value={namespace} />
                      ))}
                    </datalist>
                  ) : null}
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Key
                  </label>
                  <input
                    value={memoryItemDraft.key}
                    onChange={(event) =>
                      setMemoryItemDraft((current) =>
                        current
                          ? { ...current, key: event.target.value }
                          : current
                      )
                    }
                    className="w-full rounded-[12px] border border-[rgba(211,219,210,0.9)] bg-white px-3 py-2 text-[12px] text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                    placeholder="dataset"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Value
                  </label>
                  <textarea
                    rows={4}
                    value={memoryItemDraft.value}
                    onChange={(event) =>
                      setMemoryItemDraft((current) =>
                        current
                          ? { ...current, value: event.target.value }
                          : current
                      )
                    }
                    className="w-full rounded-[12px] border border-[rgba(211,219,210,0.9)] bg-white px-3 py-2 text-[12px] leading-5 text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                    placeholder="BRCA1_cohort_v2"
                  />
                </div>
              </div>

              <div className="mt-3 flex items-center justify-end gap-1.5">
                <ActionButton onClick={() => setMemoryItemDraft(null)}>
                  Cancel
                </ActionButton>
                <PrimaryActionButton onClick={handleMemoryDraftSave}>
                  <Save size={11} />
                  Apply
                </PrimaryActionButton>
              </div>
            </div>
          ) : null}

          {memoryItems.length > 0 ? (
            <div className="space-y-2.5">
              {memoryItems.map((item) => (
                <div
                  key={item.id}
                  className="rounded-[18px] border border-[rgba(219,226,216,0.94)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(251,252,248,0.98))] px-3.5 py-3.5 shadow-[0_1px_3px_rgba(32,43,35,0.04)]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate font-mono text-[11px] font-semibold text-[var(--apex-accent-strong)]">
                      {item.namespace}/{item.key}
                    </p>
                    <MetaBadge tone="success">ACTIVE</MetaBadge>
                  </div>

                  <p className="mt-3 break-words font-mono text-[15px] leading-6 text-slate-700">
                    {item.value || item.key}
                  </p>

                  <div className="mt-3 flex items-center gap-1">
                    <MemoryCardActionButton
                      onClick={() => startMemoryItemDraft(item)}
                      title="Edit memory item"
                    >
                      <Pencil size={16} />
                    </MemoryCardActionButton>
                    <MemoryCardActionButton
                      onClick={() => handleMemoryItemDuplicate(item.id)}
                      title="Duplicate memory item"
                    >
                      <Copy size={16} />
                    </MemoryCardActionButton>
                    <div className="ml-auto">
                      <MemoryCardActionButton
                        onClick={() => handleMemoryItemDelete(item.id)}
                        title="Delete memory item"
                        tone="danger"
                      >
                        <Trash2 size={16} />
                      </MemoryCardActionButton>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState>
              No structured memory items are available yet. Add an item here or
              open the raw file when you want to shape `MEMORY.md` directly.
            </EmptyState>
          )}

          <WideActionButton onClick={() => startMemoryItemDraft()}>
            <Plus size={13} />
            Add Item
          </WideActionButton>

          {memoryFileOpen ? (
            <div className="rounded-[16px] border border-[rgba(211,219,210,0.86)] bg-[rgba(251,252,248,0.92)] px-3 py-3">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Underlying File
                  </p>
                  <p className="mt-1 truncate text-[10px] leading-4 text-slate-500">
                    {MEMORY_PATH}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <ActionButton onClick={() => setMemoryEditorOpen((value) => !value)}>
                    <BookOpen size={11} />
                    {memoryEditorOpen ? "Preview" : "Edit"}
                  </ActionButton>
                </div>
              </div>

              <p className="mt-2 text-[10px] leading-4 text-slate-500">
                Structured card edits write back to this markdown file so memory
                retrieval and file inspection stay aligned.
              </p>

              <div className="mt-2 flex flex-wrap gap-1.5">
                <ActionButton onClick={() => openRawFile(MEMORY_PATH)}>
                  Open raw
                </ActionButton>
                <ActionButton onClick={() => inspectPathInFiles(MEMORY_PATH)}>
                  Inspect
                </ActionButton>
              </div>

              <div className="mt-2">
                {memoryEditorOpen ? (
                  <div className="h-[220px] overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.86)] bg-white">
                    <MonacoEditor
                      height="100%"
                      language="markdown"
                      value={memoryContent}
                      theme="vs"
                      onChange={(value) => setMemoryContent(value ?? "")}
                      options={{
                        minimap: { enabled: false },
                        wordWrap: "on",
                        fontSize: 11,
                        lineNumbers: "on",
                        scrollBeyondLastLine: false,
                        overviewRulerLanes: 0,
                        padding: { top: 10, bottom: 10 },
                        fontFamily: '"SF Mono", "Fira Code", Consolas, monospace',
                      }}
                    />
                  </div>
                ) : (
                  <PreviewPane content={memoryContent} className="max-h-[220px]" />
                )}
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );

  const renderUsageTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Usage"
        controls={
          <MetaBadge tone={usageOrigin === "tracked_live" ? "accent" : "neutral"}>
            {usageStatusLabel}
          </MetaBadge>
        }
      >
        {!currentSessionId ? (
          <EmptyState>Select a session to inspect token usage.</EmptyState>
        ) : usageLoading && !sessionUsage ? (
          <LoadingState label="Loading usage..." />
        ) : sessionUsage && (trackedTotalTokens > 0 || messages.length > 0) ? (
          <div className="space-y-4">
            <div className="pt-1 text-center">
              <p className="text-[40px] font-semibold tracking-[-0.06em] text-slate-800">
                {trackedTotalTokens.toLocaleString()}
              </p>
              <p className="mt-1 text-[11px] text-slate-400">Total tokens</p>
            </div>

            <div className="space-y-1.5">
              <UsageMetricRow
                label="Input"
                value={sessionUsage.input_tokens.toLocaleString()}
              />
              <UsageMetricRow
                label="Output"
                value={sessionUsage.output_tokens.toLocaleString()}
              />
              <UsageMetricRow
                label="Tools"
                value={sessionUsage.tool_tokens.toLocaleString()}
              />
            </div>

            <div className="space-y-1.5 pt-0.5">
              <div className="flex items-center justify-between gap-3 text-[12px] leading-5">
                <span>Context</span>
                <span className="font-semibold text-slate-700">
                  {contextWindowLabel ?? "Unavailable"}
                </span>
              </div>
              <div className="h-[2px] overflow-hidden rounded-full bg-[rgba(211,219,210,0.76)]">
                {contextWindowRatio !== null ? (
                  <div
                    className="h-full rounded-full bg-[var(--apex-accent)]"
                    style={{ width: `${contextWindowRatio * 100}%` }}
                  />
                ) : null}
              </div>
              {contextWindowLabel ? null : (
                <p className="text-[10px] leading-4 text-slate-500">
                  Context-window budget is not configured for this model.
                </p>
              )}
            </div>
          </div>
        ) : usageLoading ? (
          <LoadingState label="Loading usage..." />
        ) : (
          <EmptyState>
            Send a message in this session to populate token usage here.
          </EmptyState>
        )}
      </InspectorCard>
    </div>
  );

  const renderTurnsTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Turn Details"
        controls={
          <MetaBadge tone={messages.length > 0 ? "accent" : "neutral"}>
            {pluralize(messages.length, "message")}
          </MetaBadge>
        }
      >
        {messages.length === 0 ? (
          <EmptyState>Start a conversation to inspect turn details.</EmptyState>
        ) : (
          <div className="space-y-3">
            <p className="rounded-[10px] bg-[rgba(251,252,248,0.86)] px-2 py-1.5 text-[10px] leading-4 text-slate-500">
              Main chat stays concise after each turn. This view keeps the
              detailed retrieval, tool, and response trace available
              for inspection.
            </p>
            <TurnDetailsPanel messages={messages} />
          </div>
        )}
      </InspectorCard>
    </div>
  );

  return (
    <aside className="apex-panel apex-panel-muted flex h-full flex-col overflow-hidden rounded-[18px]">
      <div className="border-b border-[var(--shell-border)] bg-white/70 px-2 py-1.5">
        <div className="grid grid-cols-5 gap-0.5">
          {INSPECTOR_TABS.map((tab) => (
            <TabButton
              key={tab.id}
              active={inspectorTab === tab.id}
              icon={tab.icon}
              label={tab.label}
              ariaLabel={`Inspector ${tab.label}`}
              onClick={() => setInspectorTab(tab.id)}
            />
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {inspectorTab === "files" && renderFilesTab()}
        {inspectorTab === "sources" && renderSourcesTab()}
        {inspectorTab === "memory" && renderMemoryTab()}
        {inspectorTab === "usage" && renderUsageTab()}
        {inspectorTab === "turns" && renderTurnsTab()}
      </div>

      <div className="border-t border-[var(--shell-border)] bg-white/70 px-2 py-2">
        <button
          type="button"
          onClick={handleInspectorExport}
          disabled={messages.length === 0}
          className={cn(
            "inline-flex w-full items-center justify-center gap-1.5 rounded-full border px-3 py-2 text-[11px] font-semibold transition-colors",
            messages.length === 0
              ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
              : "border-[rgba(211,219,210,0.92)] bg-white text-slate-700 shadow-[0_1px_2px_rgba(32,43,35,0.03)] hover:border-[rgba(35,130,83,0.2)] hover:bg-[var(--panel-soft)] hover:text-[var(--apex-accent-strong)]"
          )}
          title={
            messages.length === 0
              ? "Start a conversation to export this workspace."
              : "Export the current session transcript."
          }
        >
          <Download size={14} />
          Export
        </button>
      </div>
    </aside>
  );
}
