"use client";

import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { useEffect, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  ExternalLink,
  FileText,
  Files,
  FlaskConical,
  FolderOpen,
  MessageSquare,
  Package,
  Plus,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import {
  DEFAULT_ARTIFACT_REGISTRY_FILTERS,
  artifactRegistryHasActiveFilters,
  getArtifactRegistryDescription,
  getArtifactRegistryDisplayName,
  getArtifactRegistryMetadataSummary,
  getArtifactRegistryPreviewMode,
  getArtifactRegistryRunRecordPath,
  getArtifactRegistryTimestamp,
  humanizeArtifactToken,
  isArtifactRegistryTextPreviewable,
  normalizeArtifactRegistryQuery,
  shortenArtifactPath,
  sortArtifactRegistryRecords,
  type ArtifactRegistryFilterState,
} from "@/lib/artifact-registry";
import {
  getWorkflowSummary,
} from "@/lib/session-status";
import { useApp } from "@/lib/store";
import {
  createRawFileObjectUrl,
  getFilesWorkspaceSummary,
  getFlowsWorkspaceSummary,
  listArtifactRegistry,
  openRawFileInNewTab,
  readFile,
} from "@/lib/api";
import type {
  ArtifactRegistryLookupResult,
  ArtifactRegistryRecord,
  FilesWorkspaceItem,
  FlowsWorkspaceStatus,
  FlowsWorkspaceSummaryItem,
} from "@/lib/types";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  describeWorkflow,
  flowsWorkspaceDefinitions,
  flowsWorkspaceSummaryMap,
  getQuickStartItem,
  parseWorkspaceDocument,
  type ParsedWorkspaceDocument,
  summarizeFlowsWorkspaceStatus,
  workspaceDocs,
  type WorkspaceDocument,
} from "./workspace-data";

type PreviewStatus = "idle" | "loading" | "ready" | "error";
type DocsWorkspaceStatus = "loading" | "ready" | "error";
type FilesWorkspaceStatus = "idle" | "loading" | "ready" | "error";
type ArtifactRegistryWorkspaceStatus = "loading" | "ready" | "error";

const EMPTY_ARTIFACT_REGISTRY_RECORDS: ArtifactRegistryRecord[] = [];

interface LoadedWorkspaceDocument extends WorkspaceDocument {
  parsed: ParsedWorkspaceDocument;
}

interface WorkspaceDocumentFailure extends WorkspaceDocument {
  error: string;
}

type DocsNavigatorEntry =
  | { kind: "loaded"; document: LoadedWorkspaceDocument }
  | { kind: "failed"; document: WorkspaceDocumentFailure };

function usePreviewContent(path: string | null) {
  const [status, setStatus] = useState<PreviewStatus>("idle");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    if (!path) {
      setStatus("idle");
      setContent("");
      setError(null);
      return () => {
        active = false;
      };
    }

    setStatus("loading");
    setContent("");
    setError(null);

    void readFile(path)
      .then((response) => {
        if (!active) return;
        setContent(response.content);
        setStatus("ready");
      })
      .catch((previewError) => {
        if (!active) return;
        setStatus("error");
        setError(
          previewError instanceof Error
            ? previewError.message
            : "Unable to load that file preview right now."
        );
      });

    return () => {
      active = false;
    };
  }, [path]);

  return { status, content, error };
}

function useRawPreviewObjectUrl(path: string | null, enabled: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    let revoke: (() => void) | null = null;

    if (!path || !enabled) {
      setUrl(null);
      setError(null);
      setLoading(false);
      return () => {
        active = false;
      };
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setUrl(null);

    void createRawFileObjectUrl(path, controller.signal)
      .then((result) => {
        if (!active) {
          result.revoke();
          return;
        }

        revoke = result.revoke;
        setUrl(result.url);
      })
      .catch(() => {
        if (!active) {
          return;
        }

        setError("Could not load the raw preview. Use Open Raw File to inspect it.");
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
      revoke?.();
    };
  }, [enabled, path]);

  return { url, error, loading };
}

function previewText(content: string): string {
  const lines = content.split("\n");
  const clipped = lines.slice(0, 80).join("\n");
  return lines.length > 80 ? `${clipped}\n…` : clipped;
}

function humanizeToken(value?: string | null): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function getFileExtension(path: string): string {
  const fileName = path.split("/").pop() ?? path;
  const lastDot = fileName.lastIndexOf(".");
  if (lastDot === -1) {
    return "";
  }
  return fileName.slice(lastDot).toLowerCase();
}

function formatByteSize(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value) || value < 0) {
    return "Unknown size";
  }

  if (value < 1024) {
    return `${value} B`;
  }

  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  const precision = size >= 10 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}

type FilesWorkspaceKind =
  | "table"
  | "plot"
  | "structured"
  | "report"
  | "archive"
  | "file";

function inferFilesWorkspaceKind(item: FilesWorkspaceItem): FilesWorkspaceKind {
  const extension = getFileExtension(item.path);
  const artifactType = item.artifact_type?.toLowerCase() ?? "";
  const outputName = item.output_name?.toLowerCase() ?? "";
  const name = item.name.toLowerCase();

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
    name.includes("matrix")
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
    extension === ".html" ||
    extension === ".pdf" ||
    extension === ".md" ||
    artifactType.includes("report")
  ) {
    return "report";
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

function filesWorkspaceKindLabel(item: FilesWorkspaceItem): string {
  const extension = getFileExtension(item.path);

  if (extension === ".csv") return "CSV";
  if (extension === ".tsv") return "TSV";
  if (extension === ".json") return "JSON";
  if (extension === ".yaml" || extension === ".yml") return "YAML";
  if (extension === ".html") return "HTML";
  if (extension === ".pdf") return "PDF";
  if (
    extension === ".png" ||
    extension === ".jpg" ||
    extension === ".jpeg" ||
    extension === ".svg"
  ) {
    return "Image";
  }

  const kind = inferFilesWorkspaceKind(item);
  if (kind === "table") return "Table";
  if (kind === "plot") return "Plot";
  if (kind === "structured") return "Data";
  if (kind === "report") return "Report";
  if (kind === "archive") return "Archive";
  return "File";
}

function filesWorkspaceKindTone(item: FilesWorkspaceItem): string {
  const kind = inferFilesWorkspaceKind(item);
  if (kind === "table") {
    return "border-[rgba(217,119,6,0.18)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }
  if (kind === "plot") {
    return "border-[rgba(225,29,72,0.16)] bg-[rgba(255,241,242,0.95)] text-rose-700";
  }
  if (kind === "structured") {
    return "border-[rgba(2,132,199,0.16)] bg-[rgba(240,249,255,0.95)] text-sky-700";
  }
  if (kind === "report") {
    return "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]";
  }
  if (kind === "archive") {
    return "border-[rgba(148,163,184,0.22)] bg-[rgba(241,245,249,0.92)] text-slate-600";
  }
  return "border-[rgba(168,162,158,0.2)] bg-[rgba(250,250,249,0.94)] text-stone-700";
}

function describeFilesWorkspaceItem(item: FilesWorkspaceItem): string {
  const detailParts = [
    humanizeToken(item.output_name),
    humanizeToken(item.artifact_type),
    humanizeToken(item.step_label),
    humanizeToken(item.source_tool),
  ].filter((value): value is string => Boolean(value));

  const uniqueDetailParts = detailParts.filter(
    (value, index) => detailParts.indexOf(value) === index
  );

  return uniqueDetailParts[0] ?? "Durable generated artifact";
}

function shortRunLabel(runId?: string | null): string {
  if (!runId) {
    return "No run label";
  }
  if (runId.length <= 24) {
    return runId;
  }
  return `${runId.slice(0, 18)}…${runId.slice(-5)}`;
}

type FilesWorkspacePreviewMode = "text" | "image" | "pdf" | "unsupported";

function getFilesWorkspacePreviewMode(
  item: FilesWorkspaceItem
): FilesWorkspacePreviewMode {
  const extension = getFileExtension(item.path);

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

function isTextPreviewable(item: FilesWorkspaceItem): boolean {
  return getFilesWorkspacePreviewMode(item) === "text";
}

function WorkspaceBadge({
  icon: Icon,
  children,
}: {
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(35,130,83,0.16)] bg-[rgba(35,130,83,0.08)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
      <Icon size={12} />
      <span>{children}</span>
    </span>
  );
}

function WorkspaceAction({
  children,
  onClick,
  tone = "default",
}: {
  children: ReactNode;
  onClick: () => void;
  tone?: "default" | "accent";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-medium transition-colors",
        tone === "accent"
          ? "border-[rgba(35,130,83,0.18)] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)] hover:bg-[rgba(35,130,83,0.16)]"
          : "border-[var(--shell-border)] bg-white/90 text-slate-600 hover:bg-[var(--panel-soft)] hover:text-slate-800"
      )}
    >
      {children}
    </button>
  );
}

function WorkspaceShell({
  children,
  mode,
}: {
  children: ReactNode;
  mode: "flows" | "docs" | "files" | "artifacts";
}) {
  const backgroundClass =
    mode === "flows"
      ? "bg-[linear-gradient(180deg,rgba(247,250,246,0.98)_0%,rgba(242,247,242,0.92)_100%)]"
      : mode === "docs"
        ? "bg-[linear-gradient(180deg,rgba(250,251,248,0.98)_0%,rgba(246,248,243,0.94)_100%)]"
        : mode === "files"
          ? "bg-[linear-gradient(180deg,rgba(248,250,247,0.98)_0%,rgba(243,246,242,0.94)_100%)]"
          : "bg-[linear-gradient(180deg,rgba(250,249,245,0.98)_0%,rgba(245,244,238,0.95)_100%)]";

  return (
    <section className="apex-panel flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] shadow-[var(--panel-shadow-soft)]">
      <div className={cn("flex min-h-0 flex-1 flex-col", backgroundClass)}>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5 lg:px-8 lg:py-7">
          <div className="mx-auto flex w-full max-w-[70rem] flex-col gap-4 pb-2 sm:gap-5">
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}

function WorkspaceHero({
  icon: Icon,
  title,
  description,
  badges,
  actions,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  badges?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="rounded-[24px] border border-[rgba(211,219,210,0.9)] bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(247,249,245,0.94))] p-4 shadow-[0_12px_32px_rgba(29,42,33,0.05)] sm:p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2">
            <div className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-[var(--apex-accent-soft)] text-[var(--apex-accent-strong)]">
              <Icon size={20} />
            </div>
            <WorkspaceBadge icon={Sparkles}>Workspace Mode</WorkspaceBadge>
          </div>
          <h2 className="mt-3 text-[1.3rem] font-semibold tracking-[-0.02em] text-slate-900">
            {title}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            {description}
          </p>
          {badges ? <div className="mt-3 flex flex-wrap gap-2">{badges}</div> : null}
        </div>

        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-[18px] border border-[rgba(211,219,210,0.9)] bg-white/92 px-4 py-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold tracking-[-0.02em] text-slate-900">
        {value}
      </p>
      <p className="mt-1 text-[12px] leading-5 text-slate-500">{detail}</p>
    </div>
  );
}

function EmptyWorkspaceState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-[22px] border border-dashed border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] px-5 py-8 text-center">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--apex-accent-strong)]">
        Workspace Ready
      </p>
      <h3 className="mt-2 text-lg font-semibold tracking-[-0.02em] text-slate-900">
        {title}
      </h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">
        {description}
      </p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  );
}

