"use client";

import dynamic from "next/dynamic";
import Image from "next/image";
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  BookOpen,
  Brain,
  Copy,
  Download,
  FileText,
  Hash,
  Package,
  Plus,
  Pencil,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  getRawFileUrl,
  getSessionTokens,
  listSkillsRegistry,
  readFile,
  saveFile,
} from "@/lib/api";
import {
  getLatestRequestMessages,
  getWorkflowSummary,
} from "@/lib/session-status";
import {
  getEvidenceRetrievalPayload,
  parseEvidenceArtifactMetadata,
  getEvidenceReviewPayload,
  type EvidenceArtifactMetadata,
} from "@/lib/evidence";
import { useApp } from "@/lib/store";
import { cn } from "@/lib/utils";
import type {
  ConfidenceLevel,
  Message,
  SkillRegistryEntry,
  TokenStats,
  ToolResultEnvelope,
  WorkflowArtifactScope,
  WorkflowStreamEvent,
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
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "usage", label: "Usage", icon: Hash },
] as const;

type GeneratedArtifactItem = {
  path: string;
  label: string;
  artifactType: string | null;
  scope: WorkflowArtifactScope | null;
  outputName: string | null;
  stepLabel: string | null;
  lastSeenOrder: number;
};

type GeneratedArtifactKind =
  | "table"
  | "plot"
  | "structured"
  | "report"
  | "archive"
  | "file";

type InspectorPreviewMode = "text" | "image" | "pdf" | "unsupported";

type SourceInspectorItemKind = "review" | "evidence" | "retrieval";

type SourceInspectorTone =
  | "supported"
  | "mixed"
  | "insufficient"
  | "retrieved"
  | "warning"
  | "neutral";

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

function humanizeToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function humanizeLabel(value?: string | null): string | null {
  const humanized = humanizeToken(value);
  if (!humanized) {
    return null;
  }

  return humanized.charAt(0).toUpperCase() + humanized.slice(1);
}