function DocumentTypeBadge({
  label,
}: {
  label: WorkspaceDocument["typeLabel"];
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        label === "Spec" &&
          "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.09)] text-[var(--apex-accent-strong)]",
        label === "Reference" &&
          "border-[rgba(148,163,184,0.22)] bg-[rgba(241,245,249,0.9)] text-slate-600",
        label === "SOP" &&
          "border-[rgba(217,119,6,0.18)] bg-[rgba(255,247,237,0.95)] text-amber-700"
      )}
    >
      {label}
    </span>
  );
}

function formatSectionCount(value: number): string {
  return `${value} section${value === 1 ? "" : "s"}`;
}

function WorkspaceStateCard({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "error";
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-[18px] border px-4 py-6 text-sm leading-6",
        tone === "neutral" &&
          "border-[rgba(211,219,210,0.88)] bg-[rgba(251,252,248,0.95)] text-slate-500",
        tone === "error" &&
          "border-[rgba(240,195,195,0.92)] bg-[rgba(253,244,244,0.94)] text-rose-700"
      )}
    >
      {children}
    </div>
  );
}

function DocsNavigatorCard({
  status,
  documents,
  failedDocuments,
  selectedPath,
  onSelect,
  error,
}: {
  status: DocsWorkspaceStatus;
  documents: LoadedWorkspaceDocument[];
  failedDocuments: WorkspaceDocumentFailure[];
  selectedPath: string | null;
  onSelect: (document: LoadedWorkspaceDocument) => void;
  error: string | null;
}) {
  const loadedByPath = new Map(documents.map((document) => [document.path, document]));
  const failedByPath = new Map(
    failedDocuments.map((document) => [document.path, document])
  );
  const orderedEntries: DocsNavigatorEntry[] = [];

  workspaceDocs.forEach((document) => {
    const loadedDocument = loadedByPath.get(document.path);
    if (loadedDocument) {
      orderedEntries.push({ kind: "loaded", document: loadedDocument });
      return;
    }

    const failedDocument = failedByPath.get(document.path);
    if (failedDocument) {
      orderedEntries.push({ kind: "failed", document: failedDocument });
    }
  });

  return (
    <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/92 p-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-1 pb-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Document Navigator
        </p>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          Protocols, specs, and reference files stay collected here so the docs
          workspace feels like a reading surface instead of a generic file list.
        </p>
      </div>

      <div className="mt-3 space-y-2">
        {status === "loading" ? (
          <WorkspaceStateCard>Loading documentation index…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load the documentation index right now."}
          </WorkspaceStateCard>
        ) : orderedEntries.length === 0 ? (
          <WorkspaceStateCard>
            No documents are configured for this workspace yet.
          </WorkspaceStateCard>
        ) : (
          orderedEntries.map((entry) => {
            if (entry.kind === "failed") {
              const document = entry.document;
              const Icon = document.icon;

              return (
                <div
                  key={document.id}
                  className="rounded-[18px] border border-[rgba(240,195,195,0.92)] bg-[rgba(253,244,244,0.9)] px-4 py-4"
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[12px] bg-white text-rose-500">
                      <Icon size={17} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-semibold text-rose-900">
                          {document.label}
                        </p>
                        <DocumentTypeBadge label={document.typeLabel} />
                      </div>
                      <p className="mt-2 text-[12px] leading-5 text-rose-700">
                        {document.error}
                      </p>
                      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-rose-600">
                        <span>{document.audience}</span>
                        <span className="truncate">{document.meta ?? document.path}</span>
                        <span>Unavailable</span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            }

            const document = entry.document;
            const active = document.path === selectedPath;
            const Icon = document.icon;

            return (
              <button
                key={document.id}
                type="button"
                onClick={() => onSelect(document)}
                className={cn(
                  "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
                  active
                    ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] shadow-[0_10px_24px_rgba(35,130,83,0.08)]"
                    : "border-[rgba(211,219,210,0.85)] bg-[rgba(255,255,255,0.92)] hover:border-[rgba(35,130,83,0.16)] hover:bg-[rgba(248,251,247,0.95)]"
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      "mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[12px]",
                      active
                        ? "bg-white text-[var(--apex-accent-strong)]"
                        : "bg-[rgba(247,249,245,0.9)] text-slate-500"
                    )}
                  >
                    <Icon size={17} />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {document.label}
                      </p>
                      <DocumentTypeBadge label={document.typeLabel} />
                    </div>
                    <p className="mt-2 text-[12px] leading-5 text-slate-500">
                      {document.description}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      <span>{document.audience}</span>
                      <span>{formatSectionCount(document.parsed.sections.length)}</span>
                      <span className="truncate">{document.meta ?? document.path}</span>
                    </div>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function DocumentSectionMarkdown({
  content,
}: {
  content: string;
}) {
  return (
    <div className="apex-chat-prose prose prose-sm max-w-none prose-pre:bg-[#1e1e1e] prose-pre:text-gray-100 prose-p:text-slate-600 prose-li:text-slate-600 prose-strong:text-slate-900">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h1({ children }) {
            return (
              <h4 className="mt-0 text-base font-semibold tracking-[-0.02em] text-slate-900">
                {children}
              </h4>
            );
          },
          h2({ children }) {
            return (
              <h4 className="mt-0 text-base font-semibold tracking-[-0.02em] text-slate-900">
                {children}
              </h4>
            );
          },
          h3({ children }) {
            return (
              <h5 className="mt-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 first:mt-0">
                {children}
              </h5>
            );
          },
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className ?? "");
            if (!match) {
              return (
                <code
                  className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.8em] text-[#c7254e]"
                  {...props}
                >
                  {children}
                </code>
              );
            }

            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="my-4 overflow-x-auto">
                <table className="min-w-full overflow-hidden rounded-lg border border-slate-200 text-xs">
                  {children}
                </table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-left font-semibold text-slate-700">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="border-b border-slate-100 px-3 py-2 text-slate-600">
                {children}
              </td>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function DocsReaderPane({
  status,
  document,
  error,
  warning,
  onOpen,
}: {
  status: DocsWorkspaceStatus;
  document: LoadedWorkspaceDocument | null;
  error: string | null;
  warning?: string | null;
  onOpen?: () => void;
}) {
  return (
    <div className="flex min-h-[32rem] flex-col rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/94 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-5 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Reading Pane
            </p>
            <h3 className="mt-2 text-[1.4rem] font-semibold tracking-[-0.03em] text-slate-900">
              {document?.parsed.title ?? "Select a document"}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {document?.description ??
                "Choose a protocol, spec, or reference from the navigator to read it as structured sections."}
            </p>
            {document?.meta ? (
              <p className="mt-2 text-[11px] text-slate-400">{document.meta}</p>
            ) : null}
          </div>

          {document?.path && onOpen ? (
            <WorkspaceAction onClick={onOpen} tone="accent">
              <FolderOpen size={12} />
              Open In Inspector
            </WorkspaceAction>
          ) : null}
        </div>

        {document ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <DocumentTypeBadge label={document.typeLabel} />
            <WorkspaceBadge icon={BookOpen}>
              {formatSectionCount(document.parsed.sections.length)}
            </WorkspaceBadge>
            <WorkspaceBadge icon={FileText}>{document.audience}</WorkspaceBadge>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {warning ? (
          <div className="mb-4">
            <WorkspaceStateCard>{warning}</WorkspaceStateCard>
          </div>
        ) : null}

        {status === "loading" ? (
          <WorkspaceStateCard>Loading selected document…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load the selected document right now."}
          </WorkspaceStateCard>
        ) : !document ? (
          <WorkspaceStateCard>
            Select a document from the navigator to load its reading view.
          </WorkspaceStateCard>
        ) : document.parsed.sections.length === 0 ? (
          <WorkspaceStateCard>
            This document does not have any structured sections to render yet.
          </WorkspaceStateCard>
        ) : (
          <div className="space-y-4">
            {document.parsed.sections.map((section, index) => (
              <section
                key={section.id}
                className="rounded-[20px] border border-[rgba(211,219,210,0.88)] bg-[linear-gradient(180deg,rgba(250,251,248,0.97),rgba(255,255,255,0.98))] p-4 shadow-[0_8px_20px_rgba(29,42,33,0.03)]"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <span className="inline-flex items-center rounded-full bg-[rgba(35,130,83,0.08)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--apex-accent-strong)]">
                    Section {index + 1}
                  </span>
                  <h4 className="text-lg font-semibold tracking-[-0.02em] text-slate-900">
                    {section.title}
                  </h4>
                </div>

                <div className="mt-4 rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-4">
                  <DocumentSectionMarkdown content={section.markdown} />
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FlowsPrimaryAction({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-[14px] bg-[var(--apex-accent)] px-4 py-2.5 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(35,130,83,0.18)] transition-colors hover:bg-[var(--apex-accent-strong)]"
    >
      {children}
    </button>
  );
}

function FlowsStatusBadge({
  status,
}: {
  status: FlowsWorkspaceStatus;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold",
        status === "active" &&
          "bg-[rgba(35,130,83,0.12)] text-[var(--apex-accent-strong)]",
        status === "idle" && "bg-[rgba(148,163,184,0.12)] text-slate-500",
        status === "blocked" && "bg-[rgba(217,119,6,0.12)] text-amber-700",
        status === "failed" && "bg-[rgba(220,38,38,0.1)] text-red-700"
      )}
    >
      {summarizeFlowsWorkspaceStatus(status)}
    </span>
  );
}

function FlowsWorkspaceCard({
  label,
  status,
  runCount,
  lastActivityAt,
  selected = false,
  onClick,
}: {
  label: string;
  status: FlowsWorkspaceStatus;
  runCount: number;
  lastActivityAt: number | null;
  selected?: boolean;
  onClick: () => void;
}) {
  const timestampLabel = lastActivityAt
    ? formatRelativeTime(lastActivityAt)
    : "No recent activity";
  const runCountLabel =
    runCount === 0 ? "No runs yet" : `${runCount} run${runCount === 1 ? "" : "s"}`;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-4 rounded-[20px] border px-5 py-5 text-left shadow-[0_10px_28px_rgba(18,24,20,0.04)] transition-colors",
        selected && "shadow-[0_14px_34px_rgba(18,24,20,0.08)]",
        status === "active" &&
          (selected
            ? "border-[rgba(101,174,135,0.96)] bg-[linear-gradient(180deg,rgba(244,251,247,0.99),rgba(238,248,242,0.99))]"
            : "border-[rgba(131,191,157,0.92)] bg-[linear-gradient(180deg,rgba(247,252,249,0.98),rgba(241,249,244,0.98))] hover:border-[rgba(101,174,135,0.96)]"),
        status === "idle" &&
          (selected
            ? "border-[rgba(194,204,194,0.98)] bg-[rgba(250,251,249,0.99)]"
            : "border-[rgba(228,232,226,0.96)] bg-white/96 hover:border-[rgba(204,214,203,0.96)] hover:bg-[rgba(251,252,250,0.98)]"),
        status === "blocked" &&
          (selected
            ? "border-[rgba(217,119,6,0.36)] bg-[linear-gradient(180deg,rgba(255,249,230,0.99),rgba(255,244,231,0.99))]"
            : "border-[rgba(245,158,11,0.3)] bg-[linear-gradient(180deg,rgba(255,251,235,0.98),rgba(255,247,237,0.98))] hover:border-[rgba(217,119,6,0.34)]"),
        status === "failed" &&
          (selected
            ? "border-[rgba(220,38,38,0.34)] bg-[linear-gradient(180deg,rgba(254,240,240,0.99),rgba(254,245,245,0.99))]"
            : "border-[rgba(248,113,113,0.28)] bg-[linear-gradient(180deg,rgba(254,242,242,0.98),rgba(254,247,247,0.98))] hover:border-[rgba(220,38,38,0.32)]")
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-[1.05rem] font-semibold tracking-[-0.02em] text-slate-900">
          {label}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-slate-500">
          <FlowsStatusBadge status={status} />
          <span>{runCountLabel}</span>
          <span>{timestampLabel}</span>
        </div>
      </div>

      <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border border-[rgba(226,232,240,0.95)] bg-white/92 text-slate-500">
        <ArrowRight size={16} />
      </div>
    </button>
  );
}

function summarizeFlowsDetail(status: FlowsWorkspaceStatus): string {
  if (status === "active") {
    return "Recent activity is live or staged for the next workflow request.";
  }
  if (status === "blocked") {
    return "The latest activity hit a block and needs review before it can move forward.";
  }
  if (status === "failed") {
    return "The latest observed run failed and should be inspected before retrying.";
  }
  return "Recent activity is settled, and this workflow is ready for the next run.";
}

function FlowsWorkspace() {
  const {
    messages,
    sessions,
    selectedWorkflow,
    draftMessage,
    setWorkspaceMode,
    selectWorkflow,
    primeDraftMessage,
  } = useApp();

  const workflowSummary = getWorkflowSummary(messages);
  const [workspaceItems, setWorkspaceItems] = useState<FlowsWorkspaceSummaryItem[]>([]);
  const [workspaceStatus, setWorkspaceStatus] = useState<"loading" | "ready" | "error">(
    "loading"
  );
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(null);
  const sessionRefreshToken = sessions
    .map((session) => `${session.id}:${session.updated_at}:${session.message_count}`)
    .join("|");

  useEffect(() => {
    let active = true;
    setWorkspaceStatus("loading");

    void getFlowsWorkspaceSummary()
      .then((response) => {
        if (!active) return;
        setWorkspaceItems(response.items);
        setWorkspaceStatus("ready");
      })
      .catch(() => {
        if (!active) return;
        setWorkspaceItems([]);
        setWorkspaceStatus("error");
      });

    return () => {
      active = false;
    };
  }, [sessionRefreshToken]);

  const workspaceSummary = flowsWorkspaceSummaryMap(workspaceItems);
  const flowCards = flowsWorkspaceDefinitions.map((definition) => {
    const summary = workspaceSummary.get(definition.id);
    const quickStart = getQuickStartItem(definition.quickStartId);
    const quickStartActive = quickStart
      ? quickStart.workflowId
        ? selectedWorkflow === quickStart.workflowId
        : !selectedWorkflow && draftMessage === quickStart.draftMessage
      : false;
    const currentWorkflowState =
      definition.workflowId && workflowSummary.workflowId === definition.workflowId
        ? workflowSummary.status
        : null;

    let status: FlowsWorkspaceStatus = summary?.status ?? "idle";
    if (currentWorkflowState === "blocked") {
      status = "blocked";
    } else if (currentWorkflowState === "failed") {
      status = "failed";
    } else if (
      currentWorkflowState === "running" ||
      currentWorkflowState === "not_started" ||
      quickStartActive
    ) {
      status = "active";
    }

    return {
      ...definition,
      status,
      runCount: summary?.run_count ?? 0,
      lastActivityAt: summary?.last_activity_at ?? null,
      quickStart,
    };
  });
  const hasRecordedActivity = flowCards.some((item) => item.runCount > 0);
  const selectedCard =
    flowCards.find((item) => item.id === selectedFlowId) ?? flowCards[0] ?? null;

  useEffect(() => {
    if (flowCards.length === 0) {
      if (selectedFlowId !== null) {
        setSelectedFlowId(null);
      }
      return;
    }

    if (selectedFlowId && flowCards.some((item) => item.id === selectedFlowId)) {
      return;
    }

    setSelectedFlowId(flowCards[0].id);
  }, [flowCards, selectedFlowId]);

  const selectedCardSessionDetail =
    selectedCard?.workflowId &&
    workflowSummary.workflowId === selectedCard.workflowId &&
    workflowSummary.status !== "idle"
      ? describeWorkflow(workflowSummary)
      : null;

  return (
    <WorkspaceShell mode="flows">
      <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-5">
        <div className="flex flex-col gap-4 rounded-[24px] border border-[rgba(223,229,221,0.96)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,246,0.96))] px-5 py-5 shadow-[0_12px_30px_rgba(24,35,27,0.04)] sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-[1.65rem] font-semibold tracking-[-0.03em] text-slate-900">
              Workflows
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              Manage and track your analysis workflows.
            </p>
          </div>

          <FlowsPrimaryAction onClick={() => setWorkspaceMode("sessions")}>
            <Plus size={15} />
            New Workflow
          </FlowsPrimaryAction>
        </div>

        {workspaceStatus === "error" ? (
          <EmptyWorkspaceState
            title="Workflow activity could not load"
            description="The Flows workspace could not read recent workflow activity right now. Open the session workspace to continue working, then try again."
            action={
              <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
                <MessageSquare size={12} />
                Open Session Workspace
              </WorkspaceAction>
            }
          />
        ) : !hasRecordedActivity && workspaceStatus === "ready" ? (
          <EmptyWorkspaceState
            title="No workflow activity yet"
            description="Start a workflow, run an evidence review, or trigger a compliance check and the latest activity will appear here for quick tracking."
            action={
              <FlowsPrimaryAction onClick={() => setWorkspaceMode("sessions")}>
                <Plus size={15} />
                New Workflow
              </FlowsPrimaryAction>
            }
          />
        ) : (
          <div className="space-y-4">
            {flowCards.map((item) => (
              <FlowsWorkspaceCard
                key={item.id}
                label={item.label}
                status={item.status}
                runCount={item.runCount}
                lastActivityAt={item.lastActivityAt}
                selected={selectedCard?.id === item.id}
                onClick={() => setSelectedFlowId(item.id)}
              />
            ))}

            {selectedCard ? (
              <div className="rounded-[22px] border border-[rgba(223,229,221,0.96)] bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,250,246,0.96))] p-5 shadow-[0_10px_28px_rgba(18,24,20,0.05)]">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div className="max-w-2xl">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      Workflow Detail
                    </p>
                    <h3 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-slate-900">
                      {selectedCard.label}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-slate-500">
                      {selectedCardSessionDetail ??
                        selectedCard.description ??
                        summarizeFlowsDetail(selectedCard.status)}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <WorkspaceAction onClick={() => setWorkspaceMode("sessions")}>
                      <MessageSquare size={12} />
                      Open Session
                    </WorkspaceAction>
                    {selectedCard.quickStart ? (
                      <WorkspaceAction
                        onClick={() => {
                          const quickStart = selectedCard.quickStart;
                          if (!quickStart) return;
                          selectWorkflow(quickStart.workflowId ?? null);
                          primeDraftMessage(quickStart.draftMessage);
                          setWorkspaceMode("sessions");
                        }}
                        tone="accent"
                      >
                        <Sparkles size={12} />
                        Prepare In Session
                      </WorkspaceAction>
                    ) : null}
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <WorkspaceBadge icon={FlaskConical}>
                    {summarizeFlowsWorkspaceStatus(selectedCard.status)}
                  </WorkspaceBadge>
                  <WorkspaceBadge icon={Sparkles}>
                    {selectedCard.runCount === 0
                      ? "No runs yet"
                      : `${selectedCard.runCount} run${selectedCard.runCount === 1 ? "" : "s"}`}
                  </WorkspaceBadge>
                  <WorkspaceBadge icon={MessageSquare}>
                    {selectedCard.lastActivityAt
                      ? formatRelativeTime(selectedCard.lastActivityAt)
                      : "No recent activity"}
                  </WorkspaceBadge>
                  {selectedCard.workflowId ? (
                    <WorkspaceBadge icon={FlaskConical}>
                      {selectedCard.workflowId}
                    </WorkspaceBadge>
                  ) : null}
                </div>
              </div>
            ) : null}

            {workspaceStatus === "loading" ? (
              <p className="px-1 text-sm text-slate-500">
                Syncing recent workflow activity…
              </p>
            ) : null}
          </div>
        )}
      </div>
    </WorkspaceShell>
  );
}

function DocsWorkspace() {
  const { workspaceMode, inspectorPreviewPath, openInspectorPath, setWorkspaceMode } =
    useApp();
  const [selectedDocPath, setSelectedDocPath] = useState<string | null>(
    workspaceDocs[0]?.path ?? null
  );
  const [documents, setDocuments] = useState<LoadedWorkspaceDocument[]>([]);
  const [failedDocuments, setFailedDocuments] = useState<WorkspaceDocumentFailure[]>(
    []
  );
  const [workspaceStatus, setWorkspaceStatus] =
    useState<DocsWorkspaceStatus>("loading");
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [workspaceWarning, setWorkspaceWarning] = useState<string | null>(null);

  useEffect(() => {
    if (
      workspaceMode === "docs" &&
      inspectorPreviewPath &&
      workspaceDocs.some((item) => item.path === inspectorPreviewPath)
    ) {
      setSelectedDocPath(inspectorPreviewPath);
    }
  }, [inspectorPreviewPath, workspaceMode]);

  useEffect(() => {
    if (workspaceMode !== "docs") return;

    let active = true;
    setWorkspaceStatus("loading");
    setWorkspaceError(null);
    setWorkspaceWarning(null);
    setFailedDocuments([]);

    void Promise.allSettled(
      workspaceDocs.map(async (document) => {
        const response = await readFile(document.path);
        const loadedDocument: LoadedWorkspaceDocument = {
          ...document,
          parsed: parseWorkspaceDocument(response.content, document.label),
        };
        return loadedDocument;
      })
    )
      .then((results) => {
        if (!active) return;

        const loadedDocuments: LoadedWorkspaceDocument[] = [];
        const unreadableDocuments: WorkspaceDocumentFailure[] = [];

        results.forEach((result, index) => {
          const configuredDocument = workspaceDocs[index];
          if (!configuredDocument) return;

          if (result.status === "fulfilled") {
            loadedDocuments.push(result.value);
            return;
          }

          unreadableDocuments.push({
            ...configuredDocument,
            error:
              result.reason instanceof Error
                ? result.reason.message
                : "Unable to read this document right now.",
          });
        });

        setDocuments(loadedDocuments);
        setFailedDocuments(unreadableDocuments);

        if (loadedDocuments.length === 0) {
          setWorkspaceStatus("error");
          setWorkspaceError(
            unreadableDocuments.length === 1
              ? `The Docs workspace could not load ${unreadableDocuments[0]?.label ?? "the configured document"}.`
              : "The Docs workspace could not load any configured documents right now."
          );
          return;
        }

        setWorkspaceStatus("ready");
        if (unreadableDocuments.length > 0) {
          setWorkspaceWarning(
            unreadableDocuments.length === 1
              ? `${unreadableDocuments[0]?.label ?? "One document"} is temporarily unavailable. The remaining docs are still ready to read.`
              : `${unreadableDocuments.length} configured docs are temporarily unavailable. The remaining docs are still ready to read.`
          );
        }
      })
      .catch((error) => {
        if (!active) return;
        setDocuments([]);
        setFailedDocuments([]);
        setWorkspaceStatus("error");
        setWorkspaceError(
          error instanceof Error
            ? error.message
            : "Unable to load documentation right now."
        );
      });

    return () => {
      active = false;
    };
  }, [workspaceMode]);

  useEffect(() => {
    if (documents.length === 0) return;
    if (selectedDocPath && documents.some((document) => document.path === selectedDocPath)) {
      return;
    }

    setSelectedDocPath(documents[0].path);
  }, [documents, selectedDocPath]);

  const selectedDoc =
    documents.find((item) => item.path === selectedDocPath) ?? documents[0] ?? null;

  return (
    <WorkspaceShell mode="docs">
      <WorkspaceHero
        icon={BookOpen}
        title="Documentation"
        description="Read BioAPEX specs, SOPs, and reference material in a workspace built for implementation work instead of a plain file preview."
        badges={
          <>
            <WorkspaceBadge icon={BookOpen}>{`${workspaceDocs.length} docs`}</WorkspaceBadge>
            {selectedDoc ? (
              <WorkspaceBadge icon={FileText}>{selectedDoc.parsed.title}</WorkspaceBadge>
            ) : null}
            {selectedDoc ? <DocumentTypeBadge label={selectedDoc.typeLabel} /> : null}
          </>
        }
        actions={
          <>
            {selectedDoc?.path ? (
              <WorkspaceAction
                onClick={() => openInspectorPath(selectedDoc.path!)}
                tone="accent"
              >
                <FolderOpen size={12} />
                Inspect Selected Doc
              </WorkspaceAction>
            ) : null}
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")}>
              <MessageSquare size={12} />
              Return To Session
            </WorkspaceAction>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          label="Working Set"
          value={`${workspaceDocs.length} docs`}
          detail="Protocols, specs, and reference material stay together in one center-workspace surface."
        />
        <SummaryCard
          label="Focused Doc"
          value={selectedDoc?.label ?? "None"}
          detail={
            selectedDoc?.description ??
            "Choose a document to load its structured reading view."
          }
        />
        <SummaryCard
          label="Reading State"
          value={
            workspaceStatus === "ready"
              ? selectedDoc
                ? formatSectionCount(selectedDoc.parsed.sections.length)
                : "Waiting"
              : workspaceStatus === "loading"
                ? "Loading"
                : "Issue"
          }
          detail="The selected document is rendered as section cards so longer specs and protocols remain readable."
        />
      </div>

      <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <DocsNavigatorCard
          status={workspaceStatus}
          documents={documents}
          failedDocuments={failedDocuments}
          selectedPath={selectedDoc?.path ?? null}
          onSelect={(document) => setSelectedDocPath(document.path)}
          error={workspaceError}
        />

        <DocsReaderPane
          status={workspaceStatus}
          document={selectedDoc}
          error={workspaceError}
          warning={workspaceWarning}
          onOpen={
            selectedDoc?.path ? () => openInspectorPath(selectedDoc.path!) : undefined
          }
        />
      </div>
    </WorkspaceShell>
  );
}

function FilesWorkspaceTypeBadge({
  item,
}: {
  item: FilesWorkspaceItem;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        filesWorkspaceKindTone(item)
      )}
    >
      {filesWorkspaceKindLabel(item)}
    </span>
  );
}

function FilesWorkspaceRow({
  item,
  active,
  onSelect,
}: {
  item: FilesWorkspaceItem;
  active: boolean;
  onSelect: () => void;
}) {
  const kind = inferFilesWorkspaceKind(item);
  const Icon = kind === "archive" ? Package : kind === "plot" ? Files : FileText;

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
        active
          ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] shadow-[0_10px_24px_rgba(35,130,83,0.08)]"
          : "border-[rgba(211,219,210,0.85)] bg-[rgba(255,255,255,0.92)] hover:border-[rgba(35,130,83,0.16)] hover:bg-[rgba(248,251,247,0.95)]"
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px]",
            active
              ? "bg-white text-[var(--apex-accent-strong)]"
              : "bg-[rgba(247,249,245,0.9)] text-slate-500"
          )}
        >
          <Icon size={18} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-semibold text-slate-900">{item.name}</p>
            <FilesWorkspaceTypeBadge item={item} />
          </div>
          <p className="mt-2 text-[12px] leading-5 text-slate-500">
            {describeFilesWorkspaceItem(item)}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
            <span>{formatByteSize(item.size_bytes)}</span>
            <span>
              {item.materialized_at
                ? formatRelativeTime(item.materialized_at)
                : "Unknown time"}
            </span>
            <span>{shortRunLabel(item.run_id)}</span>
          </div>
        </div>
      </div>
    </button>
  );
}

function FilesNavigatorCard({
  status,
  items,
  selectedPath,
  onSelect,
  error,
}: {
  status: FilesWorkspaceStatus;
  items: FilesWorkspaceItem[];
  selectedPath: string | null;
  onSelect: (item: FilesWorkspaceItem) => void;
  error: string | null;
}) {
  return (
    <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/92 p-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-1 pb-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Output Browser
        </p>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          Generated artifacts are grouped here as durable session outputs so you
          can review results outside the chat transcript.
        </p>
      </div>

      <div className="mt-3 space-y-2">
        {status === "loading" ? (
          <WorkspaceStateCard>Loading generated file metadata…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load generated files right now."}
          </WorkspaceStateCard>
        ) : items.length === 0 ? (
          <WorkspaceStateCard>
            No generated files are available for this session yet.
          </WorkspaceStateCard>
        ) : (
          items.map((item) => (
            <FilesWorkspaceRow
              key={item.path}
              item={item}
              active={item.path === selectedPath}
              onSelect={() => onSelect(item)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function FilesDetailPane({
  status,
  item,
  error,
  preview,
  onOpenInspector,
}: {
  status: FilesWorkspaceStatus;
  item: FilesWorkspaceItem | null;
  error: string | null;
  preview: {
    status: PreviewStatus;
    content: string;
    error: string | null;
  };
  onOpenInspector?: () => void;
}) {
  const previewMode = item ? getFilesWorkspacePreviewMode(item) : null;
  const [openRawFileError, setOpenRawFileError] = useState<string | null>(null);
  const previewUnavailableMessage = item
    ? inferFilesWorkspaceKind(item) === "plot"
      ? "This plot is ready to open in the inspector or raw-file view."
      : inferFilesWorkspaceKind(item) === "archive"
        ? "This archive is tracked in the workspace and can be opened through the raw-file endpoint."
        : "This file type is tracked here even though it is not previewed inline yet."
    : null;
  const supportsRawInlinePreview = previewMode === "image" || previewMode === "pdf";
  const {
    url: rawPreviewUrl,
    error: rawPreviewError,
    loading: rawPreviewLoading,
  } = useRawPreviewObjectUrl(item?.path ?? null, supportsRawInlinePreview);

  useEffect(() => {
    setOpenRawFileError(null);
  }, [item?.path]);

  const handleOpenRawFile = () => {
    if (!item?.path) {
      return;
    }
    setOpenRawFileError(null);
    void openRawFileInNewTab(item.path).catch(() => {
      setOpenRawFileError("Could not open the raw file right now.");
    });
  };

  return (
    <div className="flex min-h-[32rem] flex-col rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/94 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-5 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              File Detail
            </p>
            <h3 className="mt-2 text-[1.4rem] font-semibold tracking-[-0.03em] text-slate-900">
              {item?.name ?? "Select a generated file"}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {item
                ? describeFilesWorkspaceItem(item)
                : "Choose a file from the output browser to inspect its metadata and inline preview."}
            </p>
            {item?.path ? (
              <p className="mt-2 break-all text-[11px] text-slate-400">{item.path}</p>
            ) : null}
          </div>

          {item?.path ? (
            <div className="flex flex-wrap gap-2">
              {onOpenInspector ? (
                <WorkspaceAction onClick={onOpenInspector} tone="accent">
                  <FolderOpen size={12} />
                  Open In Inspector
                </WorkspaceAction>
              ) : null}
              {item?.path ? (
                <WorkspaceAction onClick={handleOpenRawFile}>
                  <ExternalLink size={12} />
                  Open Raw File
                </WorkspaceAction>
              ) : null}
            </div>
          ) : null}
        </div>

        {item ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <FilesWorkspaceTypeBadge item={item} />
            <WorkspaceBadge icon={FileText}>{formatByteSize(item.size_bytes)}</WorkspaceBadge>
            <WorkspaceBadge icon={Files}>{shortRunLabel(item.run_id)}</WorkspaceBadge>
            <WorkspaceBadge icon={Sparkles}>
              {item.materialized_at
                ? formatRelativeTime(item.materialized_at)
                : "Unknown time"}
            </WorkspaceBadge>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {status === "loading" ? (
          <WorkspaceStateCard>Loading selected file metadata…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load this file workspace right now."}
          </WorkspaceStateCard>
        ) : !item ? (
          <WorkspaceStateCard>
            Select a generated file from the browser to load its detail view.
          </WorkspaceStateCard>
        ) : (
          <div className="space-y-4">
            <section className="rounded-[20px] border border-[rgba(211,219,210,0.88)] bg-[linear-gradient(180deg,rgba(250,251,248,0.97),rgba(255,255,255,0.98))] p-4 shadow-[0_8px_20px_rgba(29,42,33,0.03)]">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Artifact Metadata
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Workflow
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {humanizeToken(item.workflow) ?? "Unknown workflow"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Run
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {item.run_id ?? "No run identifier"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Step
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {humanizeToken(item.step_label) ?? "Not linked to a workflow step"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Source
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {humanizeToken(item.source_tool) ??
                      humanizeToken(item.output_name) ??
                      "Generated artifact"}
                  </p>
                </div>
              </div>
            </section>

            <section className="rounded-[20px] border border-[rgba(211,219,210,0.88)] bg-[linear-gradient(180deg,rgba(250,251,248,0.97),rgba(255,255,255,0.98))] p-4 shadow-[0_8px_20px_rgba(29,42,33,0.03)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Preview
                  </p>
                  <h4 className="mt-1 text-lg font-semibold tracking-[-0.02em] text-slate-900">
                    {previewMode === "image"
                      ? "Inline image"
                      : previewMode === "pdf"
                        ? "Inline document"
                        : previewMode === "text"
                          ? "Inline snippet"
                          : "Open-backed artifact"}
                  </h4>
                </div>
                {item?.path ? (
                  <WorkspaceAction onClick={handleOpenRawFile}>
                    <ExternalLink size={12} />
                    Open Raw File
                  </WorkspaceAction>
                ) : null}
              </div>

              <div className="mt-4 rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-4">
                {previewMode === "unsupported" ? (
                  <WorkspaceStateCard>{previewUnavailableMessage}</WorkspaceStateCard>
                ) : supportsRawInlinePreview && rawPreviewLoading ? (
                  <WorkspaceStateCard>Loading raw preview…</WorkspaceStateCard>
                ) : openRawFileError || rawPreviewError ? (
                  <WorkspaceStateCard tone="error">
                    {openRawFileError ?? rawPreviewError}
                  </WorkspaceStateCard>
                ) : previewMode === "image" && rawPreviewUrl ? (
                  <div className="overflow-hidden rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.95)]">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={rawPreviewUrl}
                      alt={item.name}
                      className="max-h-[30rem] w-full object-contain"
                    />
                  </div>
                ) : previewMode === "pdf" && rawPreviewUrl ? (
                  <iframe
                    src={rawPreviewUrl}
                    title={item.name}
                    className="h-[30rem] w-full rounded-[16px] border border-[rgba(214,221,212,0.86)]"
                  />
                ) : preview.status === "loading" ? (
                  <WorkspaceStateCard>Loading preview…</WorkspaceStateCard>
                ) : preview.status === "error" ? (
                  <WorkspaceStateCard tone="error">
                    {preview.error ?? "Unable to load that preview."}
                  </WorkspaceStateCard>
                ) : preview.status === "ready" ? (
                  <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[16px] bg-[rgba(248,250,246,0.95)] px-4 py-4 font-mono text-[12px] leading-6 text-slate-700">
                    {previewText(preview.content)}
                  </pre>
                ) : (
                  <WorkspaceStateCard>
                    Select a generated file to preview it here.
                  </WorkspaceStateCard>
                )}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function FilesWorkspace() {
  const {
    workspaceMode,
    currentSessionId,
    inspectorPreviewPath,
    openInspectorPath,
    setWorkspaceMode,
    messages,
  } = useApp();
  const workflowSummary = getWorkflowSummary(messages);
  const latestWorkflowEvent = workflowSummary.events.at(-1);
  const toolArtifactRefCount = messages.reduce((count, message) => {
    const toolCalls = message.tool_calls ?? [];
    return (
      count +
      toolCalls.reduce(
        (toolCount, toolCall) =>
          toolCount + (toolCall.result?.artifact_refs?.length ?? 0),
        0
      )
    );
  }, 0);
  const filesRefreshKey =
    `${workflowSummary.workflowId ?? "none"}:` +
    `${latestWorkflowEvent?.run_id ?? "none"}:` +
    `${workflowSummary.events.length}:` +
    `${latestWorkflowEvent?.type ?? "none"}:` +
    `${toolArtifactRefCount}`;
  const [workspaceStatus, setWorkspaceStatus] =
    useState<FilesWorkspaceStatus>("idle");
  const [fileItems, setFileItems] = useState<FilesWorkspaceItem[]>([]);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    if (workspaceMode !== "files") {
      return () => {
        active = false;
      };
    }

    if (!currentSessionId) {
      setWorkspaceStatus("idle");
      setFileItems([]);
      setWorkspaceError(null);
      setSelectedFilePath(null);
      return () => {
        active = false;
      };
    }

    setWorkspaceStatus((previous) => (previous === "ready" ? previous : "loading"));
    setWorkspaceError(null);

    void getFilesWorkspaceSummary(currentSessionId)
      .then((response) => {
        if (!active) return;
        setFileItems(response.items);
        setWorkspaceStatus("ready");
      })
      .catch((filesError) => {
        if (!active) return;
        setWorkspaceStatus("error");
        setWorkspaceError(
          filesError instanceof Error
            ? filesError.message
            : "Unable to load generated files right now."
        );
      });

    return () => {
      active = false;
    };
  }, [currentSessionId, filesRefreshKey, workspaceMode]);

  useEffect(() => {
    if (workspaceMode !== "files") return;

    if (
      inspectorPreviewPath &&
      fileItems.some((item) => item.path === inspectorPreviewPath)
    ) {
      setSelectedFilePath(inspectorPreviewPath);
      return;
    }

    if (
      selectedFilePath &&
      fileItems.some((item) => item.path === selectedFilePath)
    ) {
      return;
    }

    setSelectedFilePath(fileItems[0]?.path ?? null);
  }, [fileItems, inspectorPreviewPath, selectedFilePath, workspaceMode]);

  const selectedFile =
    fileItems.find((item) => item.path === selectedFilePath) ?? fileItems[0] ?? null;
  const preview = usePreviewContent(
    selectedFile && isTextPreviewable(selectedFile) ? selectedFile.path : null
  );
  const latestFile = fileItems[0] ?? null;
  const hasSessionActivity = messages.length > 0;

  return (
    <WorkspaceShell mode="files">
      <WorkspaceHero
        icon={Files}
        title="Output Files"
        description="Review results, plots, and generated artifacts from the current session in a dedicated center workspace instead of hunting through chat history."
        badges={
          <>
            <WorkspaceBadge icon={Files}>{`${fileItems.length} files`}</WorkspaceBadge>
            {latestFile?.run_id ? (
              <WorkspaceBadge icon={Sparkles}>
                {shortRunLabel(latestFile.run_id)}
              </WorkspaceBadge>
            ) : null}
            {selectedFile ? (
              <WorkspaceBadge icon={FileText}>
                {filesWorkspaceKindLabel(selectedFile)}
              </WorkspaceBadge>
            ) : null}
          </>
        }
        actions={
          <>
            {selectedFile?.path ? (
              <WorkspaceAction
                onClick={() => openInspectorPath(selectedFile.path)}
                tone="accent"
              >
                <FolderOpen size={12} />
                Inspect Selected File
              </WorkspaceAction>
            ) : null}
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")}>
              <MessageSquare size={12} />
              Open Session Workspace
            </WorkspaceAction>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          label="Output Files"
          value={
            workspaceStatus === "loading"
              ? "Loading"
              : workspaceStatus === "error"
                ? "Issue"
                : `${fileItems.length}`
          }
          detail="The file browser is backed by durable artifact paths and file metadata for the active session."
        />
        <SummaryCard
          label="Latest Run"
          value={latestFile?.run_id ? shortRunLabel(latestFile.run_id) : "None"}
          detail="Each row keeps its associated run identifier visible so results stay tied to execution context."
        />
        <SummaryCard
          label="Selected Size"
          value={selectedFile ? formatByteSize(selectedFile.size_bytes) : "Waiting"}
          detail="Large and small outputs use the same browser layout so preview and open actions can expand later without redesign."
        />
      </div>

      {!currentSessionId ? (
        <EmptyWorkspaceState
          title="Open or create a session first"
          description="The Files workspace stays scoped to the active session so generated outputs can be reviewed alongside the matching inspector context."
          action={
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
              <MessageSquare size={12} />
              Go To Sessions
            </WorkspaceAction>
          }
        />
      ) : workspaceStatus === "loading" ? (
        <WorkspaceStateCard>Loading generated files for this session…</WorkspaceStateCard>
      ) : workspaceStatus === "error" ? (
        <WorkspaceStateCard tone="error">
          {workspaceError ?? "Unable to load the Files workspace right now."}
        </WorkspaceStateCard>
      ) : fileItems.length === 0 && !hasSessionActivity ? (
        <EmptyWorkspaceState
          title="No session outputs yet"
          description="Start a workflow or create a generated artifact in the session workspace and the durable files will appear here."
          action={
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
              <MessageSquare size={12} />
              Start In Sessions
            </WorkspaceAction>
          }
        />
      ) : fileItems.length === 0 ? (
        <EmptyWorkspaceState
          title="No durable file results for this session"
          description="This session has activity, but it has not materialized any generated artifact files that the workspace can browse yet."
          action={
            <WorkspaceAction onClick={() => setWorkspaceMode("flows")} tone="accent">
              <FlaskConical size={12} />
              Open Flows Workspace
            </WorkspaceAction>
          }
        />
      ) : (
        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <FilesNavigatorCard
            status={workspaceStatus}
            items={fileItems}
            selectedPath={selectedFile?.path ?? null}
            onSelect={(item) => setSelectedFilePath(item.path)}
            error={workspaceError}
          />

          <FilesDetailPane
            status={workspaceStatus}
            item={selectedFile}
            error={workspaceError}
            preview={preview}
            onOpenInspector={
              selectedFile?.path ? () => openInspectorPath(selectedFile.path) : undefined
            }
          />
        </div>
      )}
    </WorkspaceShell>
  );
}

function artifactRegistryTypeTone(record: ArtifactRegistryRecord): string {
  if (record.status === "invalid") {
    return "border-[rgba(244,63,94,0.18)] bg-[rgba(255,241,242,0.95)] text-rose-700";
  }

  if (
    record.artifact_type.includes("evidence") ||
    record.artifact_type.includes("claim") ||
    record.artifact_type.includes("grounding")
  ) {
    return "border-[rgba(2,132,199,0.16)] bg-[rgba(240,249,255,0.95)] text-sky-700";
  }

  if (
    record.artifact_type.includes("compliance") ||
    record.artifact_type.includes("qa") ||
    record.artifact_type.includes("checklist")
  ) {
    return "border-[rgba(217,119,6,0.18)] bg-[rgba(255,247,237,0.95)] text-amber-700";
  }

  if (
    record.artifact_type.includes("provenance") ||
    record.artifact_type.includes("biocompute") ||
    record.artifact_type.includes("eln")
  ) {
    return "border-[rgba(120,53,15,0.14)] bg-[rgba(250,245,235,0.94)] text-stone-700";
  }

  return "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]";
}

function artifactRegistryStatusTone(record: ArtifactRegistryRecord): string {
  return record.status === "invalid"
    ? "border-[rgba(244,63,94,0.18)] bg-[rgba(255,241,242,0.95)] text-rose-700"
    : "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] text-[var(--apex-accent-strong)]";
}

function artifactRegistryTimestampLabel(record: ArtifactRegistryRecord): string {
  const timestamp = getArtifactRegistryTimestamp(record);
  return timestamp ? formatRelativeTime(timestamp) : "Unknown time";
}

function formatArtifactRegistryGeneratedAt(value?: string | null): string {
  if (!value) {
    return "Waiting";
  }

  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? "Waiting" : formatRelativeTime(timestamp);
}

function ArtifactRegistryTypeBadge({
  record,
}: {
  record: ArtifactRegistryRecord;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        artifactRegistryTypeTone(record)
      )}
    >
      {humanizeArtifactToken(record.artifact_type) ?? "Artifact"}
    </span>
  );
}

function ArtifactRegistryStatusBadge({
  record,
}: {
  record: ArtifactRegistryRecord;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]",
        artifactRegistryStatusTone(record)
      )}
    >
      {record.status}
    </span>
  );
}

function ArtifactRegistryFilterField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: "text" | "date";
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-[12px] border border-[rgba(214,221,212,0.9)] bg-white/96 px-3 py-2 text-[13px] text-slate-700 outline-none placeholder:text-slate-400 focus:border-[var(--apex-accent)]"
      />
    </label>
  );
}

function ArtifactRegistryFiltersCard({
  filters,
  onChange,
  onReset,
}: {
  filters: ArtifactRegistryFilterState;
  onChange: (next: ArtifactRegistryFilterState) => void;
  onReset: () => void;
}) {
  const hasActiveFilters = artifactRegistryHasActiveFilters(filters);

  return (
    <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/92 p-4 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Registry Filters
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-500">
            These fields map directly to the backend registry contract, so each
            filter uses the exact stored `run_id`, `artifact_type`, `workflow`,
            `date`, and `dataset_id` values.
          </p>
        </div>

        {hasActiveFilters ? (
          <WorkspaceAction onClick={onReset}>
            <Files size={12} />
            Clear Filters
          </WorkspaceAction>
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <ArtifactRegistryFilterField
          label="Run ID"
          value={filters.run_id}
          onChange={(run_id) => onChange({ ...filters, run_id })}
          placeholder="run-20260322T..."
        />
        <ArtifactRegistryFilterField
          label="Artifact Type"
          value={filters.artifact_type}
          onChange={(artifact_type) => onChange({ ...filters, artifact_type })}
          placeholder="compliance_report"
        />
        <ArtifactRegistryFilterField
          label="Workflow"
          value={filters.workflow}
          onChange={(workflow) => onChange({ ...filters, workflow })}
          placeholder="rnaseq_qc_de"
        />
        <ArtifactRegistryFilterField
          label="Date"
          value={filters.date}
          onChange={(date) => onChange({ ...filters, date })}
          placeholder="YYYY-MM-DD"
          type="date"
        />
        <ArtifactRegistryFilterField
          label="Dataset ID"
          value={filters.dataset_id}
          onChange={(dataset_id) => onChange({ ...filters, dataset_id })}
          placeholder="dataset-..."
        />
      </div>

      <label className="mt-4 inline-flex items-center gap-2 rounded-full border border-[rgba(211,219,210,0.88)] bg-[rgba(248,250,246,0.94)] px-3 py-2 text-[12px] font-medium text-slate-600">
        <input
          type="checkbox"
          checked={filters.include_invalid}
          onChange={(event) =>
            onChange({ ...filters, include_invalid: event.target.checked })
          }
          className="h-4 w-4 rounded border-[rgba(211,219,210,0.9)] text-[var(--apex-accent)] focus:ring-[var(--apex-accent)]"
        />
        Include invalid registry entries
      </label>
    </div>
  );
}

function ArtifactRegistryRow({
  record,
  active,
  onSelect,
}: {
  record: ArtifactRegistryRecord;
  active: boolean;
  onSelect: () => void;
}) {
  const Icon = record.status === "invalid" ? AlertTriangle : Package;
  const metadataSummary = getArtifactRegistryMetadataSummary(record);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-[18px] border px-4 py-4 text-left transition-colors",
        active
          ? "border-[rgba(35,130,83,0.18)] bg-[rgba(35,130,83,0.08)] shadow-[0_10px_24px_rgba(35,130,83,0.08)]"
          : "border-[rgba(211,219,210,0.85)] bg-[rgba(255,255,255,0.92)] hover:border-[rgba(35,130,83,0.16)] hover:bg-[rgba(248,251,247,0.95)]"
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "mt-0.5 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[12px]",
            record.status === "invalid"
              ? "bg-[rgba(255,241,242,0.95)] text-rose-600"
              : active
                ? "bg-white text-[var(--apex-accent-strong)]"
                : "bg-[rgba(247,249,245,0.9)] text-slate-500"
          )}
        >
          <Icon size={18} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-semibold text-slate-900">
              {getArtifactRegistryDisplayName(record)}
            </p>
            <ArtifactRegistryTypeBadge record={record} />
            {record.status === "invalid" ? (
              <ArtifactRegistryStatusBadge record={record} />
            ) : null}
          </div>
          <p className="mt-2 text-[12px] leading-5 text-slate-500">
            {getArtifactRegistryDescription(record)}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
            <span>{artifactRegistryTimestampLabel(record)}</span>
            {metadataSummary.map((item) => (
              <span key={`${record.path}-${item}`}>{item}</span>
            ))}
          </div>
          <p className="mt-2 truncate font-mono text-[10px] text-slate-400">
            {shortenArtifactPath(record.path)}
          </p>
        </div>
      </div>
    </button>
  );
}

function ArtifactRegistryNavigatorCard({
  status,
  records,
  selectedPath,
  onSelect,
  error,
}: {
  status: ArtifactRegistryWorkspaceStatus;
  records: ArtifactRegistryRecord[];
  selectedPath: string | null;
  onSelect: (record: ArtifactRegistryRecord) => void;
  error: string | null;
}) {
  return (
    <div className="rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/92 p-3 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-1 pb-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Registry Browser
        </p>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          Durable BioAPEX artifacts are listed here with their actual registry
          metadata so workflow outputs, evidence, compliance reports, and
          provenance bundles remain inspectable on disk.
        </p>
      </div>

      <div className="mt-3 space-y-2">
        {status === "loading" ? (
          <WorkspaceStateCard>Loading artifact registry entries…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load the artifact registry right now."}
          </WorkspaceStateCard>
        ) : records.length === 0 ? (
          <WorkspaceStateCard>
            No artifact registry entries match the current filters.
          </WorkspaceStateCard>
        ) : (
          records.map((record) => (
            <ArtifactRegistryRow
              key={record.path}
              record={record}
              active={record.path === selectedPath}
              onSelect={() => onSelect(record)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function ArtifactRegistryDetailPane({
  status,
  record,
  error,
  preview,
  onOpenInspector,
  onOpenRunRecord,
}: {
  status: ArtifactRegistryWorkspaceStatus;
  record: ArtifactRegistryRecord | null;
  error: string | null;
  preview: {
    status: PreviewStatus;
    content: string;
    error: string | null;
  };
  onOpenInspector?: () => void;
  onOpenRunRecord?: () => void;
}) {
  const previewMode = record ? getArtifactRegistryPreviewMode(record) : null;
  const [openRawFileError, setOpenRawFileError] = useState<string | null>(null);
  const supportsRawInlinePreview = previewMode === "image" || previewMode === "pdf";
  const {
    url: rawPreviewUrl,
    error: rawPreviewError,
    loading: rawPreviewLoading,
  } = useRawPreviewObjectUrl(record?.path ?? null, supportsRawInlinePreview);

  useEffect(() => {
    setOpenRawFileError(null);
  }, [record?.path]);

  const handleOpenRawFile = () => {
    if (!record?.path) {
      return;
    }

    setOpenRawFileError(null);
    void openRawFileInNewTab(record.path).catch(() => {
      setOpenRawFileError("Could not open the raw file right now.");
    });
  };

  const previewUnavailableMessage = record
    ? record.status === "invalid"
      ? "This registry entry is invalid. Use the structured metadata and run record to inspect what failed."
      : "This artifact is tracked in the registry even though it is not previewed inline yet."
    : null;

  return (
    <div className="flex min-h-[32rem] flex-col rounded-[22px] border border-[rgba(211,219,210,0.9)] bg-white/94 shadow-[0_8px_24px_rgba(29,42,33,0.04)]">
      <div className="border-b border-[rgba(211,219,210,0.72)] px-5 py-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Structured Metadata
            </p>
            <h3 className="mt-2 text-[1.4rem] font-semibold tracking-[-0.03em] text-slate-900">
              {record ? getArtifactRegistryDisplayName(record) : "Select an artifact"}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {record
                ? getArtifactRegistryDescription(record)
                : "Choose an artifact registry entry to inspect its provenance, identifiers, and preview."}
            </p>
            {record?.path ? (
              <p className="mt-2 break-all text-[11px] text-slate-400">{record.path}</p>
            ) : null}
          </div>

          {record?.path ? (
            <div className="flex flex-wrap gap-2">
              {onOpenInspector ? (
                <WorkspaceAction onClick={onOpenInspector} tone="accent">
                  <FolderOpen size={12} />
                  Open In Inspector
                </WorkspaceAction>
              ) : null}
              <WorkspaceAction onClick={handleOpenRawFile}>
                <ExternalLink size={12} />
                Open Raw File
              </WorkspaceAction>
              {onOpenRunRecord ? (
                <WorkspaceAction onClick={onOpenRunRecord}>
                  <FileText size={12} />
                  Open Run Record
                </WorkspaceAction>
              ) : null}
            </div>
          ) : null}
        </div>

        {record ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <ArtifactRegistryTypeBadge record={record} />
            <ArtifactRegistryStatusBadge record={record} />
            <WorkspaceBadge icon={Package}>{artifactRegistryTimestampLabel(record)}</WorkspaceBadge>
            <WorkspaceBadge icon={FileText}>{shortRunLabel(record.run_id)}</WorkspaceBadge>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {status === "loading" ? (
          <WorkspaceStateCard>Loading selected registry metadata…</WorkspaceStateCard>
        ) : status === "error" ? (
          <WorkspaceStateCard tone="error">
            {error ?? "Unable to load this artifact detail right now."}
          </WorkspaceStateCard>
        ) : !record ? (
          <WorkspaceStateCard>
            Select an artifact from the registry browser to load its metadata and preview.
          </WorkspaceStateCard>
        ) : (
          <div className="space-y-4">
            {record.status === "invalid" ? (
              <WorkspaceStateCard tone="error">
                {record.error ??
                  "This registry entry is marked invalid. Review the run record or raw file path before relying on it."}
              </WorkspaceStateCard>
            ) : null}

            <section className="rounded-[20px] border border-[rgba(211,219,210,0.88)] bg-[linear-gradient(180deg,rgba(250,251,248,0.97),rgba(255,255,255,0.98))] p-4 shadow-[0_8px_20px_rgba(29,42,33,0.03)]">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Registry Fields
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Workflow
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {humanizeArtifactToken(record.workflow) ?? "Unknown workflow"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Run
                  </p>
                  <p className="mt-2 break-all text-sm font-medium text-slate-900">
                    {record.run_id}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Source
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {humanizeArtifactToken(record.source_tool) ??
                      humanizeArtifactToken(record.source_workflow) ??
                      "Registry artifact"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Dataset
                  </p>
                  <p className="mt-2 break-all text-sm font-medium text-slate-900">
                    {record.dataset_id ?? "Not recorded"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Artifact ID
                  </p>
                  <p className="mt-2 break-all text-sm font-medium text-slate-900">
                    {record.artifact_id}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Declared ID
                  </p>
                  <p className="mt-2 break-all text-sm font-medium text-slate-900">
                    {record.declared_id ?? "Not declared"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Created
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {record.created_at ?? "Unknown timestamp"}
                  </p>
                </div>
                <div className="rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Indexed
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900">
                    {record.indexed_at}
                  </p>
                </div>
              </div>

              <div className="mt-3 rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                  Path And Hash
                </p>
                <p className="mt-2 break-all text-sm font-medium text-slate-900">
                  {record.path}
                </p>
                <p className="mt-2 break-all font-mono text-[11px] text-slate-500">
                  {record.hash ?? "No content hash recorded"}
                </p>
              </div>
            </section>

            <section className="rounded-[20px] border border-[rgba(211,219,210,0.88)] bg-[linear-gradient(180deg,rgba(250,251,248,0.97),rgba(255,255,255,0.98))] p-4 shadow-[0_8px_20px_rgba(29,42,33,0.03)]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Preview
                  </p>
                  <h4 className="mt-1 text-lg font-semibold tracking-[-0.02em] text-slate-900">
                    {previewMode === "image"
                      ? "Inline image"
                      : previewMode === "pdf"
                        ? "Inline document"
                        : previewMode === "text"
                          ? "Inline snippet"
                          : "Open-backed artifact"}
                  </h4>
                </div>
                <WorkspaceAction onClick={handleOpenRawFile}>
                  <ExternalLink size={12} />
                  Open Raw File
                </WorkspaceAction>
              </div>

              <div className="mt-4 rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-white/92 px-4 py-4">
                {previewMode === "unsupported" ? (
                  <WorkspaceStateCard>{previewUnavailableMessage}</WorkspaceStateCard>
                ) : supportsRawInlinePreview && rawPreviewLoading ? (
                  <WorkspaceStateCard>Loading raw preview…</WorkspaceStateCard>
                ) : openRawFileError || rawPreviewError ? (
                  <WorkspaceStateCard tone="error">
                    {openRawFileError ?? rawPreviewError}
                  </WorkspaceStateCard>
                ) : previewMode === "image" && rawPreviewUrl ? (
                  <div className="overflow-hidden rounded-[16px] border border-[rgba(214,221,212,0.86)] bg-[rgba(248,250,246,0.95)]">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={rawPreviewUrl}
                      alt={getArtifactRegistryDisplayName(record)}
                      className="max-h-[30rem] w-full object-contain"
                    />
                  </div>
                ) : previewMode === "pdf" && rawPreviewUrl ? (
                  <iframe
                    src={rawPreviewUrl}
                    title={getArtifactRegistryDisplayName(record)}
                    className="h-[30rem] w-full rounded-[16px] border border-[rgba(214,221,212,0.86)]"
                  />
                ) : preview.status === "loading" ? (
                  <WorkspaceStateCard>Loading preview…</WorkspaceStateCard>
                ) : preview.status === "error" ? (
                  <WorkspaceStateCard tone="error">
                    {preview.error ?? "Unable to load that preview."}
                  </WorkspaceStateCard>
                ) : preview.status === "ready" ? (
                  <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-[16px] bg-[rgba(248,250,246,0.95)] px-4 py-4 font-mono text-[12px] leading-6 text-slate-700">
                    {previewText(preview.content)}
                  </pre>
                ) : (
                  <WorkspaceStateCard>
                    Select an artifact to preview it here.
                  </WorkspaceStateCard>
                )}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function ArtifactsWorkspace() {
  const {
    workspaceMode,
    inspectorPreviewPath,
    openInspectorPath,
    setWorkspaceMode,
  } = useApp();
  const [filters, setFilters] = useState<ArtifactRegistryFilterState>(
    DEFAULT_ARTIFACT_REGISTRY_FILTERS
  );
  const [workspaceStatus, setWorkspaceStatus] =
    useState<ArtifactRegistryWorkspaceStatus>("loading");
  const [lookup, setLookup] = useState<ArtifactRegistryLookupResult | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [selectedArtifactPath, setSelectedArtifactPath] = useState<string | null>(null);
  const {
    artifact_type,
    date,
    dataset_id,
    include_invalid,
    run_id,
    workflow,
  } = filters;

  useEffect(() => {
    if (workspaceMode !== "artifacts") {
      return;
    }

    let active = true;
    setWorkspaceStatus("loading");
    setWorkspaceError(null);
    const query = normalizeArtifactRegistryQuery({
      artifact_type,
      date,
      dataset_id,
      include_invalid,
      run_id,
      workflow,
    });

    void listArtifactRegistry(query)
      .then((response) => {
        if (!active) return;

        setLookup({
          ...response,
          records: sortArtifactRegistryRecords(response.records),
        });
        setWorkspaceStatus("ready");
      })
      .catch((artifactError) => {
        if (!active) return;

        setLookup(null);
        setWorkspaceStatus("error");
        setWorkspaceError(
          artifactError instanceof Error
            ? artifactError.message
            : "Unable to load artifact registry entries right now."
        );
      });

    return () => {
      active = false;
    };
  }, [
    artifact_type,
    date,
    dataset_id,
    include_invalid,
    run_id,
    workflow,
    workspaceMode,
  ]);

  const registryRecords = lookup?.records ?? EMPTY_ARTIFACT_REGISTRY_RECORDS;

  useEffect(() => {
    if (workspaceMode !== "artifacts") return;

    if (
      inspectorPreviewPath &&
      registryRecords.some((record) => record.path === inspectorPreviewPath)
    ) {
      setSelectedArtifactPath(inspectorPreviewPath);
      return;
    }

    if (
      selectedArtifactPath &&
      registryRecords.some((record) => record.path === selectedArtifactPath)
    ) {
      return;
    }

    setSelectedArtifactPath(registryRecords[0]?.path ?? null);
  }, [inspectorPreviewPath, registryRecords, selectedArtifactPath, workspaceMode]);

  const selectedRecord =
    registryRecords.find((record) => record.path === selectedArtifactPath) ??
    registryRecords[0] ??
    null;
  const preview = usePreviewContent(
    selectedRecord && isArtifactRegistryTextPreviewable(selectedRecord)
      ? selectedRecord.path
      : null
  );
  const hasActiveFilters = artifactRegistryHasActiveFilters(filters);
  const generatedAtLabel = formatArtifactRegistryGeneratedAt(
    lookup?.generated_at ?? null
  );

  return (
    <WorkspaceShell mode="artifacts">
      <WorkspaceHero
        icon={Package}
        title="Artifact Registry"
        description="Browse the real BioAPEX artifact registry across workflow outputs, evidence artifacts, compliance reports, provenance bundles, and related records without depending on chat history alone."
        badges={
          <>
            <WorkspaceBadge icon={Package}>
              {workspaceStatus === "loading"
                ? "Loading"
                : `${lookup?.matched_count ?? 0} visible`}
            </WorkspaceBadge>
            <WorkspaceBadge icon={Sparkles}>
              {hasActiveFilters ? "Filtered view" : "All records"}
            </WorkspaceBadge>
            {selectedRecord ? (
              <ArtifactRegistryTypeBadge record={selectedRecord} />
            ) : null}
          </>
        }
        actions={
          <>
            {selectedRecord?.path ? (
              <WorkspaceAction
                onClick={() => openInspectorPath(selectedRecord.path)}
                tone="accent"
              >
                <FolderOpen size={12} />
                Inspect Selected Artifact
              </WorkspaceAction>
            ) : null}
            {hasActiveFilters ? (
              <WorkspaceAction onClick={() => setFilters(DEFAULT_ARTIFACT_REGISTRY_FILTERS)}>
                <Files size={12} />
                Reset Filters
              </WorkspaceAction>
            ) : null}
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")}>
              <MessageSquare size={12} />
              Return To Session
            </WorkspaceAction>
          </>
        }
      />

      <ArtifactRegistryFiltersCard
        filters={filters}
        onChange={setFilters}
        onReset={() => setFilters(DEFAULT_ARTIFACT_REGISTRY_FILTERS)}
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <SummaryCard
          label="Visible Records"
          value={
            workspaceStatus === "loading"
              ? "Loading"
              : workspaceStatus === "error"
                ? "Issue"
                : `${lookup?.matched_count ?? 0}`
          }
          detail="Registry results stay aligned with the backend snapshot rather than a frontend-only artifact model."
        />
        <SummaryCard
          label="Snapshot Total"
          value={lookup ? `${lookup.total_count}` : "Waiting"}
          detail="The total count reflects the durable registry snapshot, even when filters narrow the visible entries."
        />
        <SummaryCard
          label="Invalid Visible"
          value={
            filters.include_invalid
              ? `${lookup?.invalid_count ?? 0}`
              : "Hidden"
          }
          detail={`Snapshot updated ${generatedAtLabel}. Invalid entries stay opt-in so broken records do not silently blend into normal browsing.`}
        />
      </div>

      {workspaceStatus === "loading" ? (
        <WorkspaceStateCard>Loading the artifact registry browser…</WorkspaceStateCard>
      ) : workspaceStatus === "error" ? (
        <WorkspaceStateCard tone="error">
          {workspaceError ?? "Unable to load the artifact registry right now."}
        </WorkspaceStateCard>
      ) : (lookup?.total_count ?? 0) === 0 ? (
        <EmptyWorkspaceState
          title="The artifact registry is empty"
          description="No durable BioAPEX artifacts are indexed yet. Run a workflow, evidence retrieval, compliance pass, or export flow and the registry browser will populate here."
          action={
            <WorkspaceAction onClick={() => setWorkspaceMode("sessions")} tone="accent">
              <MessageSquare size={12} />
              Start In Sessions
            </WorkspaceAction>
          }
        />
      ) : registryRecords.length === 0 ? (
        <EmptyWorkspaceState
          title="No artifacts match the current filters"
          description="The registry snapshot exists, but the active filter combination did not return any records. Clear the filters or broaden one of the backend field values."
          action={
            <WorkspaceAction
              onClick={() => setFilters(DEFAULT_ARTIFACT_REGISTRY_FILTERS)}
              tone="accent"
            >
              <Files size={12} />
              Clear Filters
            </WorkspaceAction>
          }
        />
      ) : (
        <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
          <ArtifactRegistryNavigatorCard
            status={workspaceStatus}
            records={registryRecords}
            selectedPath={selectedRecord?.path ?? null}
            onSelect={(record) => setSelectedArtifactPath(record.path)}
            error={workspaceError}
          />

          <ArtifactRegistryDetailPane
            status={workspaceStatus}
            record={selectedRecord}
            error={workspaceError}
            preview={preview}
            onOpenInspector={
              selectedRecord?.path
                ? () => openInspectorPath(selectedRecord.path)
                : undefined
            }
            onOpenRunRecord={
              selectedRecord
                ? () => openInspectorPath(getArtifactRegistryRunRecordPath(selectedRecord))
                : undefined
            }
          />
        </div>
      )}
    </WorkspaceShell>
  );
}

export default function WorkspacePanel() {
  const { workspaceMode } = useApp();

  return (
    <div className="relative h-full">
      <div
        className={cn("h-full", workspaceMode !== "sessions" && "hidden")}
        aria-hidden={workspaceMode !== "sessions"}
      >
        <ChatPanel />
      </div>

      {workspaceMode === "flows" ? <FlowsWorkspace /> : null}
      {workspaceMode === "docs" ? <DocsWorkspace /> : null}
      {workspaceMode === "files" ? <FilesWorkspace /> : null}
      {workspaceMode === "artifacts" ? <ArtifactsWorkspace /> : null}
    </div>
  );
}