function compactText(value?: string | null, maxLength = 160): string | null {
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

function formatWorkflowEvent(event: WorkflowStreamEvent) {
  switch (event.type) {
    case "workflow_start":
      return `${event.workflow_name} started`;
    case "workflow_done":
      return `${event.workflow_id} ${event.lifecycle_status}`;
    case "workflow_blocked":
      return `${event.workflow_id} blocked: ${event.reason}`;
    case "workflow_step_start":
      return `${event.step_label} running`;
    case "workflow_step_end":
      return `${event.step_label} ${event.status}`;
    case "workflow_artifact":
      return `${event.scope}: ${event.artifact.path}`;
  }
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

    if (message.retrievals?.length) {
      lines.push("");
      lines.push("Retrieved sources:");
      message.retrievals.forEach((result) => {
        lines.push(`- ${result.source} (score ${result.score.toFixed(3)})`);
      });
    }

    if (message.workflow_events?.length) {
      lines.push("");
      lines.push("Workflow events:");
      message.workflow_events.forEach((event) => {
        lines.push(`- ${formatWorkflowEvent(event)}`);
      });
    }

    if (message.tool_calls?.length) {
      lines.push("");
      lines.push("Tool calls:");
      message.tool_calls.forEach((call) => {
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
    return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`;
  }

  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}K`;
  }

  return value.toString();
}

function shortIdentifier(value: string, prefixLength = 8, suffixLength = 4): string {
  if (value.length <= prefixLength + suffixLength + 1) {
    return value;
  }

  return `${value.slice(0, prefixLength)}…${value.slice(-suffixLength)}`;
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

function groupMemoryItemsByNamespace(items: MemoryInspectorItem[]) {
  const groups = new Map<string, MemoryInspectorItem[]>();

  items.forEach((item) => {
    const namespace = item.namespace.trim() || "General";
    const existing = groups.get(namespace);
    if (existing) {
      existing.push(item);
    } else {
      groups.set(namespace, [item]);
    }
  });

  return Array.from(groups.entries()).map(([namespace, sectionItems]) => ({
    namespace,
    items: sectionItems,
  }));
}

function getMemoryItemSummary(item: MemoryInspectorItem): string {
  if (item.value) {
    return compactText(item.value, 120) ?? item.value;
  }

  return compactText(item.key, 120) ?? item.key;
}

function getSkillVersionLabel(skill: SkillRegistryEntry): string {
  return skill.version.trim() || "Local";
}

function getSkillMetadata(skill: SkillRegistryEntry): string[] {
  return uniqueStrings([
    skill.enabled ? "Enabled" : "Available",
    humanizeLabel(skill.category),
    humanizeLabel(skill.stage),
    humanizeLabel(skill.stability),
  ]);
}

function getUsageShare(value: number, total: number): string {
  if (total <= 0) {
    return "0%";
  }

  return `${Math.round((value / total) * 100)}%`;
}

function getFileExtension(path: string): string | null {
  const fileName = path.split("/").pop() ?? path;
  const index = fileName.lastIndexOf(".");
  if (index <= 0 || index === fileName.length - 1) {
    return null;
  }
  return fileName.slice(index).toLowerCase();
}

function getInspectorPreviewMode(path: string): InspectorPreviewMode {
  const extension = getFileExtension(path);

  if (
    extension === ".png" ||
    extension === ".jpg" ||
    extension === ".jpeg" ||
    extension === ".svg"
  ) {
    return "image";
  }

  if (extension === ".pdf") {
    return "pdf";
  }

  if (
    extension === ".zip" ||
    extension === ".gz" ||
    extension === ".tgz" ||
    extension === ".tar" ||
    extension === ".tif" ||
    extension === ".tiff" ||
    extension === ".xlsx" ||
    extension === ".xls" ||
    extension === ".parquet" ||
    extension === ".mtx"
  ) {
    return "unsupported";
  }

  return "text";
}

function getUnsupportedPreviewMessage(path: string): string {
  const extension = getFileExtension(path);

  if (
    extension === ".zip" ||
    extension === ".gz" ||
    extension === ".tgz" ||
    extension === ".tar"
  ) {
    return "Archive previews are not available in the inspector yet. Use Open raw to inspect or download the artifact.";
  }

  if (extension === ".tif" || extension === ".tiff") {
    return "This image format is not previewed inline in the inspector yet. Use Open raw to inspect the artifact.";
  }

  if (
    extension === ".xlsx" ||
    extension === ".xls" ||
    extension === ".parquet" ||
    extension === ".mtx"
  ) {
    return "This generated table format is not previewed inline yet. Use Open raw to inspect the artifact.";
  }

  return "This file is not previewed inline in the inspector yet. Use Open raw to inspect the artifact.";
}

function shouldShowGeneratedArtifact(item: {
  path: string;
  artifactType: string | null;
  scope: WorkflowArtifactScope | null;
}): boolean {
  if (!item.path) {
    return false;
  }

  if (item.scope === "run_record") {
    return false;
  }

  if (item.artifactType === "workflow_run") {
    return false;
  }

  return true;
}

function collectArtifacts(events: WorkflowStreamEvent[]) {
  const items = new Map<string, GeneratedArtifactItem>();
  let order = 0;

  const upsertArtifact = ({
    path,
    artifactType,
    scope,
    outputName,
    stepLabel,
  }: {
    path: string;
    artifactType?: string | null;
    scope?: WorkflowArtifactScope | null;
    outputName?: string | null;
    stepLabel?: string | null;
  }) => {
    const existing = items.get(path);
    const nextItem: GeneratedArtifactItem = {
      path,
      label: path.split("/").pop() ?? path,
      artifactType: artifactType ?? existing?.artifactType ?? null,
      scope: scope ?? existing?.scope ?? null,
      outputName: outputName ?? existing?.outputName ?? null,
      stepLabel: stepLabel ?? existing?.stepLabel ?? null,
      lastSeenOrder: order,
    };
    order += 1;

    if (!shouldShowGeneratedArtifact(nextItem)) {
      return;
    }

    items.set(path, nextItem);
  };

  events.forEach((event) => {
    if (event.type === "workflow_artifact") {
      upsertArtifact({
        path: event.artifact.path,
        artifactType: event.artifact.artifact_type,
        scope: event.scope,
        outputName: event.output_name,
        stepLabel: event.step_label,
      });
    }

    if (event.type === "workflow_step_end") {
      event.artifact_refs.forEach((artifact) => {
        upsertArtifact({
          path: artifact.path,
          artifactType: artifact.artifact_type,
          outputName: null,
          stepLabel: event.step_label,
        });
      });
    }
  });

  return Array.from(items.values())
    .sort((left, right) => right.lastSeenOrder - left.lastSeenOrder)
    .slice(0, 12);
}

function inferGeneratedArtifactKind(item: GeneratedArtifactItem): GeneratedArtifactKind {
  const extension = getFileExtension(item.path);
  const artifactType = item.artifactType?.toLowerCase() ?? "";
  const outputName = item.outputName?.toLowerCase() ?? "";
  const label = item.label.toLowerCase();

  if (
    extension === ".csv" ||
    extension === ".tsv" ||
    extension === ".xlsx" ||
    extension === ".xls" ||
    extension === ".parquet" ||
    extension === ".mtx" ||
    artifactType.includes("matrix") ||
    artifactType.includes("results") ||
    outputName.includes("table") ||
    label.includes("matrix")
  ) {
    return "table";
  }

  if (
    extension === ".png" ||
    extension === ".jpg" ||
    extension === ".jpeg" ||
    extension === ".svg" ||
    extension === ".tif" ||
    extension === ".tiff" ||
    artifactType === "figure" ||
    outputName.includes("plot") ||
    outputName.includes("figure")
  ) {
    return "plot";
  }

  if (
    extension === ".html" ||
    extension === ".pdf" ||
    extension === ".md" ||
    artifactType.includes("report")
  ) {
    return "report";
  }

  if (
    extension === ".json" ||
    extension === ".yaml" ||
    extension === ".yml" ||
    artifactType.includes("manifest") ||
    artifactType.includes("summary") ||
    artifactType.includes("metrics")
  ) {
    return "structured";
  }

  if (
    extension === ".zip" ||
    extension === ".gz" ||
    extension === ".tgz" ||
    extension === ".tar"
  ) {
    return "archive";
  }

  return "file";
}

function getGeneratedArtifactCue(item: GeneratedArtifactItem) {
  const extension = getFileExtension(item.path);
  const kind = inferGeneratedArtifactKind(item);

  if (extension === ".json") {
    return { kind, label: "JSON" };
  }

  if (extension === ".yaml" || extension === ".yml") {
    return { kind, label: "YAML" };
  }

  if (extension === ".csv") {
    return { kind, label: "CSV" };
  }

  if (extension === ".tsv") {
    return { kind, label: "TSV" };
  }

  if (extension === ".html") {
    return { kind, label: "HTML" };
  }

  if (extension === ".pdf") {
    return { kind, label: "PDF" };
  }

  if (extension === ".md") {
    return { kind, label: "MD" };
  }

  if (kind === "table") {
    return { kind, label: "Table" };
  }

  if (kind === "plot") {
    return { kind, label: "Plot" };
  }

  if (kind === "report") {
    return { kind, label: "Report" };
  }

  if (kind === "structured") {
    return { kind, label: "Data" };
  }

  if (kind === "archive") {
    return { kind, label: "Archive" };
  }

  return { kind, label: "File" };
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
  const values = [
    humanizeToken(item.outputName),
    humanizeToken(item.artifactType),
    humanizeToken(item.stepLabel),
  ].filter((value): value is string => Boolean(value));

  const uniqueValues = values.filter(
    (value, index) => values.indexOf(value) === index
  );

  return uniqueValues[0] ?? "Generated artifact";
}

function getGeneratedArtifactScopeLabel(item: GeneratedArtifactItem): string | null {
  return humanizeToken(item.scope);
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

function getSourceScopeMessages(
  messages: Message[],
  workflowSummary: ReturnType<typeof getWorkflowSummary>
) {
  const latestMessages = getLatestRequestMessages(messages);
  const latestRunId = workflowSummary.events.at(-1)?.run_id ?? null;

  if (!latestRunId) {
    return latestMessages;
  }

  const scopedIds = new Set<string>(latestMessages.map((message) => message.id));
  messages.forEach((message) => {
    if ((message.workflow_events ?? []).some((event) => event.run_id === latestRunId)) {
      scopedIds.add(message.id);
    }
  });

  return messages.filter((message) => scopedIds.has(message.id));
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

function collectSourceInspectorData(
  messages: Message[],
  workflowSummary: ReturnType<typeof getWorkflowSummary>
) {
  const scopedMessages = getSourceScopeMessages(messages, workflowSummary);
  const reviewedItems = new Map<string, SourceInspectorItem>();
  const retrievedSources = new Map<string, RetrievedSourceSummary>();
  let order = 0;

  scopedMessages.forEach((message, messageIndex) => {
    (message.tool_calls ?? []).forEach((call, callIndex) => {
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

    (message.retrievals ?? []).forEach((result) => {
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

function getRunStatusLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.status === "not_started") {
    return "Not started";
  }

  if (summary.status === "running") {
    return "In progress";
  }

  if (summary.status === "blocked") {
    return "Blocked";
  }

  if (summary.status === "failed") {
    return "Failed";
  }

  if (summary.status === "completed") {
    return "Completed";
  }

  return "Idle";
}

function getRunStatusClass(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.status === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }

  if (summary.status === "blocked" || summary.status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }

  if (summary.status === "not_started") {
    return "border-slate-200 bg-slate-50 text-slate-600";
  }

  return "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]";
}

function getRunSurfaceClass(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.status === "completed") {
    return "border-emerald-100 bg-[linear-gradient(180deg,rgba(244,251,247,0.98),rgba(237,249,241,0.98))]";
  }

  if (summary.status === "blocked" || summary.status === "failed") {
    return "border-rose-100 bg-[linear-gradient(180deg,rgba(255,247,247,0.98),rgba(254,241,241,0.98))]";
  }

  if (summary.status === "not_started") {
    return "border-slate-200 bg-[linear-gradient(180deg,rgba(249,250,251,0.98),rgba(245,247,249,0.98))]";
  }

  return "border-[rgba(35,130,83,0.14)] bg-[linear-gradient(180deg,rgba(242,250,245,0.98),rgba(234,247,239,0.98))]";
}

function getStepCountLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.totalSteps !== null) {
    return `${summary.completedSteps}/${summary.totalSteps}`;
  }

  if (summary.observedSteps > 0) {
    return `${summary.completedSteps}/${summary.observedSteps}`;
  }

  return "0";
}

function getProgressLabel(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.currentStep) {
    return summary.currentStep;
  }

  if (summary.status === "not_started") {
    return summary.lifecycleStatus === "preflight_checked"
      ? "Preflight checked"
      : "Waiting for first step";
  }

  if (summary.status === "running") {
    return summary.observedSteps > 0 ? "Awaiting next step" : "Starting workflow";
  }

  if (summary.status === "blocked") {
    return "Action required";
  }

  if (summary.status === "failed") {
    return "Run halted";
  }

  if (summary.status === "completed") {
    return "All steps finished";
  }

  return null;
}

function getRunDetail(summary: ReturnType<typeof getWorkflowSummary>) {
  if (summary.currentStep) {
    return `Current: ${summary.currentStep}`;
  }

  if (summary.blockedReason) {
    return summary.blockedReason;
  }

  if (summary.failureReason) {
    return summary.failureReason;
  }

  if (summary.status === "not_started") {
    return summary.totalSteps !== null
      ? `Run is staged with ${summary.totalSteps} step${summary.totalSteps === 1 ? "" : "s"} and waiting to begin.`
      : "Run is staged and waiting for the first workflow step.";
  }

  if (summary.status === "completed") {
    return "Run finished.";
  }

  if (summary.status === "running") {
    return "Waiting for the next step update.";
  }

  if (summary.status === "failed") {
    return "The latest workflow run failed.";
  }

  return "No active workflow step yet.";
}

function TabButton({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: typeof FileText;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-[42px] flex-col items-center justify-center gap-0.5 rounded-[10px] border px-1 py-1 text-center transition-colors",
        active
          ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.1)] text-[var(--apex-accent-strong)]"
          : "border-transparent text-slate-500 hover:border-[var(--shell-border)] hover:bg-white/80 hover:text-slate-700"
      )}
    >
      <Icon size={12} strokeWidth={1.75} />
      <span className="text-[9px] font-medium leading-tight">{label}</span>
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
    <section className="rounded-[14px] border border-[rgba(211,219,210,0.86)] bg-[rgba(255,255,255,0.88)] px-2.5 py-2.5 shadow-[0_1px_2px_rgba(32,43,35,0.03)] backdrop-blur-sm">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            {title}
          </h3>
          {meta ? (
            <p className="mt-0.5 truncate text-[10px] leading-4 text-slate-500">
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

function IconActionButton({
  onClick,
  disabled,
  title,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  title: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-[10px] border transition-colors",
        disabled
          ? "cursor-not-allowed border-[var(--shell-border)] bg-[rgba(247,249,245,0.92)] text-slate-400"
          : "border-[var(--shell-border)] bg-white/85 text-slate-600 hover:bg-[var(--panel-soft)] hover:text-slate-800"
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
        "inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em]",
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

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[rgba(211,219,210,0.92)] bg-[rgba(251,252,248,0.78)] px-2.5 py-3 text-[11px] leading-5 text-slate-500">
      {children}
    </div>
  );
}

function getSourceItemTone(tone: SourceInspectorTone) {
  if (tone === "supported") {
    return {
      badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
      icon: "bg-emerald-50 text-emerald-700",
      surface:
        "border-[rgba(16,185,129,0.14)] bg-[linear-gradient(180deg,rgba(244,251,247,0.98),rgba(237,249,241,0.96))]",
    };
  }

  if (tone === "mixed") {
    return {
      badge: "border-amber-200 bg-amber-50 text-amber-700",
      icon: "bg-amber-50 text-amber-700",
      surface:
        "border-[rgba(245,158,11,0.14)] bg-[linear-gradient(180deg,rgba(255,251,235,0.96),rgba(254,243,199,0.74))]",
    };
  }

  if (tone === "insufficient") {
    return {
      badge: "border-rose-200 bg-rose-50 text-rose-700",
      icon: "bg-rose-50 text-rose-700",
      surface:
        "border-[rgba(244,63,94,0.12)] bg-[linear-gradient(180deg,rgba(255,244,246,0.96),rgba(255,228,230,0.76))]",
    };
  }

  if (tone === "retrieved") {
    return {
      badge: "border-sky-200 bg-sky-50 text-sky-700",
      icon: "bg-sky-50 text-sky-700",
      surface:
        "border-[rgba(14,165,233,0.12)] bg-[linear-gradient(180deg,rgba(240,249,255,0.96),rgba(224,242,254,0.74))]",
    };
  }

  if (tone === "warning") {
    return {
      badge: "border-orange-200 bg-orange-50 text-orange-700",
      icon: "bg-orange-50 text-orange-700",
      surface:
        "border-[rgba(249,115,22,0.12)] bg-[linear-gradient(180deg,rgba(255,247,237,0.96),rgba(255,237,213,0.78))]",
    };
  }

  return {
    badge: "border-slate-200 bg-slate-100 text-slate-600",
    icon: "bg-slate-100 text-slate-600",
    surface:
      "border-[rgba(148,163,184,0.14)] bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(241,245,249,0.82))]",
  };
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

function SourceRecordRow({
  item,
  onInspect,
}: {
  item: SourceInspectorItem;
  onInspect: (path: string) => void;
}) {
  const tone = getSourceItemTone(item.tone);
  const Icon =
    item.kind === "review"
      ? BookOpen
      : item.kind === "retrieval"
        ? Search
        : FileText;

  return (
    <div
      className={cn(
        "rounded-[12px] border px-2.5 py-2 shadow-[0_1px_1px_rgba(32,43,35,0.02)]",
        tone.surface
      )}
    >
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[9px]",
            tone.icon
          )}
        >
          <Icon size={12} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[12px] font-semibold leading-5 text-slate-700">
                {item.title}
              </p>
              <p className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
                {item.sourceType}
              </p>
            </div>
            {item.stateLabel ? (
              <span
                className={cn(
                  "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
                  tone.badge
                )}
              >
                {item.stateLabel}
              </span>
            ) : null}
          </div>

          {item.identifier || item.metadata.length > 0 ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {item.identifier ? (
                <span className="rounded-full border border-white/80 bg-white/82 px-1.5 py-0.5 font-mono text-[9px] text-slate-500">
                  {item.identifier}
                </span>
              ) : null}
              {item.metadata.map((value) => (
                <span
                  key={`${item.id}-${value}`}
                  className="rounded-full border border-white/70 bg-white/75 px-1.5 py-0.5 text-[9px] font-medium text-slate-500"
                >
                  {value}
                </span>
              ))}
            </div>
          ) : null}

          {item.detail ? (
            <p className="mt-1 text-[11px] leading-5 text-slate-600">
              {item.detail}
            </p>
          ) : null}

          {item.path ? (
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <span className="truncate font-mono text-[9px] text-slate-400">
                {shortenPath(item.path, 4)}
              </span>
              <button
                type="button"
                onClick={() => onInspect(item.path!)}
                className="shrink-0 rounded-full border border-white/80 bg-white/82 px-2 py-0.5 text-[10px] font-medium text-slate-600 transition-colors hover:text-slate-800"
              >
                Open artifact
              </button>
            </div>
          ) : null}
        </div>
      </div>
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

function ImagePreview({
  src,
  alt,
}: {
  src: string;
  alt: string;
}) {
  return (
    <div className="overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)] p-2">
      <Image
        src={src}
        alt={alt}
        width={1600}
        height={900}
        unoptimized
        className="max-h-[360px] h-auto w-full rounded-[10px] object-contain"
      />
    </div>
  );
}

function FramePreview({
  src,
  title,
}: {
  src: string;
  title: string;
}) {
  return (
    <div className="overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.8)] bg-[rgba(248,250,246,0.96)]">
      <iframe
        src={src}
        title={title}
        className="h-[360px] w-full bg-white"
      />
    </div>
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
    currentSessionId,
    sessions,
    messages,
    isStreaming,
    ragMode,
    inspectorTab,
    inspectorPreviewPath,
    setInspectorTab,
    openInspectorPath,
    clearInspectorPath,
    primeDraftMessage,
  } = useApp();

  const [skills, setSkills] = useState<SkillRegistryEntry[]>([]);
  const [tokens, setTokens] = useState<TokenStats | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [memoryContent, setMemoryContent] = useState("");
  const [savedMemoryContent, setSavedMemoryContent] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memorySaving, setMemorySaving] = useState(false);
  const [memorySaveMsg, setMemorySaveMsg] = useState("");
  const [memoryActionMsg, setMemoryActionMsg] = useState("");
  const [memoryItemDraft, setMemoryItemDraft] = useState<MemoryItemDraft | null>(null);
  const [memoryFileOpen, setMemoryFileOpen] = useState(false);
  const [memoryEditorOpen, setMemoryEditorOpen] = useState(false);
  const [skillContent, setSkillContent] = useState("");
  const [savedSkillContent, setSavedSkillContent] = useState("");
  const [selectedSkillPath, setSelectedSkillPath] = useState<string | null>(null);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillSaving, setSkillSaving] = useState(false);
  const [skillSaveMsg, setSkillSaveMsg] = useState("");
  const [skillActionMsg, setSkillActionMsg] = useState("");
  const [skillEditorOpen, setSkillEditorOpen] = useState(false);
  const [previewContent, setPreviewContent] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [sourceArtifactMetadata, setSourceArtifactMetadata] = useState<
    Record<string, EvidenceArtifactMetadata | null>
  >({});
  const memoryRequestIdRef = useRef(0);
  const skillsRequestIdRef = useRef(0);
  const skillFileRequestIdRef = useRef(0);
  const previewRequestIdRef = useRef(0);
  const sourceMetadataRequestIdRef = useRef(0);
  const hasLoadedMemoryRef = useRef(false);
  const hasLoadedSkillsRef = useRef(false);

  const isMemoryDirty = memoryContent !== savedMemoryContent;
  const isSkillDirty = skillContent !== savedSkillContent;
  const activeSession =
    sessions.find((session) => session.id === currentSessionId) ?? null;
  const parsedMemoryDocument = parseMemoryDocument(memoryContent);
  const memoryItems = parsedMemoryDocument.items;
  const memoryNamespaces = uniqueStrings([
    ...memoryItems.map((item) => item.namespace),
    memoryItemDraft?.namespace ?? null,
  ]);
  const workflowSummary = getWorkflowSummary(messages);
  const hasActiveRun = workflowSummary.events.length > 0;
  const artifactItems = collectArtifacts(workflowSummary.events);
  const sourceInspectorData = collectSourceInspectorData(messages, workflowSummary);
  const reviewedSourceItems = sourceInspectorData.reviewedItems.map((item) =>
    item.path
      ? mergeSourceItemWithMetadata(item, sourceArtifactMetadata[item.path])
      : item
  );
  const retrievedSourceItems = sourceInspectorData.retrievedItems;
  const scopedSourceMessageCount = sourceInspectorData.scopedMessages.length;
  const runStatusLabel = getRunStatusLabel(workflowSummary);
  const stepCountLabel = getStepCountLabel(workflowSummary);
  const progressLabel = getProgressLabel(workflowSummary);
  const runDetail = getRunDetail(workflowSummary);
  const previewMode = inspectorPreviewPath
    ? getInspectorPreviewMode(inspectorPreviewPath)
    : null;
  const previewRawUrl = inspectorPreviewPath
    ? getRawFileUrl(inspectorPreviewPath)
    : null;
  const selectedSkill =
    skills.find((skill) => skill.location === selectedSkillPath) ?? null;
  const activeSkills = skills.filter((skill) => skill.enabled);
  const availableSkills = skills.filter((skill) => !skill.enabled);
  const trackedTotalTokens = tokens?.tracked_total_tokens ?? tokens?.total_tokens ?? 0;
  const promptContextTokens = tokens?.total_tokens ?? 0;
  const contextWindowRatio =
    tokens?.context_window_tokens && tokens.context_window_tokens > 0
      ? Math.min(promptContextTokens / tokens.context_window_tokens, 1)
      : null;
  const contextWindowLabel = tokens?.context_window_tokens
    ? `${formatCompactTokenValue(promptContextTokens)} / ${formatCompactTokenValue(tokens.context_window_tokens)}`
    : "Unavailable";

  useEffect(() => {
    if (!currentSessionId) {
      setTokens(null);
      setUsageLoading(false);
      return;
    }

    if (isStreaming) {
      setUsageLoading(false);
      return;
    }

    let cancelled = false;
    setUsageLoading(true);

    getSessionTokens(currentSessionId)
      .then((nextTokens) => {
        if (!cancelled) {
          setTokens(nextTokens);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setTokens(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setUsageLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [currentSessionId, isStreaming]);

  useEffect(() => {
    setMemoryFileOpen(false);
    setMemoryEditorOpen(false);
    setSkillEditorOpen(false);

    if (inspectorTab === "memory") {
      setMemorySaveMsg("");
      setMemoryActionMsg("");
      if (!hasLoadedMemoryRef.current) {
        void loadMemory();
      }
    }

    if (inspectorTab === "skills") {
      setSkillSaveMsg("");
      setSkillActionMsg("");
      if (!hasLoadedSkillsRef.current) {
        void refreshSkills();
      }
    }
  }, [inspectorTab]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const confirmDiscardChanges = (
    scopeLabel: "memory" | "skill",
    targetLabel: string
  ) => {
    if (typeof window === "undefined") {
      return false;
    }

    return window.confirm(
      `Discard unsaved ${scopeLabel} edits and load ${targetLabel} from disk?`
    );
  };

  const canReloadMemory = () =>
    !isMemoryDirty || confirmDiscardChanges("memory", MEMORY_PATH);

  const canReloadSkill = (targetPath?: string | null) =>
    !isSkillDirty ||
    confirmDiscardChanges(
      "skill",
      targetPath ? shortenPath(targetPath, 3) : "the selected skill file"
    );

  const loadMemory = async () => {
    const requestId = memoryRequestIdRef.current + 1;
    memoryRequestIdRef.current = requestId;
    setMemoryLoading(true);

    try {
      const res = await readFile(MEMORY_PATH);
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent(res.content);
      setSavedMemoryContent(res.content);
      hasLoadedMemoryRef.current = true;
    } catch {
      if (memoryRequestIdRef.current !== requestId) return;

      setMemoryContent("# Could not load MEMORY.md");
      setSavedMemoryContent("# Could not load MEMORY.md");
      hasLoadedMemoryRef.current = true;
    } finally {
      if (memoryRequestIdRef.current === requestId) {
        setMemoryLoading(false);
      }
    }
  };

  const refreshSkills = async (preferredPath?: string) => {
    const requestId = skillsRequestIdRef.current + 1;
    skillsRequestIdRef.current = requestId;
    setSkillsLoading(true);

    try {
      const nextSkills = await listSkillsRegistry();
      if (skillsRequestIdRef.current !== requestId) return;

      setSkills(nextSkills);
      hasLoadedSkillsRef.current = true;

      if (nextSkills.length === 0) {
        setSelectedSkillPath(null);
        setSkillContent("");
        setSavedSkillContent("");
        return nextSkills;
      }

      const nextPath =
        preferredPath ??
        (selectedSkillPath &&
        nextSkills.some((skill) => skill.location === selectedSkillPath)
          ? selectedSkillPath
          : null);

      if (!nextPath) {
        setSelectedSkillPath(null);
        setSkillContent("");
        setSavedSkillContent("");
        return nextSkills;
      }

      if (!nextSkills.some((skill) => skill.location === nextPath)) {
        setSelectedSkillPath(null);
        setSkillContent("");
        setSavedSkillContent("");
        setSkillEditorOpen(false);
      }

      return nextSkills;
    } catch {
      if (skillsRequestIdRef.current !== requestId) return;

      hasLoadedSkillsRef.current = true;
      if (skills.length === 0) {
        setSkillContent("# Could not load skill registry");
        setSavedSkillContent("# Could not load skill registry");
      }
      return null;
    } finally {
      if (skillsRequestIdRef.current === requestId) {
        setSkillsLoading(false);
      }
    }
  };

  const loadSkillFile = async (path: string) => {
    const requestId = skillFileRequestIdRef.current + 1;
    skillFileRequestIdRef.current = requestId;
    setSkillsLoading(true);
    setSelectedSkillPath(path);

    try {
      const res = await readFile(path);
      if (skillFileRequestIdRef.current !== requestId) return;

      setSkillContent(res.content);
      setSavedSkillContent(res.content);
    } catch {
      if (skillFileRequestIdRef.current !== requestId) return;

      setSkillContent("# Could not load skill file");
      setSavedSkillContent("# Could not load skill file");
    } finally {
      if (skillFileRequestIdRef.current === requestId) {
        setSkillsLoading(false);
      }
    }
  };

  const loadPreview = async (path: string) => {
    const requestId = previewRequestIdRef.current + 1;
    previewRequestIdRef.current = requestId;
    setPreviewContent("");
    setPreviewError("");

    if (getInspectorPreviewMode(path) !== "text") {
      setPreviewLoading(false);
      return;
    }

    setPreviewLoading(true);

    try {
      const res = await readFile(path);
      if (previewRequestIdRef.current !== requestId) return;

      setPreviewContent(res.content);
    } catch {
      if (previewRequestIdRef.current !== requestId) return;

      setPreviewError(
        "Could not load file preview. Use Open raw to inspect the artifact."
      );
    } finally {
      if (previewRequestIdRef.current === requestId) {
        setPreviewLoading(false);
      }
    }
  };

  useEffect(() => {
    if (!inspectorPreviewPath) {
      setPreviewContent("");
      setPreviewError("");
      setPreviewLoading(false);
      return;
    }

    void loadPreview(inspectorPreviewPath);
  }, [inspectorPreviewPath]);

  const openPreviewRawFile = () => {
    if (!previewRawUrl || typeof window === "undefined") {
      return;
    }

    window.open(previewRawUrl, "_blank", "noopener,noreferrer");
  };

  const openRawFile = (path: string) => {
    if (typeof window === "undefined") {
      return;
    }

    window.open(getRawFileUrl(path), "_blank", "noopener,noreferrer");
  };

  const inspectPathInFiles = (path: string) => {
    openInspectorPath(path);
    setInspectorTab("files");
  };

  const flashMemoryAction = (message: string) => {
    setMemoryActionMsg(message);
    window.setTimeout(() => setMemoryActionMsg(""), 2000);
  };

  const flashSkillAction = (message: string) => {
    setSkillActionMsg(message);
    window.setTimeout(() => setSkillActionMsg(""), 2000);
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

  const handleSkillsRefresh = async () => {
    if (!canReloadSkill(selectedSkillPath)) {
      return;
    }

    const keepSelectedPath = selectedSkillPath;
    const nextSkills = await refreshSkills(keepSelectedPath ?? undefined);

    if (
      keepSelectedPath &&
      nextSkills?.some((skill) => skill.location === keepSelectedPath)
    ) {
      await loadSkillFile(keepSelectedPath);
    }
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

  const handleMemoryItemCopy = async (item: MemoryInspectorItem) => {
    if (typeof navigator === "undefined" || !navigator.clipboard) {
      flashMemoryAction("Clipboard unavailable");
      return;
    }

    const copyValue = item.value
      ? `${item.namespace}/${item.key}\n${item.value}`
      : `${item.namespace}/${item.key}`;

    try {
      await navigator.clipboard.writeText(copyValue);
      flashMemoryAction("Memory item copied");
    } catch {
      flashMemoryAction("Copy failed");
    }
  };

  const handleSkillSave = async () => {
    if (!selectedSkillPath || !isSkillDirty) return;

    setSkillSaving(true);
    setSkillSaveMsg("");

    try {
      await saveFile(selectedSkillPath, skillContent);
      setSavedSkillContent(skillContent);
      setSkillSaveMsg("Saved");
      setTimeout(() => setSkillSaveMsg(""), 2000);
    } catch {
      setSkillSaveMsg("Save failed");
    } finally {
      setSkillSaving(false);
    }
  };

  const handleSkillInstall = () => {
    primeDraftMessage(
      "Use the skill-installer skill to install a new skill into this BioAPEX workspace."
    );
    flashSkillAction("Install request drafted in the composer");
  };

  const handleSkillSelection = async (path: string) => {
    if (path === selectedSkillPath && skillContent) {
      return;
    }

    if (!canReloadSkill(path)) {
      return;
    }

    setSkillSaveMsg("");
    setSkillEditorOpen(false);
    await loadSkillFile(path);
  };

  const handleSelectedSkillRefresh = async () => {
    if (!selectedSkillPath || !canReloadSkill(selectedSkillPath)) {
      return;
    }

    await loadSkillFile(selectedSkillPath);
  };

  const clearSelectedSkill = () => {
    if (selectedSkillPath && !canReloadSkill(selectedSkillPath)) {
      return;
    }

    setSelectedSkillPath(null);
    setSkillContent("");
    setSavedSkillContent("");
    setSkillEditorOpen(false);
  };

  const renderFilesTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Active Run"
        meta={workflowSummary.workflowId ?? (hasActiveRun ? "Current workflow run" : undefined)}
      >
        {hasActiveRun ? (
          <div
            className={cn(
              "space-y-2 rounded-[12px] border px-2.5 py-2.5",
              getRunSurfaceClass(workflowSummary)
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-[12px] font-semibold text-slate-800">
                  {workflowSummary.workflowName ?? workflowSummary.workflowId ?? "Workflow run"}
                </p>
                {progressLabel ? (
                  <p className="mt-0.5 truncate text-[10px] leading-4 text-slate-500">
                    {progressLabel}
                  </p>
                ) : null}
              </div>
              <span
                className={cn(
                  "inline-flex shrink-0 items-center rounded-full border px-2 py-1 text-[10px] font-semibold",
                  getRunStatusClass(workflowSummary)
                )}
              >
                {runStatusLabel}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-1.5">
              <MiniStat
                label="Steps"
                value={stepCountLabel}
                accent={workflowSummary.status === "running"}
              />
              <MiniStat
                label="State"
                value={runStatusLabel}
                accent={
                  workflowSummary.status === "running" ||
                  workflowSummary.status === "completed"
                }
              />
            </div>

            <p className="text-[11px] leading-5 text-slate-600">{runDetail}</p>
          </div>
        ) : (
          <EmptyState>
            Send a workflow-oriented request to populate run progress and generated files here.
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
            Generated workflow outputs will appear here once a step materializes inspectable artifacts.
          </EmptyState>
        )}
      </InspectorCard>

      {inspectorPreviewPath ? (
        <InspectorCard
          title="Preview"
          meta={shortenPath(inspectorPreviewPath, 3)}
          controls={
            <>
              {previewMode === "text" ? (
                <ActionButton onClick={() => void loadPreview(inspectorPreviewPath)}>
                  <RefreshCw size={11} />
                  Refresh
                </ActionButton>
              ) : null}
              <ActionButton onClick={openPreviewRawFile}>Open raw</ActionButton>
              <ActionButton onClick={clearInspectorPath}>Clear</ActionButton>
            </>
          }
        >
          {previewLoading ? (
            <LoadingState label="Loading preview..." />
          ) : previewMode === "image" && previewRawUrl ? (
            <ImagePreview
              src={previewRawUrl}
              alt={inspectorPreviewPath.split("/").pop() ?? "Generated artifact"}
            />
          ) : previewMode === "pdf" && previewRawUrl ? (
            <FramePreview
              src={previewRawUrl}
              title={inspectorPreviewPath.split("/").pop() ?? "Generated artifact"}
            />
          ) : previewMode === "unsupported" ? (
            <EmptyState>{getUnsupportedPreviewMessage(inspectorPreviewPath)}</EmptyState>
          ) : previewError ? (
            <EmptyState>{previewError}</EmptyState>
          ) : (
            <PreviewPane content={previewContent} />
          )}
        </InspectorCard>
      ) : null}
    </div>
  );

  const renderSourcesTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Reviewed Evidence"
        meta={`${reviewedSourceItems.length} item${reviewedSourceItems.length === 1 ? "" : "s"}`}
      >
        {reviewedSourceItems.length > 0 ? (
          <div className="space-y-1">
            {reviewedSourceItems.slice(0, 8).map((item) => (
              <SourceRecordRow
                key={item.id}
                item={item}
                onInspect={openInspectorPath}
              />
            ))}
          </div>
        ) : (
          <EmptyState>
            No reviewed evidence or attached source cards are linked to the current turn or workflow run yet. Evidence retrieval, evidence review, or source-backed workflows will populate this view.
          </EmptyState>
        )}
      </InspectorCard>

      <InspectorCard
        title="Retrieved Context"
        meta={`${retrievedSourceItems.length} source${retrievedSourceItems.length === 1 ? "" : "s"}`}
      >
        {retrievedSourceItems.length > 0 ? (
          <div className="space-y-1">
            {retrievedSourceItems.slice(0, 8).map((source) => (
              <SourceRecordRow
                key={source.source}
                item={{
                  id: source.source,
                  kind: "retrieval",
                  artifactType: null,
                  title: source.source,
                  sourceType: "Retrieved context",
                  identifier: source.identifier,
                  stateLabel: null,
                  detail: `${pluralize(source.count, "hit")} attached to the latest turn.`,
                  metadata: [`Top score ${source.score.toFixed(3)}`],
                  tone: "retrieved",
                  path: null,
                  lastSeenOrder: source.lastSeenOrder,
                }}
                onInspect={openInspectorPath}
              />
            ))}
          </div>
        ) : (
          <EmptyState>
            No retrieved context is attached to the current turn or workflow run. Retrieval remains visible in the center trace when RAG-backed context is used.
          </EmptyState>
        )}
      </InspectorCard>

      <InspectorCard title="Sources Context" meta={ragMode ? "RAG on" : "RAG off"}>
        <div className="space-y-1 text-[11px] text-slate-600">
          <p>
            {scopedSourceMessageCount > 0
              ? `Showing evidence and sources from the current request or workflow run (${pluralize(scopedSourceMessageCount, "message")}).`
              : "No current turn or workflow run has attached evidence or retrieval context yet."}
          </p>
          <p>
            {ragMode
              ? "Retrieved context stays separate from reviewed evidence so source inspection remains concrete and reviewable."
              : "RAG is currently disabled, so only explicit evidence artifacts or review outputs will appear here."}
          </p>
          {workflowSummary.workflowId ? (
            <p>Latest workflow context: {workflowSummary.workflowId}</p>
          ) : null}
        </div>
      </InspectorCard>
    </div>
  );

  const renderMemoryTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Context Memory"
        meta={MEMORY_PATH}
        controls={
          <>
            <ActionButton onClick={() => void handleMemoryRefresh()}>
              <RefreshCw size={11} />
              Refresh
            </ActionButton>
            <ActionButton
              onClick={() => {
                setMemoryFileOpen((value) => !value);
                setMemoryEditorOpen(false);
              }}
            >
              <Brain size={11} />
              {memoryFileOpen ? "Hide file" : "Raw file"}
            </ActionButton>
          </>
        }
      >
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <MetaBadge tone={isMemoryDirty ? "warning" : "success"}>
                {isMemoryDirty ? "Unsaved edits" : "File synced"}
              </MetaBadge>
              <MetaBadge>{pluralize(memoryItems.length, "item")}</MetaBadge>
              {memorySaveMsg ? (
                <MetaBadge tone={memorySaveMsg === "Saved" ? "success" : "warning"}>
                  {memorySaveMsg}
                </MetaBadge>
              ) : null}
              {memoryActionMsg ? (
                <MetaBadge tone="accent">{memoryActionMsg}</MetaBadge>
              ) : null}
            </div>
            <PrimaryActionButton
              onClick={() => void handleMemorySave()}
              disabled={!isMemoryDirty || memorySaving}
            >
              <Save size={11} />
              {memorySaving ? "Saving…" : "Save"}
            </PrimaryActionButton>
          </div>

          <p className="text-[10px] leading-4 text-slate-500">
            Structured memory items stay synced to `memory/MEMORY.md`, and the raw
            markdown file remains available when exact formatting matters.
          </p>

          {memoryLoading ? (
            <LoadingState label="Loading memory..." />
          ) : (
            <>
              {memoryItemDraft ? (
                <div className="rounded-[12px] border border-[rgba(35,130,83,0.16)] bg-white px-2.5 py-2.5 shadow-[0_1px_2px_rgba(32,43,35,0.03)]">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] font-semibold text-slate-700">
                      {memoryItemDraft.mode === "create" ? "Add memory item" : "Edit memory item"}
                    </p>
                    <MetaBadge tone="warning">Draft</MetaBadge>
                  </div>

                  <div className="mt-2 space-y-2">
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
                        className="w-full rounded-[10px] border border-[var(--shell-border)] bg-[rgba(251,252,248,0.9)] px-3 py-2 text-[12px] text-slate-700 outline-none focus:border-[var(--apex-accent)]"
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
                        className="w-full rounded-[10px] border border-[var(--shell-border)] bg-[rgba(251,252,248,0.9)] px-3 py-2 text-[12px] text-slate-700 outline-none focus:border-[var(--apex-accent)]"
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
                        className="w-full rounded-[10px] border border-[var(--shell-border)] bg-[rgba(251,252,248,0.9)] px-3 py-2 text-[12px] leading-5 text-slate-700 outline-none focus:border-[var(--apex-accent)]"
                        placeholder="BRCA1_cohort_v2"
                      />
                    </div>
                  </div>

                  <div className="mt-2 flex items-center justify-end gap-1.5">
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
                <div className="space-y-2">
                  {memoryItems.map((item) => (
                    <div
                      key={item.id}
                      className="rounded-[16px] border border-[rgba(211,219,210,0.78)] bg-[rgba(255,255,255,0.96)] px-3 py-3 shadow-[0_1px_2px_rgba(32,43,35,0.03)]"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-mono text-[11px] font-semibold text-[var(--apex-accent-strong)]">
                            {item.namespace}/{item.key}
                          </p>
                          <p className="mt-2 text-[14px] font-medium leading-6 text-slate-700">
                            {item.value || item.key}
                          </p>
                        </div>
                        <MetaBadge tone="success">Active</MetaBadge>
                      </div>

                      <div className="mt-3 flex items-center gap-2">
                        <IconActionButton
                          onClick={() => startMemoryItemDraft(item)}
                          title="Edit memory item"
                        >
                          <Pencil size={14} />
                        </IconActionButton>
                        <IconActionButton
                          onClick={() => void handleMemoryItemCopy(item)}
                          title="Copy memory item"
                        >
                          <Copy size={14} />
                        </IconActionButton>
                        <IconActionButton
                          onClick={() => handleMemoryItemDelete(item.id)}
                          title="Delete memory item"
                        >
                          <Trash2 size={14} />
                        </IconActionButton>
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
                <div className="rounded-[14px] border border-[rgba(211,219,210,0.82)] bg-[rgba(251,252,248,0.92)] px-2.5 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                        Underlying File
                      </p>
                      <p className="mt-0.5 truncate text-[10px] leading-4 text-slate-500">
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
      </InspectorCard>
    </div>
  );

  const renderSkillsTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Active"
        meta={`${activeSkills.length} enabled`}
        controls={
          <ActionButton onClick={() => void handleSkillsRefresh()}>
            <RefreshCw size={11} />
            Refresh
          </ActionButton>
        }
      >
        <div className="space-y-3">
          {skillsLoading && skills.length === 0 ? (
            <LoadingState label="Loading skills..." />
          ) : activeSkills.length > 0 ? (
            <div className="space-y-1.5">
              {activeSkills.map((skill) => (
                <button
                  key={skill.location}
                  type="button"
                  onClick={() => void handleSkillSelection(skill.location)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-[12px] border px-2.5 py-2 text-left transition-colors",
                    skill.location === selectedSkillPath
                      ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)]"
                      : "border-transparent bg-[rgba(251,252,248,0.94)] hover:border-[rgba(211,219,210,0.86)] hover:bg-white"
                  )}
                >
                  <span
                    className={cn(
                      "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[9px]",
                      skill.location === selectedSkillPath
                        ? "bg-[rgba(35,130,83,0.12)] text-[var(--apex-accent-strong)]"
                        : "bg-white text-[var(--apex-accent-strong)]"
                    )}
                  >
                    <Sparkles size={13} />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-700">
                    {skill.name}
                  </span>
                  <span className="flex-shrink-0 text-[11px] text-slate-500">
                    {getSkillVersionLabel(skill)}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState>
              No active skills are currently available. Refresh this view once the
              backend skill scan finishes.
            </EmptyState>
          )}

          <div className="border-t border-[rgba(211,219,210,0.72)] pt-2">
            <p className="text-[11px] font-semibold text-slate-500">Available Skills</p>
            <p className="mt-1 text-[11px] leading-5 text-slate-400">
              Add more analysis tools, data processors, or custom workflows to
              expand capabilities.
            </p>

            <div className="mt-2">
              <WideActionButton onClick={handleSkillInstall}>
                <Plus size={13} />
                Install Skill
              </WideActionButton>
            </div>

            {skillActionMsg ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                <MetaBadge tone="accent">{skillActionMsg}</MetaBadge>
              </div>
            ) : null}

            {availableSkills.length > 0 ? (
              <div className="mt-2 space-y-1.5">
                {availableSkills.map((skill) => (
                  <button
                    key={skill.location}
                    type="button"
                    onClick={() => void handleSkillSelection(skill.location)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-[12px] border px-2.5 py-2 text-left transition-colors",
                      skill.location === selectedSkillPath
                        ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)]"
                        : "border-transparent bg-[rgba(251,252,248,0.94)] hover:border-[rgba(211,219,210,0.86)] hover:bg-white"
                    )}
                  >
                    <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[9px] bg-white text-slate-500">
                      <Package size={13} />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-700">
                      {skill.name}
                    </span>
                    <span className="flex-shrink-0 text-[11px] text-slate-500">
                      {getSkillVersionLabel(skill)}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </InspectorCard>

      {selectedSkillPath ? (
        <InspectorCard
          title={selectedSkill?.name ?? "Skill File"}
          meta={shortenPath(selectedSkillPath, 3)}
          controls={
            <>
              <ActionButton onClick={() => void handleSelectedSkillRefresh()}>
                <RefreshCw size={11} />
                Refresh
              </ActionButton>
              <ActionButton onClick={() => setSkillEditorOpen((value) => !value)}>
                <BookOpen size={11} />
                {skillEditorOpen ? "Preview" : "Edit"}
              </ActionButton>
              <ActionButton onClick={clearSelectedSkill}>Hide</ActionButton>
            </>
          }
        >
          {selectedSkill ? (
            <div className="mb-2 rounded-[12px] border border-[rgba(211,219,210,0.82)] bg-[rgba(251,252,248,0.92)] px-2.5 py-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[12px] font-semibold text-slate-700">
                    {selectedSkill.name}
                  </p>
                  <p className="mt-1 text-[10px] leading-4 text-slate-500">
                    {selectedSkill.description || "Local skill definition file."}
                  </p>
                </div>
                <MetaBadge tone={selectedSkill.enabled ? "success" : "neutral"}>
                  {getSkillVersionLabel(selectedSkill)}
                </MetaBadge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {getSkillMetadata(selectedSkill).map((value) => (
                  <MetaBadge key={`${selectedSkill.location}-${value}`}>{value}</MetaBadge>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              {skillSaveMsg ? (
                <MetaBadge tone={skillSaveMsg === "Saved" ? "success" : "warning"}>
                  {skillSaveMsg}
                </MetaBadge>
              ) : null}
              <MetaBadge tone={isSkillDirty ? "warning" : "neutral"}>
                {isSkillDirty ? "Unsaved edits" : "File synced"}
              </MetaBadge>
            </div>
            <button
              type="button"
              onClick={() => void handleSkillSave()}
              disabled={!isSkillDirty || skillSaving}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
                isSkillDirty && !skillSaving
                  ? "bg-[var(--apex-accent)] text-white hover:bg-[var(--apex-accent-strong)]"
                  : "cursor-not-allowed bg-slate-200 text-slate-400"
              )}
            >
              <Save size={11} />
              {skillSaving ? "Saving…" : "Save"}
            </button>
          </div>

          {skillsLoading ? (
            <LoadingState label="Loading skill..." />
          ) : skillEditorOpen ? (
            <div className="h-[220px] overflow-hidden rounded-[12px] border border-[rgba(211,219,210,0.86)] bg-white">
              <MonacoEditor
                height="100%"
                language="markdown"
                value={skillContent}
                theme="vs"
                onChange={(value) => setSkillContent(value ?? "")}
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
            <PreviewPane content={skillContent} className="max-h-[220px]" />
          )}

          <div className="mt-2 flex flex-wrap gap-1.5">
            <ActionButton onClick={() => openRawFile(selectedSkillPath)}>
              Open raw
            </ActionButton>
            <ActionButton onClick={() => inspectPathInFiles(selectedSkillPath)}>
              Inspect
            </ActionButton>
          </div>
        </InspectorCard>
      ) : null}
    </div>
  );

  const renderUsageTab = () => (
    <div className="space-y-2">
      <InspectorCard
        title="Usage"
        meta={activeSession ? activeSession.title : currentSessionId ?? "No session"}
      >
        {usageLoading && !tokens ? (
          <LoadingState label="Loading usage..." />
        ) : tokens ? (
          <div className="space-y-3">
            <div className="text-center">
              <p className="text-[38px] font-semibold tracking-[-0.05em] text-slate-800">
                {trackedTotalTokens.toLocaleString()}
              </p>
              <p className="text-[11px] text-slate-400">Total tokens</p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2 text-[12px] text-slate-500">
                <span>Input</span>
                <span className="font-medium text-slate-700">
                  {tokens.input_tokens.toLocaleString()}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[12px] text-slate-500">
                <span>Output</span>
                <span className="font-medium text-slate-700">
                  {tokens.output_tokens.toLocaleString()}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[12px] text-slate-500">
                <span>Tools</span>
                <span className="font-medium text-slate-700">
                  {tokens.tool_tokens.toLocaleString()}
                </span>
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2 text-[12px] text-slate-500">
                <span>Context</span>
                <span className="font-medium text-slate-700">{contextWindowLabel}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[rgba(211,219,210,0.76)]">
                <div
                  className="h-full rounded-full bg-[linear-gradient(90deg,var(--apex-accent),rgba(35,130,83,0.55))]"
                  style={{ width: `${(contextWindowRatio ?? 0) * 100}%` }}
                />
              </div>
              <p className="text-[10px] leading-4 text-slate-500">
                Prompt/context pressure is calculated from the actual model history in
                play, while tool I/O stays tracked separately above.
              </p>
            </div>

            <div className="border-t border-[rgba(211,219,210,0.72)] pt-2">
              <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                <span>Provenance</span>
              </div>
              <div className="mt-2 space-y-1.5 text-[12px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-400">Session</span>
                  <span className="font-mono text-[11px] text-slate-700">
                    {shortIdentifier(tokens.session_id)}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-400">Model</span>
                  <span className="font-mono text-[11px] text-slate-700">
                    {tokens.model_name}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-400">Mode</span>
                  <span className="text-[11px] font-medium text-slate-700">
                    {ragMode ? "Grounded" : "Chat"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState>Token usage will appear once a session is selected.</EmptyState>
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
              onClick={() => setInspectorTab(tab.id)}
            />
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {inspectorTab === "files" && renderFilesTab()}
        {inspectorTab === "sources" && renderSourcesTab()}
        {inspectorTab === "memory" && renderMemoryTab()}
        {inspectorTab === "skills" && renderSkillsTab()}
        {inspectorTab === "usage" && renderUsageTab()}
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
